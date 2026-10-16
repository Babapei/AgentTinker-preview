import dagre from '@dagrejs/dagre';
import type { Edge, Node } from '@xyflow/react';
import type { RunView, Span } from './protocol';

export type CallNode = Node<
  { span: Span | null; reference: string | null; inherited: boolean },
  'call'
>;

/** Parent and retry edges are explicit evidence; y order never invents a dependency. */
export function executionGraph(
  view: RunView,
  selected: string | null,
): { nodes: CallNode[]; edges: Edge[] } {
  const nodes: CallNode[] = view.spans.map((span) => ({
    id: span.span_id,
    type: 'call',
    position: { x: 0, y: 0 },
    data: { span, reference: null, inherited: false },
    selected: span.span_id === selected,
  }));
  const edges: Edge[] = [];
  const ids = new Set(nodes.map((node) => node.id));
  const previous = new Map<string, Span>();
  for (const span of view.spans) {
    if (span.parent_span_id) {
      const parent = span.parent_span_id;
      if (!ids.has(parent)) {
        nodes.push({
          id: parent,
          type: 'call',
          position: { x: 0, y: 0 },
          data: {
            span: null,
            reference: parent,
            inherited: view.run.inherited_span_ids.includes(parent),
          },
        });
        ids.add(parent);
      }
      edges.push({
        id: `parent:${span.span_id}`,
        source: parent,
        target: span.span_id,
        type: 'smoothstep',
        label: '父引用',
        style: { stroke: '#91a797' },
        labelStyle: { fill: '#52685a', fontSize: 10 },
      });
    }
    if (span.kind === 'tool' && span.logical_call_id !== null) {
      const prior = previous.get(span.logical_call_id);
      if (prior && span.attempt === prior.attempt! + 1)
        edges.push({
          id: `retry:${span.span_id}`,
          source: prior.span_id,
          target: span.span_id,
          type: 'smoothstep',
          label: '执行器重试',
          style: { stroke: '#9a7938', strokeDasharray: '4 3' },
          labelStyle: { fill: '#7a5e23', fontSize: 10 },
        });
      previous.set(span.logical_call_id, span);
    }
  }
  const layout = new dagre.graphlib.Graph({ multigraph: true });
  layout.setGraph({ rankdir: 'TB', nodesep: 28, ranksep: 28, marginx: 14, marginy: 14 });
  layout.setDefaultEdgeLabel(() => ({}));
  for (const node of nodes) layout.setNode(node.id, { width: 220, height: 80 });
  for (const edge of edges) layout.setEdge(edge.source, edge.target, {}, edge.id);
  dagre.layout(layout);
  for (const node of nodes) {
    const point = layout.node(node.id);
    node.position = { x: point.x - 110, y: point.y - 40 };
  }
  return { nodes, edges };
}
