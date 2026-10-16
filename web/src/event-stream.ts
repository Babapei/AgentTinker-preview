import { createParser } from 'eventsource-parser';
import { ApiError } from './api';
import { EventIntegrityError, EventLog, terminal } from './event-log';
import { parseProtocol } from './protocol';

export type Connection = 'connecting' | 'following' | 'reconnecting' | 'complete' | 'unavailable';

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, ms);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
}

/** Reconnect from the last applied fact. Never use a stale query plus Last-Event-ID. */
export async function followEvents(
  log: EventLog,
  options: {
    signal: AbortSignal;
    onUpdate: () => void;
    onConnection: (state: Connection) => void;
    retryDelay?: number;
  },
): Promise<void> {
  const { signal, onUpdate, onConnection, retryDelay = 500 } = options;
  let retries = 0,
    gaps = 0;
  while (!signal.aborted) {
    let reader: ReadableStreamDefaultReader<string> | undefined;
    const startingCursor = log.cursor;
    try {
      onConnection(retries === 0 ? 'connecting' : 'reconnecting');
      const response = await fetch(
        `/api/v1/runs/${encodeURIComponent(log.runId)}/events?after_seq=${log.cursor}`,
        {
          signal,
          headers: { Accept: 'text/event-stream' },
        },
      );
      if (!response.ok) {
        await response.body?.cancel();
        throw new ApiError(response.status);
      }
      if (
        !response.body ||
        !response.headers.get('content-type')?.startsWith('text/event-stream')
      ) {
        await response.body?.cancel();
        throw new EventIntegrityError('event_frame_invalid');
      }
      onConnection('following');
      reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      const parser = createParser({
        onEvent(frame) {
          let value: unknown;
          try {
            value = JSON.parse(frame.data);
          } catch {
            throw new EventIntegrityError('event_frame_invalid');
          }
          const event = parseProtocol('event', value);
          if (frame.id !== `${log.runId}:${event.seq}` || frame.event !== event.type) {
            throw new EventIntegrityError('event_frame_invalid');
          }
          if (log.append(event)) onUpdate();
        },
        onError(error) {
          if (error.type !== 'unknown-field') throw new EventIntegrityError('event_frame_invalid');
        },
      });
      while (!signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        parser.feed(value);
        if (log.view && terminal(log.view.run.status)) {
          onConnection('complete');
          return;
        }
      }
      if (signal.aborted) return;
      throw new Error('event_stream_ended');
    } catch (error) {
      if (signal.aborted) return;
      const gap = error instanceof EventIntegrityError && error.message === 'event_gap';
      if (gap && gaps++ === 0) {
        /* One fresh backfill can repair a transport gap. */
      } else if (
        error instanceof EventIntegrityError ||
        (error instanceof Error && error.message === 'protocol_invalid') ||
        (error instanceof ApiError &&
          error.status >= 400 &&
          error.status < 500 &&
          ![408, 429].includes(error.status))
      ) {
        throw error;
      }
      retries = log.cursor > startingCursor ? 1 : retries + 1;
      onConnection('reconnecting');
    } finally {
      await reader?.cancel().catch(() => undefined);
      reader?.releaseLock();
    }
    await delay(Math.min(5000, retryDelay * 2 ** Math.min(retries - 1, 4)), signal);
  }
}
