import { parseProtocol } from './protocol';

export class ApiError extends Error {
  constructor(public readonly status: number) {
    super(status === 404 ? 'run_not_found' : 'api_unavailable');
  }
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
