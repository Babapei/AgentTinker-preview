from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel

from agenttinker.core.events import parse_event
from agenttinker.core.records import Run, RunConfig, VersionRef


@pytest.fixture
def run_record():
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    return Run(
        run_id="run_A",
        mode="synthetic",
        config=RunConfig(agent=VersionRef(id="serial-agent", version="1")),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def make_event(run_record):
    def make(seq, event_type, data, **metadata):
        return parse_event(
            {
                "event_id": f"evt_{seq}",
                "run_id": run_record.run_id,
                "seq": seq,
                "occurred_at": run_record.created_at + timedelta(seconds=seq),
                "received_at": run_record.created_at + timedelta(seconds=seq),
                "type": event_type,
                "data": data.model_dump(mode="json") if isinstance(data, BaseModel) else data,
                **metadata,
            }
        )

    return make
