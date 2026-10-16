import { useEffect, useState } from 'react';
import { getRun, getRuns } from './api';
import type { Run, RunPage, RunView } from './protocol';

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
  }>({ id: null, view: null, loading: false, error: null });

  useEffect(() => {
    if (runId === null) return;
    const controller = new AbortController();
    let active = true;
    setState((previous) => ({
      id: runId,
      view: previous.id === runId ? previous.view : null,
      loading: true,
      error: null,
    }));
    getRun(runId, controller.signal)
      .then((view) => {
        if (active) setState({ id: runId, view, loading: false, error: null });
      })
      .catch((error: Error) => {
        if (active) setState({ id: runId, view: null, loading: false, error });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [runId, revision]);

  return state.id === runId ? state : { view: null, loading: runId !== null, error: null };
}
