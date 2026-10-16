import { afterEach, expect, it, vi } from 'vitest';
import { ApiError, getRun, getRuns } from './api';
import fixture from './test/fixtures/retried-run.json';

afterEach(() => vi.unstubAllGlobals());

it('reads encoded run identity and propagates cancellation without dispatching', async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json(fixture));
  vi.stubGlobal('fetch', fetcher);
  const controller = new AbortController();
  expect(await getRun('run:example', controller.signal)).toEqual(fixture);
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
