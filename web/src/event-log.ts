import equal from 'fast-deep-equal';
import { parseProtocol, type Run, type RuntimeEvent, type RunView, type Span } from './protocol';

export class EventIntegrityError extends Error {}

export const terminal = (status: Run['status']) =>
  ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(status);

const transitions: Record<Run['status'], Run['status'][]> = {
  queued: ['running', 'cancel_requested', 'failed', 'interrupted'],
  running: ['cancel_requested', 'succeeded', 'failed', 'interrupted'],
  cancel_requested: ['cancelled', 'failed', 'interrupted'],
  succeeded: [],
  failed: [],
  cancelled: [],
  interrupted: [],
};

function requireFact(condition: unknown, code = 'event_history_invalid'): asserts condition {
  if (!condition) throw new EventIntegrityError(code);
}

function immutableSpan(span: Span) {
  const { status, ended_at, duration_ms, output, model, usage, cost, ...identity } = span;
  void [status, ended_at, duration_ms, output, model, usage, cost];
  return identity;
}

/** A pure prefix projection. No SDK, HTTP, tool, or checkpoint execution. */
export function projectEvents(events: readonly RuntimeEvent[]): RunView | null {
  const state: { run: Run | null } = { run: null };
  const spans = new Map<string, Span>();
  const checkpoints = new Map<string, RunView['checkpoints'][number]>();
  const failures = new Map<string, Extract<RuntimeEvent, { type: 'tool.attempt_failed' }>>();
  const retries = new Set<string>();
  const ids = new Set<string>();
  for (const [index, original] of events.entries()) {
    let run = state.run;
    const event = structuredClone(parseProtocol('event', original));
    requireFact(event.seq === index + 1 && !ids.has(event.event_id), 'event_order_conflict');
    if (run === null) {
      requireFact(event.type === 'run.created' && event.data.status === 'queued');
      requireFact(event.data.run_id === event.run_id);
      run = event.data;
    } else {
      requireFact(event.run_id === run.run_id && !terminal(run.status));
      switch (event.type) {
        case 'run.created':
          throw new EventIntegrityError('run_already_created');
        case 'run.status_changed':
          requireFact(
            event.data.before === run.status && transitions[run.status].includes(event.data.after),
          );
          if (terminal(event.data.after) && event.data.after !== 'interrupted') {
            requireFact([...spans.values()].every((span) => span.status !== 'running'));
          }
          if (event.data.after === 'interrupted') {
            for (const [id, span] of spans) {
              if (span.status === 'running') spans.set(id, { ...span, status: 'interrupted' });
            }
          }
          run = { ...run, status: event.data.after };
          break;
        case 'span.started': {
          const span = event.data;
          requireFact(run.status === 'running' && span.status === 'running');
          requireFact(!spans.has(span.span_id) && !run.inherited_span_ids.includes(span.span_id));
          requireFact(
            span.parent_span_id === null ||
              spans.has(span.parent_span_id) ||
              run.inherited_span_ids.includes(span.parent_span_id),
          );
          if (span.kind === 'tool') {
            const previous = [...spans.values()]
              .filter(
                (prior) => prior.kind === 'tool' && prior.logical_call_id === span.logical_call_id,
              )
              .at(-1);
            if (previous === undefined) requireFact(span.attempt === 1);
            else
              requireFact(
                retries.has(previous.span_id) &&
                  span.attempt === previous.attempt! + 1 &&
                  span.logical_node_id === previous.logical_node_id &&
                  span.parent_span_id === previous.parent_span_id &&
                  span.call_index === previous.call_index &&
                  equal(span.input, previous.input),
              );
          }
          spans.set(span.span_id, span);
          break;
        }
        case 'span.finished': {
          const previous = spans.get(event.span_id);
          requireFact(previous?.status === 'running' && event.data.status !== 'running');
          requireFact(equal(immutableSpan(previous), immutableSpan(event.data)));
          spans.set(event.span_id, event.data);
          break;
        }
        case 'tool.attempt_failed':
        case 'tool.retry_scheduled': {
          const span = spans.get(event.span_id);
          requireFact(
            span?.kind === 'tool' &&
              span.status === 'failed' &&
              span.logical_call_id === event.logical_call_id &&
              span.attempt === event.attempt,
          );
          if (event.type === 'tool.attempt_failed') {
            requireFact(!failures.has(event.span_id));
            failures.set(event.span_id, event);
          } else {
            const failure = failures.get(event.span_id);
            requireFact(
              failure?.data.will_retry &&
                failure.data.retry_owner === 'executor' &&
                event.data.retry_owner === 'executor' &&
                event.data.next_attempt === event.attempt + 1 &&
                !retries.has(event.span_id) &&
                run.status === 'running',
            );
            retries.add(event.span_id);
          }
          break;
        }
        case 'checkpoint.saved':
          requireFact(
            event.data.run_id === run.run_id &&
              run.status === 'running' &&
              !checkpoints.has(event.data.checkpoint_id),
          );
          checkpoints.set(event.data.checkpoint_id, event.data);
      }
    }
    if (event.type === 'span.started' || event.type === 'span.finished') {
      requireFact(event.span_id === event.data.span_id && event.run_id === event.data.run_id);
      for (const key of [
        'parent_span_id',
        'logical_node_id',
        'logical_call_id',
        'attempt',
      ] as const) {
        requireFact(event[key] === null || event[key] === event.data[key]);
      }
    }
    if (new Date(event.received_at).getTime() > new Date(run.updated_at).getTime()) {
      run = { ...run, updated_at: event.received_at };
    }
    state.run = run;
    ids.add(event.event_id);
  }
  const run = state.run;
  return run === null
    ? null
    : {
        schema_version: '0.1',
        run,
        last_seq: events.length,
        spans: [...spans.values()],
        checkpoints: [...checkpoints.values()],
      };
}

export class EventLog {
  private facts: RuntimeEvent[] = [];
  private seen = new Map<string, RuntimeEvent>();
  view: RunView | null = null;

  constructor(readonly runId: string) {}

  get cursor() {
    return this.facts.length;
  }
  get events(): readonly RuntimeEvent[] {
    return this.facts.slice();
  }

  append(value: unknown): boolean {
    const event = structuredClone(parseProtocol('event', value));
    requireFact(event.run_id === this.runId, 'event_run_mismatch');
    const previous = this.seen.get(event.event_id);
    if (previous !== undefined) {
      requireFact(equal(previous, event), 'event_identity_conflict');
      return false;
    }
    requireFact(
      event.seq === this.cursor + 1,
      event.seq > this.cursor + 1 ? 'event_gap' : 'event_order_conflict',
    );
    const next = [...this.facts, event];
    const view = projectEvents(next);
    this.facts = next;
    this.seen.set(event.event_id, event);
    this.view = view;
    return true;
  }
}
