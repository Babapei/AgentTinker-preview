/* Generated from Pydantic serialization schemas. Run npm run schema. */

export type AllowedPatchFields = ('tool_retry_limit' | 'top_k')[];
export type Available = boolean;
export type Adapter = string;
export type AgentVersion = string;
export type AllowedPatchFields1 = ('tool_retry_limit' | 'top_k')[];
export type Boundary = 'before_tool';
export type CheckpointId = string;
export type JsonValue = unknown;
export type RunId = string;
export type RuntimeVersion = string;
export type SchemaVersion = '0.1';
export type Reason =
  | (
      | 'unsupported_capability'
      | 'source_run_active'
      | 'checkpoint_missing'
      | 'runtime_incompatible'
      | 'checkpoint_state_invalid'
      | 'checkpoint_unreadable'
    )
  | null;
export type CheckpointAvailability = CheckpointAvailability1[];
export type Mode = 'live' | 'synthetic';
export type Model = string | null;
export type Provider = ('openai' | 'deepseek') | null;
export type Variant = 'baseline' | 'candidate';
export type AnswerReview = 'unreviewed';
export type Id = string;
export type Version = string;
export type CheckId = string;
export type Explanation = string;
export type SchemaVersion1 = '0.1';
export type SpanIds = string[];
export type Verdict = 'pass' | 'fail' | 'unknown';
export type Checks = EvidenceCheck[];
export type CitedDocumentIds = string[];
export type CreatedAt = string;
export type EvaluationId = string;
export type ExecutionStatus = string;
export type FailureCode = string | null;
export type InputHash = string;
export type ReadDocumentIds = string[];
export type ReturnedDocumentIds = string[];
export type RunId1 = string;
export type SampleSize = 1;
export type SchemaVersion2 = '0.1';
export type StatisticalConclusion = false;
export type Status = 'completed' | 'failed';
export type Items = EvaluationResult[];
export type NextOffset = number | null;
export type Total = number;
export type Event =
  | RunCreated
  | RunStatusChanged
  | SpanStarted
  | SpanFinished
  | ToolAttemptFailed
  | ToolRetryScheduled
  | CheckpointSaved;
export type Attempt = number | null;
export type ForkFromCheckpoint = boolean;
export type ParallelFork = false;
export type PatchArbitraryState = false;
export type PatchToolPolicy = boolean;
export type PauseLiveExecution = false;
export type RecordPlayback = boolean;
export type RunFromStart = boolean;
export type TraceView = boolean;
export type FixtureHash = string | null;
export type PriceVersion = string | null;
export type PromptVersion = string | null;
export type Provider1 = string | null;
export type RequestedModel = string | null;
export type Task = string | null;
export type CreatedAt1 = string;
export type InheritedSpanIds = string[];
export type InterventionId = string;
export type ParentRunId = string;
export type SchemaVersion3 = '0.1';
export type SourceCheckpointId = string;
export type Mode1 = 'live' | 'recorded' | 'synthetic' | 'imported';
export type ParentRunId1 = string | null;
export type RunId2 = string;
export type SchemaVersion4 = '0.1';
export type SourceCheckpointId1 = string | null;
export type RunStatus =
  'queued' | 'running' | 'cancel_requested' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';
export type UpdatedAt = string;
export type EventId = string;
export type LogicalCallId = string | null;
export type LogicalNodeId = string | null;
export type OccurredAt = string;
export type ParentSpanId = string | null;
export type ReceivedAt = string;
export type RunId3 = string;
export type SchemaVersion5 = '0.1';
export type Seq = number;
export type SpanId = string | null;
export type Type = 'run.created';
export type Attempt1 = number | null;
export type RunStatus1 =
  'queued' | 'running' | 'cancel_requested' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';
