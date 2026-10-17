"""Native offline fixtures for browser wire validation; no credentials or provider calls."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agenttinker.experiments import documents as corpus
from agenttinker.experiments.evaluation import EvaluationRequest, ReviewRequest
from agenttinker.runtime.service import DocumentRunRequest, RunService
from agenttinker.storage.evaluations import SQLiteEvaluationStore


def main():
    with TemporaryDirectory(prefix="agenttinker-assessments-") as directory:
        database = Path(directory) / "runs.sqlite"
        with RunService(database) as service:
            view, _ = service.submit_document(DocumentRunRequest(mode="synthetic"), "A")
            view = service.wait(view.run.run_id)
        with SQLiteEvaluationStore(database) as store:
            result, _ = store.create_evaluation(view.run.run_id, EvaluationRequest(), "evaluation")
            review, _ = store.create_review(
                view.run.run_id,
                ReviewRequest(
                    evaluation_id=result.evaluation_id,
                    input_hash=result.input_hash,
                    reviewer="offline test fixture",
                    fact_coverage={"configurable-retries": "covered", "citation-fix": "missing"},
                    judgement="justified_insufficiency",
                    explanation="离线测试：材料不足，回答已说明。",
                ),
                "review",
            )
            fixtures = {
                "scenario": corpus.scenario(),
                "view": view,
                "evaluation": result,
                "review": review,
                "evaluation_page": store.evaluations(view.run.run_id),
                "review_page": store.reviews(view.run.run_id),
            }
            print(
                json.dumps({key: value.model_dump(mode="json") for key, value in fixtures.items()})
            )


if __name__ == "__main__":
    main()
