import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { EventLog } from './event-log';
import { followEvents } from './event-stream';
import { eventFixtures } from './test/event-fixtures';
import type { RuntimeEvent } from './protocol';

let example: ReturnType<typeof eventFixtures>['retried'];
beforeAll(() => {
  example = eventFixtures().retried;
});
afterEach(() => vi.unstubAllGlobals());

function frame(event: RuntimeEvent): string {
  return `id: ${event.run_id}:${event.seq}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}
function streamResponse(text: string) {
  const bytes = new TextEncoder().encode(text);
  return new Response(
    new ReadableStream({
      start(controller) {
        // Split inside UTF-8 characters and JSON, not only on frame boundaries.
        for (let offset = 0; offset < bytes.length; offset += 17)
          controller.enqueue(bytes.slice(offset, offset + 17));
        controller.close();
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  );
}
function options() {
  return {
    signal: new AbortController().signal,
    onUpdate: vi.fn(),
    onConnection: vi.fn(),
    retryDelay: 1,
  };
}

it('reads fragmented UTF-8 SSE facts and matches the durable final view', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(streamResponse(': keep-alive\n\n' + example.events.map(frame).join('')));
  vi.stubGlobal('fetch', fetcher);
  const log = new EventLog(example.view.run.run_id),
    callbacks = options();
  await followEvents(log, callbacks);
  expect(log.view).toEqual(example.view);
  expect(callbacks.onConnection).toHaveBeenLastCalledWith('complete');
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('reconnects after EOF from the last applied sequence and deduplicates delivery', async () => {
  const first = example.events.slice(0, 3);
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(streamResponse([...first, first[2]].map(frame).join('')))
    .mockResolvedValueOnce(streamResponse(example.events.slice(3).map(frame).join('')));
  vi.stubGlobal('fetch', fetcher);
  const log = new EventLog(example.view.run.run_id),
    callbacks = options();
  await followEvents(log, callbacks);
  expect(fetcher.mock.calls[1][0]).toContain('after_seq=3');
  expect(fetcher.mock.calls[1][1].headers).toEqual({ Accept: 'text/event-stream' });
  expect(log.cursor).toBe(example.events.length);
  expect(callbacks.onUpdate).toHaveBeenCalledTimes(example.events.length);
});

it('backfills a gap without skipping the missing fact', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      streamResponse([example.events[0], example.events[2]].map(frame).join('')),
    )
    .mockResolvedValueOnce(streamResponse(example.events.slice(1).map(frame).join('')));
  vi.stubGlobal('fetch', fetcher);
  const log = new EventLog(example.view.run.run_id);
  await followEvents(log, options());
  expect(fetcher.mock.calls[1][0]).toContain('after_seq=1');
  expect(log.view).toEqual(example.view);
});

it('stops on a persistent gap without presenting a completed history', async () => {
  const text = [example.events[0], example.events[2]].map(frame).join('');
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => Promise.resolve(streamResponse(text))),
  );
  const log = new EventLog(example.view.run.run_id);
  await expect(followEvents(log, options())).rejects.toThrow('event_gap');
  expect(log.cursor).toBe(1);
});

it('rejects a mismatched SSE identity before applying it', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(streamResponse(frame(example.events[0]).replace(':1\n', ':2\n'))),
  );
  const log = new EventLog(example.view.run.run_id);
  await expect(followEvents(log, options())).rejects.toThrow('event_frame_invalid');
  expect(log.cursor).toBe(0);
});

it('aborts a subscription during reconnect without issuing cancellation or more reads', async () => {
  const controller = new AbortController();
  const fetcher = vi.fn().mockResolvedValue(streamResponse(frame(example.events[0])));
  vi.stubGlobal('fetch', fetcher);
  await followEvents(new EventLog(example.view.run.run_id), {
    signal: controller.signal,
    onUpdate() {},
    onConnection(state) {
      if (state === 'reconnecting') controller.abort();
    },
  }).catch((error) => {
    expect(controller.signal.aborted).toBe(true);
    expect(error.name).toBe('AbortError');
  });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
