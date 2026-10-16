import { expect, it } from 'vitest';
import { executionGraph } from './execution-graph';
import { parseProtocol } from './protocol';
import fixture from './test/fixtures/retried-run.json';

it('keeps each call separate and derives only parent and retry relationships', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  const graph = executionGraph(view, view.spans[2].span_id);
  expect(graph.nodes).toHaveLength(4);
  expect(new Set(graph.nodes.map((node) => node.id)).size).toBe(4);
  expect(graph.edges.filter((edge) => edge.id.startsWith('parent:'))).toHaveLength(3);
  const retry = graph.edges.find((edge) => edge.id.startsWith('retry:'))!;
  expect([retry.source, retry.target]).toEqual([view.spans[1].span_id, view.spans[2].span_id]);
  expect(
    graph.nodes.every(
      (node) => Number.isFinite(node.position.x) && Number.isFinite(node.position.y),
    ),
  ).toBe(true);
  expect(graph.nodes.find((node) => node.selected)?.id).toBe(view.spans[2].span_id);
});

it('does not draw future template calls or infer edges merely from list order', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  view.spans = view.spans.slice(0, 2).map((span) => ({ ...span, parent_span_id: null }));
  expect(executionGraph(view, null).edges).toHaveLength(0);
  view.spans = [];
  expect(executionGraph(view, null)).toEqual({ nodes: [], edges: [] });
});

it('shows an inherited reference without fabricating a new executed span', () => {
  const view = parseProtocol('run_view', structuredClone(fixture));
  view.run.inherited_span_ids = ['span_prefix'];
  view.spans = [{ ...view.spans[0], parent_span_id: 'span_prefix' }];
  const graph = executionGraph(view, null);
  const reference = graph.nodes.find((node) => node.id === 'span_prefix')!;
  expect(reference.data).toMatchObject({ span: null, inherited: true, reference: 'span_prefix' });
  expect(view.spans).toHaveLength(1);
  expect(graph.edges[0].source).toBe('span_prefix');
});
