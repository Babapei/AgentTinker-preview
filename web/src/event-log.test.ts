import { beforeAll, expect, it } from 'vitest';
import { EventLog, projectEvents } from './event-log';
import { eventFixtures } from './test/event-fixtures';

let examples: ReturnType<typeof eventFixtures>;
beforeAll(() => {
  examples = eventFixtures();
});

it.each([
  'failed',
  'retried',
  'cancelled',
  'forked',
  'document',
  'document_forked',
  'imported',
] as const)('matches every Python projection prefix for a native %s run', (name) => {
  const { events, prefixes, view } = examples[name];
  const log = new EventLog(view.run.run_id);
  for (const [index, event] of events.entries()) {
    expect(log.append(event)).toBe(true);
    expect(log.view).toEqual(prefixes[index]);
  }
  expect(log.view).toEqual(view);
  expect(projectEvents([])).toBeNull();
});

it('deduplicates only identical facts and does not mutate old prefixes', () => {
  const { events, view } = examples.retried;
  const log = new EventLog(view.run.run_id);
  log.append(events[0]);
  const original = structuredClone(log.view);
  expect(log.append(structuredClone(events[0]))).toBe(false);
  expect(log.cursor).toBe(1);
  for (const event of events.slice(1)) log.append(event);
  expect(original).toEqual(examples.retried.prefixes[0]);
  const changed = { ...events[0], received_at: '2040-01-01T00:00:00Z' };
  expect(() => log.append(changed)).toThrow('event_identity_conflict');
  expect(log.view).toEqual(view);
});

it('rejects sequence gaps, foreign identity and changed history without advancing', () => {
  const { events, view } = examples.retried;
  const log = new EventLog(view.run.run_id);
  log.append(events[0]);
  expect(() => log.append(events[2])).toThrow('event_gap');
  expect(() => log.append({ ...events[1], run_id: 'run_foreign' })).toThrow('event_run_mismatch');
  expect(() => log.append({ ...events[0], event_id: 'evt_new' })).toThrow('event_order_conflict');
  expect(log.cursor).toBe(1);
  log.append(events[1]);
  expect(log.cursor).toBe(2);
});

it('rejects tool retries without their causal failure and scheduling facts', () => {
  const { events } = examples.retried;
  const mutated = events
    .filter((event) => event.type !== 'tool.retry_scheduled')
    .map((event, index) => ({ ...event, seq: index + 1 }));
  expect(() => projectEvents(mutated)).toThrow('event_history_invalid');
});

it('does not let a finish fact rewrite the original call input', () => {
  const events = structuredClone(examples.retried.events);
  const finish = events.find((event) => event.type === 'span.finished')!;
  if (finish.type === 'span.finished') finish.data.input = { changed: true };
  expect(() => projectEvents(events)).toThrow('event_history_invalid');
});

it('marks unfinished work interrupted without inventing result, end time or usage', () => {
  const events = structuredClone(examples.cancelled.events.slice(0, 3));
  const last = structuredClone(examples.cancelled.events.at(-1)!);
  if (last.type !== 'run.status_changed') throw new Error('fixture_status_required');
  Object.assign(last, { seq: 4 });
  Object.assign(last.data, { before: 'running', after: 'interrupted' });
  const view = projectEvents([...events, last])!;
  expect(view.run.status).toBe('interrupted');
  expect(view.spans[0]).toMatchObject({
    status: 'interrupted',
    ended_at: null,
    output: null,
    usage: { total_tokens: null },
  });
});

it.each(['2026-10-16T10:43:30.305887Z', '2026-10-16T18:43:30.305887+08:00'])(
  'retains sub-millisecond observations and timezone equivalence: %s',
  (received) => {
    const events = structuredClone(examples.retried.events.slice(0, 2));
    if (events[0].type !== 'run.created') throw new Error('creation_required');
    events[0].data.created_at = '2026-10-16T10:43:30.305125Z';
    events[0].data.updated_at = '2026-10-16T10:43:30.305125Z';
    events[0].received_at = '2026-10-16T10:43:30.305125Z';
    events[1].received_at = received;
    expect(projectEvents(events)?.run.updated_at).toBe(received);
  },
);