export type Reason1 = string | null;
export type EventId1 = string;
export type LogicalCallId1 = string | null;
export type LogicalNodeId1 = string | null;
export type OccurredAt1 = string;
export type ParentSpanId1 = string | null;
export type ReceivedAt1 = string;
export type RunId4 = string;
export type SchemaVersion6 = '0.1';
export type Seq1 = number;
export type SpanId1 = string | null;
export type Type1 = 'run.status_changed';
export type Attempt2 = number | null;
export type Attempt3 = number | null;
export type CallIndex = number;
export type Amount = string | null;
export type Currency = string | null;
export type EvidenceArtifactId = string | null;
export type Kind = 'unknown' | 'estimate' | 'actual';
export type PriceVersion1 = string | null;
export type DurationMs = number | null;
export type EndedAt = string | null;
export type Input = {
  [k: string]: JsonValue;
} | null;
export type Kind1 = 'model' | 'tool' | 'evaluation';
export type LogicalCallId2 = string | null;
export type LogicalNodeId2 = string;
export type Model1 = string | null;
export type Output = {
  [k: string]: JsonValue;
} | null;
export type ParentSpanId2 = string | null;
export type Provider2 = string | null;
export type RunId5 = string;
export type SchemaVersion7 = '0.1';
export type SpanId2 = string;
export type StartedAt = string;
export type Status1 = 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';
export type CachedInputTokens = number | null;
export type CompletionTokens = number | null;
export type PromptTokens = number | null;
export type Raw = {
  [k: string]: JsonValue;
} | null;
export type TotalTokens = number | null;
export type UncachedInputTokens = number | null;
export type EventId2 = string;
export type LogicalCallId3 = string | null;
export type LogicalNodeId3 = string | null;
export type OccurredAt2 = string;
export type ParentSpanId3 = string | null;
export type ReceivedAt2 = string;
export type RunId6 = string;
export type SchemaVersion8 = '0.1';
export type Seq2 = number;
export type SpanId3 = string;
export type Type2 = 'span.started';
export type Attempt4 = number | null;
export type EventId3 = string;
export type LogicalCallId4 = string | null;
export type LogicalNodeId4 = string | null;
export type OccurredAt3 = string;
export type ParentSpanId4 = string | null;
export type ReceivedAt3 = string;
export type RunId7 = string;
export type SchemaVersion9 = '0.1';
export type Seq3 = number;
export type SpanId4 = string;
export type Type3 = 'span.finished';
export type Attempt5 = number;
export type ErrorCode = string;
export type FaultPlanId = string | null;
export type Origin = 'injected' | 'tool' | 'provider' | 'executor';
export type RetryOwner = 'executor' | 'agent';
export type WillRetry = boolean;
export type EventId4 = string;
export type LogicalCallId5 = string;
export type LogicalNodeId5 = string | null;
export type OccurredAt4 = string;
export type ParentSpanId5 = string | null;
export type ReceivedAt4 = string;
export type RunId8 = string;
export type SchemaVersion10 = '0.1';
export type Seq4 = number;
export type SpanId5 = string;
export type Type4 = 'tool.attempt_failed';
export type Attempt6 = number;
export type NextAttempt = number;
export type RetryOwner1 = 'executor';
export type EventId5 = string;
export type LogicalCallId6 = string;
export type LogicalNodeId6 = string | null;
export type OccurredAt5 = string;
export type ParentSpanId6 = string | null;
export type ReceivedAt5 = string;
export type RunId9 = string;
export type SchemaVersion11 = '0.1';
export type Seq5 = number;
export type SpanId6 = string;
export type Type5 = 'tool.retry_scheduled';
export type Attempt7 = number | null;
export type EventId6 = string;
export type LogicalCallId7 = string | null;
export type LogicalNodeId7 = string | null;
export type OccurredAt6 = string;
export type ParentSpanId7 = string | null;
export type ReceivedAt6 = string;
export type RunId10 = string;
export type SchemaVersion12 = '0.1';
export type Seq6 = number;
export type SpanId7 = string | null;
export type Type6 = 'checkpoint.saved';
export type SourceCheckpointId2 = string;
export type CreatedAt2 = string;
export type EvaluationId1 = string;
export type Explanation1 = string;
export type InputHash1 = string;
export type Judgement = 'supported' | 'justified_insufficiency' | 'unsupported' | 'uncertain';
export type ReviewId = string;
export type Reviewer = string;
export type RunId11 = string;
export type SchemaVersion13 = '0.1';
export type Claim = 'unverified_source_record';
export type MaxModelCalls = number;
export type PromptVersion1 = string;
export type SchemaVersion14 = '0.1';
export type SystemPrompt = string;
export type Case = DatasetCase | ExecutionCase;
export type FixtureHash1 = string;
/**
 * @minItems 1
 */
