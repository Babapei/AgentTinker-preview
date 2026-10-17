"""Only structured observation identities change; SDK calls and user text stay intact."""

from copy import deepcopy
from uuid import uuid4

from agenttinker.core.events import parse_event
from agenttinker.core.projection import RunView, project_events
from agenttinker.core.records import Capabilities


class ImportMapping:
    def __init__(self, records, artifacts):
        self.runs = {key: f"imported_{uuid4().hex}" for key in records}
        self.spans = {
            span.span_id: f"span_{uuid4().hex}"
            for record in records.values()
            for span in record.view.spans
        }
        self.checkpoints = {
            cp.checkpoint_id: f"cp_{uuid4().hex}"
            for record in records.values()
            for cp in record.view.checkpoints
        }
        self.artifacts = {key: f"artifact_{uuid4().hex}" for key in artifacts}
        self.interventions = {
            record.view.run.intervention.intervention_id: f"intervention_{uuid4().hex}"
            for record in records.values()
            if record.view.run.intervention
        }

    def run(self, value, *, playback):
        run = deepcopy(value)
        run.update(
            run_id=self.runs[run["run_id"]],
            mode="imported",
            capabilities=Capabilities(record_playback=playback).model_dump(mode="json"),
        )
        if run["parent_run_id"] is not None:
            run["parent_run_id"] = self.runs[run["parent_run_id"]]
            run["source_checkpoint_id"] = self.checkpoints[run["source_checkpoint_id"]]
        run["inherited_span_ids"] = [self.spans[key] for key in run["inherited_span_ids"]]
        if run["intervention"] is not None:
            intervention = run["intervention"]
            intervention.update(
                intervention_id=self.interventions[intervention["intervention_id"]],
                parent_run_id=self.runs[intervention["parent_run_id"]],
                source_checkpoint_id=self.checkpoints[intervention["source_checkpoint_id"]],
            )
        return run

    def span(self, value):
        span = deepcopy(value)
        span.update(span_id=self.spans[span["span_id"]], run_id=self.runs[span["run_id"]])
        if span["parent_span_id"] is not None:
            span["parent_span_id"] = self.spans[span["parent_span_id"]]
        if span["cost"]["evidence_artifact_id"] is not None:
            span["cost"]["evidence_artifact_id"] = self.artifacts[
                span["cost"]["evidence_artifact_id"]
            ]
        intervention = span["input"].get("intervention_id") if span["input"] is not None else None
        if isinstance(intervention, str) and intervention in self.interventions:
            span["input"]["intervention_id"] = self.interventions[intervention]
        return span

    def checkpoint(self, value):
        cp = deepcopy(value)
        cp.update(
            checkpoint_id=self.checkpoints[cp["checkpoint_id"]],
            run_id=self.runs[cp["run_id"]],
            locator={},
            allowed_patch_fields=[],
        )
        return cp

    def observations(self, record):
        playback = record.events is not None
        value = record.view.model_dump(mode="json")
        value["run"] = self.run(value["run"], playback=playback)
        value["spans"] = [self.span(span) for span in value["spans"]]
        value["checkpoints"] = [self.checkpoint(cp) for cp in value["checkpoints"]]
        view = RunView.model_validate(value)
        if not playback:
            return view, ()
        events = []
        for original in record.events:
            event = original.model_dump(mode="json")
            event.update(event_id=f"evt_{uuid4().hex}", run_id=self.runs[event["run_id"]])
            for field in ("span_id", "parent_span_id"):
                if event[field] is not None:
                    event[field] = self.spans[event[field]]
            if event["type"] == "run.created":
                event["data"] = self.run(event["data"], playback=True)
            elif event["type"] in {"span.started", "span.finished"}:
                event["data"] = self.span(event["data"])
            elif event["type"] == "checkpoint.saved":
                event["data"] = self.checkpoint(event["data"])
            events.append(parse_event(event))
        if project_events(events) != view:
            raise ValueError("import_projection_mismatch")
        return view, tuple(events)
