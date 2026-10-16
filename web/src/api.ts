import equal from 'fast-deep-equal';
import { parseProtocol, type ForkRequest, type RunRequest } from './protocol';

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
]);

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    code?: string,
  ) {
    super(code ?? (status === 404 ? 'run_not_found' : 'api_unavailable'));
  }
}

async function write(path: string, body?: unknown, key?: string) {
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
  return parseProtocol('run_view', await response.json());
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