export type RequiredDocumentIds = [string, ...string[]];
/**
 * @minItems 1
 */
export type RequiredFacts = [FactRequirement, ...FactRequirement[]];
export type Description = string;
/**
 * @minItems 1
 */
export type DocumentIds = [string, ...string[]];
export type FactId = string;
export type SchemaVersion15 = '0.1';
export type SchemaVersion16 = '0.1';
export type Task1 = string;
export type ExpectedExecution = string;
export type FixtureHash2 = string;
export type SchemaVersion17 = '0.1';
export type Task2 = string;
export type Description1 = string;
export type Kind2 = 'rule' | 'human';
export type SchemaVersion18 = '0.1';
export type Evaluators = EvaluatorDefinition[];
export type AllowedVariables = ('tool_retry_limit' | 'top_k')[];
export type ToolRetryLimit = number;
export type TopK = number;
export type Role = 'baseline' | 'candidate';
export type SchemaVersion19 = '0.1';
export type Description2 = string;
export type License = string | null;
export type SchemaVersion20 = '0.1';
export type Source = string;
/**
 * @minItems 1
 */
export type SuccessCriteria = [string, ...string[]];
export type Title = string;
export type DocumentId = string;
export type SchemaVersion21 = '0.1';
export type Text = string;
export type Title1 = string;
export type Documents = Document[];
export type HashMethod = 'legacy-document-list-v1' | 'document-case-v1';
export type SchemaVersion22 = '0.1';
export type Sha256 = string;
export type Notes = string[];
export type SchemaVersion23 = '0.1';
export type Variants = Variant1[];
export type EvaluationId2 = string;
export type PortableInputHash = string;
export type SourceInputHash = string;
export type EvaluationBindings = EvaluationBinding[];
export type Evaluations = EvaluationResult[];
export type ImportId = string;
export type ImportedAt = string;
export type License1 = string | null;
export type LocalRunId = string;
export type PortablePackageSha256 = string;
export type PortableViewSha256 = string;
export type Reviews = HumanReview[];
export type SchemaVersion24 = '0.1';
export type Source1 = string;
export type SourceMode = 'live' | 'recorded' | 'synthetic' | 'imported';
export type SourcePackageSha256 = string;
export type SourceRunId = string;
export type SourceViewSha256 = string;
export type Title2 = string;
export type ImportId1 = string;
export type ImportedAt1 = string;
export type PortablePackageSha2561 = string;
export type RootRunId = string;
export type LocalRunId1 = string;
export type RecordPlayback1 = boolean;
export type SourceMode1 = 'live' | 'recorded' | 'synthetic' | 'imported';
export type SourceRunId1 = string;
export type Runs = ImportedRunLink[];
export type SchemaVersion25 = '0.1';
export type SourcePackageSha2561 = string;
export type Title3 = string;
export type Items1 = HumanReview[];
export type NextOffset1 = number | null;
export type Total1 = number;
export type EvaluationId3 = string;
export type Explanation2 = string;
export type InputHash2 = string;
export type Judgement1 = 'supported' | 'justified_insufficiency' | 'unsupported' | 'uncertain';
export type Reviewer1 = string;
export type Items2 = Run[];
export type NextOffset2 = number | null;
export type Total2 = number;
export type InjectTimeout = boolean;
export type Mode2 = 'live' | 'synthetic';
export type Model2 = string | null;
export type Provider3 = ('openai' | 'deepseek') | null;
export type Task3 = string;
export type Checkpoints = CheckpointRef[];
export type LastSeq = number;
export type SchemaVersion26 = '0.1';
export type Spans = Span[];
export type Documents1 = Document[];
export type SchemaVersion27 = '0.1';
export type Scenarios = Scenario[];
export type Items3 = Span[];
export type NextOffset3 = number | null;
export type Total3 = number;

