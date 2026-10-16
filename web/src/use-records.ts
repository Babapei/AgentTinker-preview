import { useEffect, useState } from 'react';
import { getRun, getRuns } from './api';
import equal from 'fast-deep-equal';
import { EventIntegrityError, EventLog } from './event-log';
import { followEvents, type Connection } from './event-stream';
import type { Run, RunPage, RunView, RuntimeEvent } from './protocol';

export function useHistory(revision: number) {
  const [page, setPage] = useState({ revision, offset: 0 });
  const offset = page.revision === revision ? page.offset : 0;
  const [state, setState] = useState<{
    runs: Run[];
    total: number | null;
    next: number | null;
    loading: boolean;
    error: Error | null;
  }>({ runs: [], total: null, next: null, loading: true, error: null });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    getRuns(offset, controller.signal)
      .then((page: RunPage) => {
        if (!active) return;
        setState((previous) => ({
          runs: Array.from(
            new Map(
              [...(offset === 0 ? [] : previous.runs), ...page.items].map((run) => [
                run.run_id,
                run,
              ]),
            ).values(),
          ).sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()),
          total: page.total,
          next: page.next_offset,
          loading: false,
          error: null,
        }));
      })
      .catch((error: Error) => {
        if (active) setState((previous) => ({ ...previous, loading: false, error }));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [offset, revision]);

  return {
    ...state,
    loadMore: () => state.next !== null && setPage({ revision, offset: state.next }),
  };
}

export function useRun(runId: string | null, revision: number) {
  const [state, setState] = useState<{
    id: string | null;
    view: RunView | null;
    loading: boolean;
    error: Error | null;
    streamError: Error | null;
    connection: Connection;
    events: readonly RuntimeEvent[];
  }>({
    id: null,
    view: null,
    loading: false,
    error: null,
    streamError: null,
    connection: 'connecting',
    events: [],
  });

  useEffect(() => {
    if (runId === null) return;
    const controller = new AbortController();
    let active = true;
    setState((previous) => ({
      id: runId,
      view: previous.id === runId ? previous.view : null,
      loading: true,
      error: null,
      streamError: null,
      connection: 'connecting',
      events: [],
    }));
    getRun(runId, controller.signal)
      .then(async (snapshot) => {
        if (!active) return;
        setState((previous) => ({ ...previous, view: snapshot, loading: false }));
        if (!snapshot.run.capabilities.record_playback) {
          setState((previous) => ({ ...previous, connection: 'unavailable' }));
          return;
        }
        const log = new EventLog(runId);
        try {
          await followEvents(log, {
            signal: controller.signal,
            onConnection(connection) {
              if (active) setState((previous) => ({ ...previous, connection }));
            },
            onUpdate() {
              if (!active) return;
              if (log.cursor === snapshot.last_seq && !equal(log.view, snapshot)) {
                throw new EventIntegrityError('event_snapshot_mismatch');
              }
              // Capture this validated prefix before React runs the updater later.
              const view = log.cursor >= snapshot.last_seq ? log.view : snapshot;
              const events = log.events;
              setState((previous) => ({
                ...previous,
                view,
                events,
              }));
            },
          });
        } catch (error) {
          if (active)
            setState((previous) => ({
              ...previous,
              streamError: error as Error,
              connection: 'unavailable',
            }));
        }
      })
      .catch((error: Error) => {
        if (active)
          setState((previous) => ({ ...previous, id: runId, view: null, loading: false, error }));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [runId, revision]);

  return state.id === runId
    ? state
    : {
        view: null,
        loading: runId !== null,
        error: null,
        streamError: null,
        connection: 'connecting' as Connection,
        events: [],
      };
}
