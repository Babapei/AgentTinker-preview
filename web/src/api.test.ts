import { afterEach, expect, it, vi } from 'vitest';
import { ApiError, cancelRun, createRun, getRun, getRuns } from './api';
import type { RunRequest } from './protocol';
import fixture from './test/fixtures/retried-run.json';

afterEach(() => vi.unstubAllGlobals());

it('reads encoded run identity and propagates cancellation without dispatching', async () => {
  const encodedFixture = structuredClone(fixture);
  encodedFixture.run.run_id = 'run:example';
  const fetcher = vi.fn().mockResolvedValue(Response.json(encodedFixture));
  vi.stubGlobal('fetch', fetcher);
  const controller = new AbortController();
  expect(await getRun('run:example', controller.signal)).toEqual(encodedFixture);
  expect(fetcher).toHaveBeenCalledWith('/api/v1/runs/run%3Aexample', {
    signal: controller.signal,
    headers: { Accept: 'application/json' },
  });
});

it('retains pagination from the history response', async () => {
  const page = { items: [fixture.run], total: 51, next_offset: 50 };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(page)));
  expect(await getRuns()).toEqual(page);
});

it('returns a stable missing-run error without exposing the response body', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response('private-server-error', { status: 404 })),
  );
  await expect(getRun('missing')).rejects.toEqual(new ApiError(404));
});

it('rejects an unrecognized successful response', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ status: 'all-good' })));
  await expect(getRun('wrong-contract')).rejects.toThrow('protocol_invalid');
});

it('rejects a different run returned under the requested identity', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(fixture)));
  await expect(getRun('run_different')).rejects.toThrow('protocol_invalid');
});

it('writes an explicit run once with the caller idempotency key and validates its provenance', async () => {
  const body: RunRequest = {
    mode: 'synthetic',
    task: fixture.run.config.task,
    provider: null,
    model: null,
    policy: { tool_retry_limit: 1, top_k: 2 },
    inject_timeout: true,
  };
  const fetcher = vi.fn().mockImplementation(async () => Response.json(fixture));
  vi.stubGlobal('fetch', fetcher);
  expect(await createRun(body, 'durable-key')).toEqual(fixture);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][1].headers['Idempotency-Key']).toBe('durable-key');
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(body);
  await expect(createRun({ ...body, mode: 'live' }, 'other-key')).rejects.toThrow(
    'protocol_invalid',
  );
});

it('keeps cancel response identity and safe operation errors', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(fixture)));
  await expect(cancelRun('another-run')).rejects.toThrow('protocol_invalid');
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(Response.json({ detail: 'provider_not_configured' }, { status: 503 })),
  );
  await expect(cancelRun('a')).rejects.toThrow('provider_not_configured');
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(Response.json({ detail: 'private-server-text' }, { status: 500 })),
  );
  await expect(cancelRun('a')).rejects.toThrow('api_unavailable');
});