export interface RuntimeProtocol {
  checkpoint_availability: CheckpointAvailability;
  document_run_request: DocumentRunRequest;
  evaluation: EvaluationResult;
  evaluation_page: EvaluationPage;
  evaluation_request: EvaluationRequest;
  event: Event;
  fork_request: ForkRequest;
  human_review: HumanReview;
  import_provenance: ImportProvenance | null;
  import_result: ImportResult;
  review_page: ReviewPage;
  review_request: ReviewRequest;
  run_page: RunPage;
  run_request: RunRequest;
  run_view: RunView;
  scenarios: Scenarios;
  span_page: SpanPage;
}
export interface CheckpointAvailability1 {
  allowed_patch_fields: AllowedPatchFields;
  available: Available;
  checkpoint: CheckpointRef;
  reason: Reason;
}
export interface CheckpointRef {
  adapter: Adapter;
  agent_version: AgentVersion;
  allowed_patch_fields: AllowedPatchFields1;
  boundary: Boundary;
  checkpoint_id: CheckpointId;
  locator: Locator;
  run_id: RunId;
  runtime_version: RuntimeVersion;
  schema_version: SchemaVersion;
  tool_versions: ToolVersions;
}
export interface Locator {
  [k: string]: JsonValue;
}
export interface ToolVersions {
  /**
   * This interface was referenced by `ToolVersions`'s JSON-Schema definition
   * via the `patternProperty` "^[A-Za-z0-9][A-Za-z0-9_.:-]*$".
   */
  [k: string]: string;
}
export interface DocumentRunRequest {
  mode: Mode;
  model: Model;
  provider: Provider;
  variant: Variant;
}
export interface EvaluationResult {
  answer_review: AnswerReview;
  case: VersionRef;
  checks: Checks;
  cited_document_ids: CitedDocumentIds;
  created_at: CreatedAt;
  evaluation_id: EvaluationId;
  evaluator: VersionRef;
  execution_status: ExecutionStatus;
  failure_code: FailureCode;
  input_hash: InputHash;
  read_document_ids: ReadDocumentIds;
  returned_document_ids: ReturnedDocumentIds;
  run_id: RunId1;
  sample_size: SampleSize;
  schema_version: SchemaVersion2;
  statistical_conclusion: StatisticalConclusion;
  status: Status;
}
export interface VersionRef {
  id: Id;
  version: Version;
}
export interface EvidenceCheck {
  check_id: CheckId;
  explanation: Explanation;
  schema_version: SchemaVersion1;
  span_ids: SpanIds;
  verdict: Verdict;
}
export interface EvaluationPage {
  items: Items;
  next_offset: NextOffset;
  total: Total;
}
export interface EvaluationRequest {
  evaluator: VersionRef1;
}
export interface VersionRef1 {
  id: Id;
  version: Version;
}
export interface RunCreated {
  attempt: Attempt;
  data: Run;
  event_id: EventId;
  logical_call_id: LogicalCallId;
  logical_node_id: LogicalNodeId;
  occurred_at: OccurredAt;
  parent_span_id: ParentSpanId;
  received_at: ReceivedAt;
  run_id: RunId3;
  schema_version: SchemaVersion5;
  seq: Seq;
  span_id: SpanId;
  type: Type;
}
export interface Run {
  capabilities: Capabilities;
  config: RunConfig;
  created_at: CreatedAt1;
  inherited_span_ids: InheritedSpanIds;
  intervention: Intervention | null;
  mode: Mode1;
  parent_run_id: ParentRunId1;
  run_id: RunId2;
  schema_version: SchemaVersion4;
  source_checkpoint_id: SourceCheckpointId1;
  status: RunStatus;
  updated_at: UpdatedAt;
}
export interface Capabilities {
  fork_from_checkpoint: ForkFromCheckpoint;
  parallel_fork: ParallelFork;
  patch_arbitrary_state: PatchArbitraryState;
  patch_tool_policy: PatchToolPolicy;
  pause_live_execution: PauseLiveExecution;
  record_playback: RecordPlayback;
  run_from_start: RunFromStart;
  trace_view: TraceView;
}
export interface RunConfig {
  agent: VersionRef;
  case: VersionRef | null;
  evaluator_versions: EvaluatorVersions;
  experiment: VersionRef | null;
  fault_parameters: FaultParameters;
  fault_plan: VersionRef | null;
  fixture_hash: FixtureHash;
  model_parameters: ModelParameters;
  price_version: PriceVersion;
  prompt_version: PromptVersion;
  provider: Provider1;
  requested_model: RequestedModel;
  runtime_versions: RuntimeVersions;
  task: Task;
  tool_policy: ToolPolicy;
  tool_versions: ToolVersions1;
  variant: VersionRef | null;
}
export interface EvaluatorVersions {
  /**
   * This interface was referenced by `EvaluatorVersions`'s JSON-Schema definition
   * via the `patternProperty` "^[A-Za-z0-9][A-Za-z0-9_.:-]*$".
   */
  [k: string]: string;
}
export interface FaultParameters {
  [k: string]: JsonValue;
}
export interface ModelParameters {
  [k: string]: JsonValue;
}
export interface RuntimeVersions {
  /**
   * This interface was referenced by `RuntimeVersions`'s JSON-Schema definition
   * via the `patternProperty` "^[A-Za-z0-9][A-Za-z0-9_.:-]*$".
   */
  [k: string]: string;
}
export interface ToolPolicy {
  [k: string]: JsonValue;
}
export interface ToolVersions1 {
  /**
   * This interface was referenced by `ToolVersions1`'s JSON-Schema definition
   * via the `patternProperty` "^[A-Za-z0-9][A-Za-z0-9_.:-]*$".
   */
  [k: string]: string;
}
export interface Intervention {
  after: After;
  before: Before;
  intervention_id: InterventionId;
  parent_run_id: ParentRunId;
  patch: Patch;
  schema_version: SchemaVersion3;
  source_checkpoint_id: SourceCheckpointId;
}
export interface After {
  [k: string]: JsonValue;
}
export interface Before {
  [k: string]: JsonValue;
}
export interface Patch {
  [k: string]: JsonValue;
}
export interface RunStatusChanged {
  attempt: Attempt1;
  data: StatusChange;
  event_id: EventId1;
  logical_call_id: LogicalCallId1;
  logical_node_id: LogicalNodeId1;
  occurred_at: OccurredAt1;
  parent_span_id: ParentSpanId1;
  received_at: ReceivedAt1;
  run_id: RunId4;
  schema_version: SchemaVersion6;
  seq: Seq1;
  span_id: SpanId1;
  type: Type1;
}
export interface StatusChange {
  after: RunStatus1;
  before: RunStatus1;
  reason: Reason1;
}
export interface SpanStarted {
  attempt: Attempt2;
  data: Span;
  event_id: EventId2;
  logical_call_id: LogicalCallId3;
  logical_node_id: LogicalNodeId3;
  occurred_at: OccurredAt2;
  parent_span_id: ParentSpanId3;
  received_at: ReceivedAt2;
  run_id: RunId6;
  schema_version: SchemaVersion8;
  seq: Seq2;
  span_id: SpanId3;
  type: Type2;
}
export interface Span {
  attempt: Attempt3;
  call_index: CallIndex;
  cost: Cost;
  duration_ms: DurationMs;
  ended_at: EndedAt;
  input: Input;
  kind: Kind1;
  logical_call_id: LogicalCallId2;
  logical_node_id: LogicalNodeId2;
  model: Model1;
  output: Output;
  parent_span_id: ParentSpanId2;
  provider: Provider2;
  run_id: RunId5;
  schema_version: SchemaVersion7;
  span_id: SpanId2;
  started_at: StartedAt;
  status: Status1;
  usage: Usage;
}
export interface Cost {
  amount: Amount;
  currency: Currency;
  evidence_artifact_id: EvidenceArtifactId;
  kind: Kind;
  price_version: PriceVersion1;
}
export interface Usage {
  cached_input_tokens: CachedInputTokens;
  completion_tokens: CompletionTokens;
  prompt_tokens: PromptTokens;
  raw: Raw;
  total_tokens: TotalTokens;
  uncached_input_tokens: UncachedInputTokens;
}
export interface SpanFinished {
  attempt: Attempt4;
  data: Span;
  event_id: EventId3;
  logical_call_id: LogicalCallId4;
  logical_node_id: LogicalNodeId4;
  occurred_at: OccurredAt3;
  parent_span_id: ParentSpanId4;
  received_at: ReceivedAt3;
  run_id: RunId7;
  schema_version: SchemaVersion9;
  seq: Seq3;
  span_id: SpanId4;
  type: Type3;
}
export interface ToolAttemptFailed {
  attempt: Attempt5;
  data: ToolFailure;
  event_id: EventId4;
  logical_call_id: LogicalCallId5;
  logical_node_id: LogicalNodeId5;
  occurred_at: OccurredAt4;
  parent_span_id: ParentSpanId5;
  received_at: ReceivedAt4;
  run_id: RunId8;
  schema_version: SchemaVersion10;
  seq: Seq4;
  span_id: SpanId5;
  type: Type4;
}
export interface ToolFailure {
  error_code: ErrorCode;
  fault_plan_id: FaultPlanId;
  origin: Origin;
  retry_owner: RetryOwner;
  will_retry: WillRetry;
}
export interface ToolRetryScheduled {
  attempt: Attempt6;
  data: Retry;
  event_id: EventId5;
  logical_call_id: LogicalCallId6;
  logical_node_id: LogicalNodeId6;
  occurred_at: OccurredAt5;
  parent_span_id: ParentSpanId6;
  received_at: ReceivedAt5;
  run_id: RunId9;
  schema_version: SchemaVersion11;
  seq: Seq5;
  span_id: SpanId6;
  type: Type5;
}
export interface Retry {
  next_attempt: NextAttempt;
  retry_owner: RetryOwner1;
}
export interface CheckpointSaved {
  attempt: Attempt7;
  data: CheckpointRef;
  event_id: EventId6;
  logical_call_id: LogicalCallId7;
  logical_node_id: LogicalNodeId7;
  occurred_at: OccurredAt6;
  parent_span_id: ParentSpanId7;
  received_at: ReceivedAt6;
  run_id: RunId10;
  schema_version: SchemaVersion12;
  seq: Seq6;
  span_id: SpanId7;
  type: Type6;
}
export interface ForkRequest {
  patch: Patch1;
  source_checkpoint_id: SourceCheckpointId2;
}
export interface Patch1 {
  [k: string]: JsonValue;
}
export interface HumanReview {
  created_at: CreatedAt2;
  evaluation_id: EvaluationId1;
  evaluator: VersionRef2;
  explanation: Explanation1;
  fact_coverage: FactCoverage;
  input_hash: InputHash1;
  judgement: Judgement;
  review_id: ReviewId;
  reviewer: Reviewer;
  run_id: RunId11;
  schema_version: SchemaVersion13;
}
export interface VersionRef2 {
  id: Id;
  version: Version;
}
export interface FactCoverage {
  /**
   * This interface was referenced by `FactCoverage`'s JSON-Schema definition
   * via the `patternProperty` "^[A-Za-z0-9][A-Za-z0-9_.:-]*$".
   */
  [k: string]: 'covered' | 'missing' | 'uncertain';
}
export interface ImportProvenance {
  claim: Claim;
  context: ExperimentContext | null;
  evaluation_bindings: EvaluationBindings;
  evaluations: Evaluations;
  import_id: ImportId;
  imported_at: ImportedAt;
  license: License1;
  local_run_id: LocalRunId;
  portable_package_sha256: PortablePackageSha256;
  portable_view_sha256: PortableViewSha256;
  reviews: Reviews;
  schema_version: SchemaVersion24;
  source: Source1;
  source_mode: SourceMode;
  source_package_sha256: SourcePackageSha256;
  source_run_id: SourceRunId;
  source_view_sha256: SourceViewSha256;
  title: Title2;
}
export interface ExperimentContext {
  agent: AgentDefinition;
  case: Case;
  evaluators: Evaluators;
  experiment: ExperimentDefinition;
  fixture: Fixture;
  notes: Notes;
  schema_version: SchemaVersion23;
  variants: Variants;
}
export interface AgentDefinition {
  max_model_calls: MaxModelCalls;
  prompt_version: PromptVersion1;
  ref: VersionRef;
  schema_version: SchemaVersion14;
  system_prompt: SystemPrompt;
  tool_schemas: ToolSchemas;
  tool_versions: ToolVersions2;
}
export interface ToolSchemas {
  /**
   * This interface was referenced by `ToolSchemas`'s JSON-Schema definition
   * via the `patternProperty` "^[A-Za-z0-9][A-Za-z0-9_.:-]*$".
   */
  [k: string]: {
    [k: string]: JsonValue;
  };
}
export interface ToolVersions2 {
  /**
   * This interface was referenced by `ToolVersions2`'s JSON-Schema definition
   * via the `patternProperty` "^[A-Za-z0-9][A-Za-z0-9_.:-]*$".
   */
  [k: string]: string;
}
export interface DatasetCase {
  fixture: VersionRef;
  fixture_hash: FixtureHash1;
  ref: VersionRef;
  required_document_ids: RequiredDocumentIds;
  required_facts: RequiredFacts;
  schema_version: SchemaVersion16;
  task: Task1;
}
export interface FactRequirement {
  description: Description;
  document_ids: DocumentIds;
  fact_id: FactId;
  schema_version: SchemaVersion15;
}
export interface ExecutionCase {
  expected_execution: ExpectedExecution;
  fixture: VersionRef;
  fixture_hash: FixtureHash2;
  ref: VersionRef;
  schema_version: SchemaVersion17;
  task: Task2;
}
export interface EvaluatorDefinition {
  description: Description1;
  kind: Kind2;
  ref: VersionRef;
  schema_version: SchemaVersion18;
}
export interface ExperimentDefinition {
  agent: VersionRef;
  allowed_variables: AllowedVariables;
  baseline: Variant1;
  candidate: Variant1;
  case: VersionRef;
  description: Description2;
  license: License;
  ref: VersionRef;
  schema_version: SchemaVersion20;
  source: Source;
  success_criteria: SuccessCriteria;
  title: Title;
}
export interface Variant1 {
  policy: ToolPolicy1;
  ref: VersionRef;
  role: Role;
  schema_version: SchemaVersion19;
}
export interface ToolPolicy1 {
  tool_retry_limit: ToolRetryLimit;
  top_k: TopK;
}
export interface Fixture {
  documents: Documents;
  hash_method: HashMethod;
  ref: VersionRef;
  schema_version: SchemaVersion22;
  sha256: Sha256;
}
export interface Document {
  document_id: DocumentId;
  schema_version: SchemaVersion21;
  text: Text;
  title: Title1;
}
export interface EvaluationBinding {
  evaluation_id: EvaluationId2;
  portable_input_hash: PortableInputHash;
  source_input_hash: SourceInputHash;
}
export interface ImportResult {
  import_id: ImportId1;
  imported_at: ImportedAt1;
  portable_package_sha256: PortablePackageSha2561;
  root_run_id: RootRunId;
  runs: Runs;
  schema_version: SchemaVersion25;
  source_package_sha256: SourcePackageSha2561;
  title: Title3;
}
export interface ImportedRunLink {
  local_run_id: LocalRunId1;
  record_playback: RecordPlayback1;
  source_mode: SourceMode1;
  source_run_id: SourceRunId1;
}
export interface ReviewPage {
  items: Items1;
  next_offset: NextOffset1;
  total: Total1;
}
export interface ReviewRequest {
  evaluation_id: EvaluationId3;
  explanation: Explanation2;
  fact_coverage: FactCoverage1;
  input_hash: InputHash2;
  judgement: Judgement1;
  reviewer: Reviewer1;
}
export interface FactCoverage1 {
  /**
   * This interface was referenced by `FactCoverage1`'s JSON-Schema definition
   * via the `patternProperty` "^[A-Za-z0-9][A-Za-z0-9_.:-]*$".
   */
  [k: string]: 'covered' | 'missing' | 'uncertain';
}
export interface RunPage {
  items: Items2;
  next_offset: NextOffset2;
  total: Total2;
}
export interface RunRequest {
  inject_timeout: InjectTimeout;
  mode: Mode2;
  model: Model2;
  policy: ToolPolicy1;
  provider: Provider3;
  task: Task3;
}
export interface RunView {
  checkpoints: Checkpoints;
  last_seq: LastSeq;
  run: Run;
  schema_version: SchemaVersion26;
  spans: Spans;
}
export interface Scenario {
  agent: AgentDefinition;
  case: DatasetCase;
  definition: ExperimentDefinition;
  documents: Documents1;
  schema_version: SchemaVersion27;
}
export interface SpanPage {
  items: Items3;
  next_offset: NextOffset3;
  total: Total3;
}
