"""Experiment identity is independent from execution status and answer judgement."""

from typing import Literal

from pydantic import Field, model_validator

from agenttinker.core.records import SHA256, Identifier, JSONData, Record, Text, VersionRef
from agenttinker.m0.models import ToolPolicy


class Document(Record):
    document_id: Identifier
    title: Text
    text: Text


class FactRequirement(Record):
    fact_id: Identifier
    description: Text
    document_ids: tuple[Identifier, ...] = Field(min_length=1)


class DatasetCase(Record):
    ref: VersionRef
    task: Text
    fixture: VersionRef
    fixture_hash: SHA256
    required_document_ids: tuple[Identifier, ...] = Field(min_length=1)
    required_facts: tuple[FactRequirement, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_requirements(self):
        if len(set(self.required_document_ids)) != len(self.required_document_ids):
            raise ValueError("duplicate_required_document")
        if len({fact.fact_id for fact in self.required_facts}) != len(self.required_facts):
            raise ValueError("duplicate_required_fact")
        if any(
            not set(fact.document_ids) <= set(self.required_document_ids)
            for fact in self.required_facts
        ):
            raise ValueError("fact_document_not_required")
        return self


class AgentDefinition(Record):
    ref: VersionRef
    prompt_version: Text
    system_prompt: Text
    tool_versions: dict[Identifier, Text]
    tool_schemas: dict[Identifier, JSONData]
    max_model_calls: int = Field(strict=True, ge=1, le=20)

    @model_validator(mode="after")
    def matching_tools(self):
        if not self.tool_versions or self.tool_versions.keys() != self.tool_schemas.keys():
            raise ValueError("agent_tool_definitions_mismatch")
        return self


class Variant(Record):
    ref: VersionRef
    policy: ToolPolicy
    role: Literal["baseline", "candidate"]


class ExperimentDefinition(Record):
    ref: VersionRef
    title: Text
    description: Text
    success_criteria: tuple[Text, ...] = Field(min_length=1)
    agent: VersionRef
    case: VersionRef
    allowed_variables: tuple[Literal["tool_retry_limit", "top_k"], ...]
    baseline: Variant
    candidate: Variant
    source: Text
    license: Text | None = None

    @model_validator(mode="after")
    def one_changed_factor(self):
        before, after = self.baseline.policy.model_dump(), self.candidate.policy.model_dump()
        changed = {key for key in before if before[key] != after[key]}
        if (
            self.baseline.role != "baseline"
            or self.candidate.role != "candidate"
            or self.baseline.ref == self.candidate.ref
            or len(changed) != 1
            or not changed <= set(self.allowed_variables)
            or len(set(self.allowed_variables)) != len(self.allowed_variables)
        ):
            raise ValueError("invalid_experiment_variants")
        return self
