"""Immutable assessments and request identity commit together, apart from execution events."""

from datetime import UTC, datetime
from uuid import uuid4

from agenttinker.core.records import Count, Span, ValueModel
from agenttinker.core.requests import request_identity
from agenttinker.core.states import TERMINAL_STATUSES
from agenttinker.experiments import documents as corpus
from agenttinker.experiments.evaluation import (
    EvaluationRequest,
    EvaluationResult,
    HumanReview,
    ReviewRequest,
    evaluate_documents,
    evaluation_failure,
    validate_document_context,
)
from agenttinker.storage.sqlite import EventConflict, SQLiteEventStore, encode


class AssessmentRejected(Exception):
    """Stable reasons; no raw evidence, SQLite errors, or evaluator exception text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class EvaluationPage(ValueModel):
    items: tuple[EvaluationResult, ...]
    total: Count
    next_offset: Count | None


class ReviewPage(ValueModel):
    items: tuple[HumanReview, ...]
    total: Count
    next_offset: Count | None


class SQLiteEvaluationStore(SQLiteEventStore):
    def _existing_request(self, request_key, fingerprint):
        row = self._connection.execute(
            "SELECT fingerprint, evaluation_id, review_id FROM assessment_requests "
            "WHERE request_key=?",
            (request_key,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            raise EventConflict("idempotency_key_payload_conflict")
        return self._read("evaluations" if row[1] else "reviews", row[1] or row[2])

    def _read(self, table, record_id):
        column, model = (
            ("evaluation_id", EvaluationResult)
            if table == "evaluations"
            else ("review_id", HumanReview)
        )
        row = self._connection.execute(
            f"SELECT body FROM {table} WHERE {column}=?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise AssessmentRejected("assessment_not_found")
        return model.model_validate_json(row[0])

    def get_evaluation(self, run_id, evaluation_id):
        result = self._read("evaluations", evaluation_id)
        if result.run_id != run_id:
            raise AssessmentRejected("assessment_not_found")
        return result

    def get_review(self, run_id, review_id):
        result = self._read("reviews", review_id)
        if result.run_id != run_id:
            raise AssessmentRejected("assessment_not_found")
        return result

    def inherited_spans(self, view) -> tuple[Span, ...]:
        needed, found = set(view.run.inherited_span_ids), {}
        parent_id, visited = view.run.parent_run_id, {view.run.run_id}
        while needed:
            if parent_id is None or parent_id in visited:
                raise AssessmentRejected("evaluation_context_mismatch")
            visited.add(parent_id)
            parent = self.get_view(parent_id)
            if not needed <= {s.span_id for s in parent.spans} | set(parent.run.inherited_span_ids):
                raise AssessmentRejected("evaluation_context_mismatch")
            for span in parent.spans:
                if span.span_id in needed:
                    found[span.span_id] = span
                    needed.remove(span.span_id)
            parent_id = parent.run.parent_run_id
        return tuple(found[span_id] for span_id in view.run.inherited_span_ids)

    def _persist(self, result, request_key, fingerprint):
        if isinstance(result, EvaluationResult):
            table, column, record_id = "evaluations", "evaluation_id", result.evaluation_id
            self._connection.execute(
                "INSERT INTO evaluations(evaluation_id, run_id, body) VALUES (?, ?, ?)",
                (record_id, result.run_id, encode(result)),
            )
        else:
            table, column, record_id = "reviews", "review_id", result.review_id
            self._connection.execute(
                "INSERT INTO reviews(review_id, run_id, evaluation_id, body) VALUES (?, ?, ?, ?)",
                (record_id, result.run_id, result.evaluation_id, encode(result)),
            )
        self._connection.execute(
            f"INSERT INTO assessment_requests(request_key, fingerprint, {column}) VALUES (?, ?, ?)",
            (request_key, fingerprint, record_id),
        )
        return self._read(table, record_id), True

    def create_evaluation(self, run_id, request: EvaluationRequest, request_key):
        request = EvaluationRequest.model_validate_json(request.model_dump_json())
        fingerprint = request_identity(
            request_key,
            {
                "operation": "evaluate",
                "run_id": run_id,
                "request": request.model_dump(mode="json"),
            },
        )
        with self._transaction():
            if (existing := self._existing_request(request_key, fingerprint)) is not None:
                return existing, False
            view = self.get_view(run_id)
            if view.run.status not in TERMINAL_STATUSES:
                raise AssessmentRejected("evaluation_run_active")
            if request.evaluator != corpus.EVALUATOR:
                raise AssessmentRejected("evaluator_unsupported")
            inherited = self.inherited_spans(view)
            try:
                validate_document_context(view, inherited)
            except ValueError:
                raise AssessmentRejected("evaluation_context_mismatch") from None
            try:
                result = evaluate_documents(view, inherited)
            except Exception as error:
                result = evaluation_failure(
                    view, inherited, f"evaluator_error:{type(error).__name__}"
                )
            return self._persist(result, request_key, fingerprint)

    def create_review(self, run_id, request: ReviewRequest, request_key):
        request = ReviewRequest.model_validate_json(request.model_dump_json())
        fingerprint = request_identity(
            request_key,
            {
                "operation": "review",
                "run_id": run_id,
                "request": request.model_dump(mode="json"),
            },
        )
        with self._transaction():
            if (existing := self._existing_request(request_key, fingerprint)) is not None:
                return existing, False
            evaluation = self.get_evaluation(run_id, request.evaluation_id)
            if evaluation.input_hash != request.input_hash:
                raise AssessmentRejected("review_evidence_mismatch")
            if evaluation.status != "completed":
                raise AssessmentRejected("review_evaluation_failed")
            review = HumanReview(
                **request.model_dump(),
                run_id=run_id,
                review_id=f"review_{uuid4().hex}",
                created_at=datetime.now(UTC),
            )
            return self._persist(review, request_key, fingerprint)

    def _page(self, table, run_id, offset, limit):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid_assessment_page")
        self.get_view(run_id)
        # Count and items share a snapshot even when another request appends a result.
        with self._transaction():
            total = self._connection.execute(
                f"SELECT count(*) FROM {table} WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            model, page = (
                (EvaluationResult, EvaluationPage)
                if table == "evaluations"
                else (HumanReview, ReviewPage)
            )
            items = tuple(
                model.model_validate_json(row[0])
                for row in self._connection.execute(
                    f"SELECT body FROM {table} WHERE run_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (run_id, limit, offset),
                )
            )
        following = offset + len(items)
        return page(items=items, total=total, next_offset=following if following < total else None)

    def evaluations(self, run_id, *, offset=0, limit=50):
        return self._page("evaluations", run_id, offset, limit)

    def reviews(self, run_id, *, offset=0, limit=50):
        return self._page("reviews", run_id, offset, limit)

    def assessment_snapshot(self, run_id):
        """An export never mixes a new review with an older evaluation list."""
        with self._transaction():
            self.get_view(run_id)
            return tuple(
                tuple(
                    model.model_validate_json(row[0])
                    for row in self._connection.execute(
                        f"SELECT body FROM {table} WHERE run_id=? ORDER BY rowid LIMIT 1001",
                        (run_id,),
                    )
                )
                for table, model in (("evaluations", EvaluationResult), ("reviews", HumanReview))
            )
