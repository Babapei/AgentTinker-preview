import { expect, it } from 'vitest';
import { duration, modelAnswer, summarize } from './observations';
import { parseProtocol } from './protocol';
import fixture from './test/fixtures/retried-run.json';

it('counts logical tool calls separately from attempts and inherited references', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  view.run.inherited_span_ids = ['inherited-model'];
  const metrics = summarize(view);
  expect(metrics.modelCalls).toBe(2);
  expect(metrics.toolCalls).toBe(1);
  expect(metrics.toolAttempts).toBe(2);
  expect(metrics.totalTokens).toBeNull();
  expect(metrics.cost).toBeNull();
});

it('keeps a partly observed token total unknown and preserves observed zero', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  view.spans[0].usage.total_tokens = 0;
  expect(summarize(view)).toMatchObject({ knownUsage: 1, totalTokens: null });
  view.spans[3].usage.total_tokens = 0;
  expect(summarize(view)).toMatchObject({ knownUsage: 2, totalTokens: 0 });
  expect(duration(0)).toBe('0.0 ms');
  expect(duration(null)).toBe('未知');
});

it('adds decimal estimates exactly, retaining their distinction from actual charges', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  for (const span of view.spans.filter((span) => span.kind === 'model')) {
    span.cost = {
      amount: '0.000004224',
      currency: 'USD',
      kind: 'estimate',
      price_version: 'offline-version',
      evidence_artifact_id: null,
    };
  }
  expect(summarize(view).cost).toEqual({
    amount: '0.000008448',
    currency: 'USD',
    kind: 'estimate',
  });
  view.spans[3].cost.currency = 'CNY';
  expect(summarize(view).cost).toBeNull();
});

it('does not present mixed estimates and actual charges as one bill', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  for (const span of view.spans.filter((span) => span.kind === 'model')) {
    Object.assign(span.cost, {
      amount: '1',
      currency: 'USD',
      kind: 'estimate',
      price_version: 'p',
    });
  }
  view.spans[3].cost.kind = 'actual';
  view.spans[3].cost.evidence_artifact_id = 'invoice-fixture';
  expect(summarize(view).cost).toBeNull();
});

it('does not round cost strings to the decimal library default precision', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  for (const span of view.spans.filter((span) => span.kind === 'model')) {
    Object.assign(span.cost, { currency: 'USD', kind: 'estimate', price_version: 'p' });
  }
  view.spans[0].cost.amount = '12345678901234567890.0000000001';
  view.spans[3].cost.amount = '0.0000000002';
  expect(summarize(view).cost?.amount).toBe('12345678901234567890.0000000003');
});

it('extracts only a recorded model message, without inventing an answer', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  expect(modelAnswer(view)).toContain('Synthetic answer');
  view.spans = view.spans.slice(0, 1);
  expect(modelAnswer(view)).toBeNull();
});
