import equal from 'fast-deep-equal';
import {
  parseProtocol,
  type DocumentRunRequest,
  type EvaluationRequest,
  type ForkRequest,
  type ReviewRequest,
  type RunRequest,
  type Scenario,
} from './protocol';

const errorCodes = new Set([
  'provider_not_configured',
  'invalid_patch',
  'checkpoint_missing',
  'runtime_incompatible',
  'unsupported_capability',
  'source_run_active',
  'checkpoint_state_invalid',
  'checkpoint_unreadable',
  'idempotency_key_payload_conflict',
  'invalid_request',
  'scenario_not_found',
  'assessment_not_found',
  'evaluation_run_active',
  'evaluation_context_mismatch',
  'evaluator_unsupported',
  'review_evidence_mismatch',
  'review_evaluation_failed',
]);

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    code?: string,
  ) {
    super(code ?? (status === 404 ? 'run_not_found' : 'api_unavailable'));
  }
}

async function post(path: string, body?: unknown, key?: string): Promise<unknown> {
  const response = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(key ? { 'Idempotency-Key': key } : {}),
    },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const code =
      typeof payload?.detail === 'string' && errorCodes.has(payload.detail)
        ? payload.detail
        : undefined;
    throw new ApiError(response.status, code);
  }
  return response.json();
}

async function write(path: string, body?: unknown, key?: string) {
  return parseProtocol('run_view', await post(path, body, key));
}

export async function createRun(body: RunRequest, key: string) {
  const view = await write('/runs', body, key);
  if (
    view.run.mode !== body.mode ||
    view.run.parent_run_id !== null ||
    view.run.config.provider !== (body.provider ?? 'synthetic') ||
    (body.model !== null && view.run.config.requested_model !== body.model) ||
    view.run.config.fault_parameters.inject_timeout !== body.inject_timeout ||
    view.run.config.task !== body.task ||
    !equal(view.run.config.tool_policy, body.policy)
  )
    throw new Error('protocol_invalid');
  return view;
}

export async function cancelRun(runId: string) {
  const view = await write(`/runs/${encodeURIComponent(runId)}/cancel`);
  if (view.run.run_id !== runId) throw new Error('protocol_invalid');
  return view;
}

export async function getCheckpointAvailability(runId: string, signal?: AbortSignal) {
  const items = parseProtocol(
    'checkpoint_availability',
    await get(`/runs/${encodeURIComponent(runId)}/checkpoint-availability`, signal),
  );
  if (items.some((item) => item.checkpoint.run_id !== runId)) throw new Error('protocol_invalid');
  return items;
}

export async function forkRun(runId: string, body: ForkRequest, key: string) {
  const view = await write(`/runs/${encodeURIComponent(runId)}/forks`, body, key);
  if (
    view.run.parent_run_id !== runId ||
    view.run.source_checkpoint_id !== body.source_checkpoint_id ||
    !equal(view.run.intervention?.patch, body.patch)
  )
    throw new Error('protocol_invalid');
  return view;
}

async function get(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/v1${path}`, {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new ApiError(response.status);
  return response.json();
}

export async function getRuns(offset = 0, signal?: AbortSignal) {
  return parseProtocol('run_page', await get(`/runs?offset=${offset}&limit=50`, signal));
}

export async function getRun(runId: string, signal?: AbortSignal) {
  const view = parseProtocol('run_view', await get(`/runs/${encodeURIComponent(runId)}`, signal));
  if (view.run.run_id !== runId) throw new Error('protocol_invalid');
  return view;
}

export async function getScenarios(signal?: AbortSignal) {
  return parseProtocol('scenarios', await get('/scenarios', signal));
}

export async function createDocumentRun(body: DocumentRunRequest, scenario: Scenario, key: string) {
  const view = await write(
    `/scenarios/${encodeURIComponent(scenario.definition.ref.id)}/runs`,
    body,
    key,
  );
  const variant =
    body.variant === 'baseline' ? scenario.definition.baseline : scenario.definition.candidate;
  if (
    view.run.mode !== body.mode ||
    view.run.parent_run_id !== null ||
    view.run.config.provider !== (body.provider ?? 'synthetic') ||
    (body.model !== null && view.run.config.requested_model !== body.model) ||
    !equal(view.run.config.experiment, scenario.definition.ref) ||
    !equal(view.run.config.case, scenario.case.ref) ||
    !equal(view.run.config.agent, scenario.agent.ref) ||
    !equal(view.run.config.variant, variant.ref) ||
    !equal(view.run.config.tool_policy, variant.policy) ||
    view.run.config.task !== scenario.case.task ||
    view.run.config.fixture_hash !== scenario.case.fixture_hash ||
    view.run.config.fault_parameters.inject_timeout !== false
  )
    throw new Error('protocol_invalid');
  return view;
}

const runPath = (runId: string) => `/runs/${encodeURIComponent(runId)}`;

export async function getEvaluations(runId: string, offset = 0, signal?: AbortSignal) {
  const page = parseProtocol(
    'evaluation_page',
    await get(`${runPath(runId)}/evaluations?offset=${offset}&limit=50`, signal),
  );
  if (page.items.some((item) => item.run_id !== runId)) throw new Error('protocol_invalid');
  return page;
}

export async function getEvaluation(runId: string, id: string, signal?: AbortSignal) {
  const result = parseProtocol(
    'evaluation',
    await get(`${runPath(runId)}/evaluations/${encodeURIComponent(id)}`, signal),
  );
  if (result.run_id !== runId || result.evaluation_id !== id) throw new Error('protocol_invalid');
  return result;
}

export async function getReviews(runId: string, offset = 0, signal?: AbortSignal) {
  const page = parseProtocol(
    'review_page',
    await get(`${runPath(runId)}/reviews?offset=${offset}&limit=50`, signal),
  );
  if (page.items.some((item) => item.run_id !== runId)) throw new Error('protocol_invalid');
  return page;
}

export async function evaluateRun(runId: string, body: EvaluationRequest, key: string) {
  const result = parseProtocol(
    'evaluation',
    await post(`${runPath(runId)}/evaluations`, body, key),
  );
  if (result.run_id !== runId || !equal(result.evaluator, body.evaluator))
    throw new Error('protocol_invalid');
  return result;
}

export async function reviewRun(runId: string, body: ReviewRequest, key: string) {
  const result = parseProtocol('human_review', await post(`${runPath(runId)}/reviews`, body, key));
  if (
    result.run_id !== runId ||
    Object.entries(body).some(([key, value]) => !equal(result[key as keyof typeof result], value))
  )
    throw new Error('protocol_invalid');
  return result;
}
