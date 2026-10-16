import { describe, expect, it } from 'vitest';
import { parseProtocol } from './protocol';
import fixture from './test/fixtures/retried-run.json';

describe('Python response contracts in the browser', () => {
  it('accepts a native retry record without filling unknown observations', () => {
    const data = structuredClone(fixture);
    const view = parseProtocol('run_view', data);
    expect(view.run.mode).toBe('synthetic');
    expect(view.spans).toHaveLength(4);
    expect(view.spans[0].usage.total_tokens).toBeNull();
    expect(view.spans[0].cost.amount).toBeNull();
    expect(data).toEqual(fixture);
  });

  it.each(['version', 'missing', 'negative_usage', 'numeric_cost'])(
    'rejects incompatible or incomplete wire observations: %s',
    (kind) => {
      const data: Record<string, unknown> = structuredClone(fixture);
      if (kind === 'version') data.schema_version = '999';
      if (kind === 'missing') delete data.spans;
      if (kind === 'negative_usage') {
        const spans = data.spans as { usage: { total_tokens: number | null } }[];
        spans[0].usage.total_tokens = -1;
      }
      if (kind === 'numeric_cost') {
        const spans = data.spans as { cost: { amount: number | null } }[];
        spans[0].cost.amount = 0;
      }
      expect(() => parseProtocol('run_view', data)).toThrow('protocol_invalid');
    },
  );

  it('accepts decimal cost strings with their source intact', () => {
    const data = structuredClone(fixture);
    Object.assign(data.spans[0].cost, {
      kind: 'estimate',
      amount: '0.000004224',
      currency: 'USD',
      price_version: 'offline-price-fixture',
    });
    const view = parseProtocol('run_view', data);
    expect(view.spans[0].cost.amount).toBe('0.000004224');
    expect(view.spans[0].cost.price_version).toBe('offline-price-fixture');
  });
});
