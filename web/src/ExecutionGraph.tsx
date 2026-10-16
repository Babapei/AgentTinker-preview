import { useEffect, useMemo } from 'react';
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useNodesInitialized,
  useReactFlow,
  type NodeProps,
} from '@xyflow/react';
import { Cpu, Layers2, Wrench } from 'lucide-react';
import type { RunView } from './protocol';
import { executionGraph, type CallNode } from './execution-graph';
import Status from './Status';
import { shortId } from './observations';

type RenderNode = CallNode & { data: CallNode['data'] & { select: (id: string) => void } };

function Call({ data, selected }: NodeProps<RenderNode>) {
  const span = data.span;
  return (
    <div
      className={`call-node ${selected ? 'is-selected' : ''} ${span === null ? 'reference-node' : ''}`}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      {span === null ? (
        <div className="reference-content">
          <Layers2 size={16} />
          <strong>{data.inherited ? '继承步骤引用' : '缺失的父步骤引用'}</strong>
          <code>{shortId(data.reference!)}</code>
        </div>
      ) : (
        <button
          className="nodrag nopan graph-node-control"
          onClick={() => data.select(span.span_id)}
          aria-pressed={selected}
          aria-label={`检查步骤 ${span.logical_node_id} ${span.kind === 'tool' ? `尝试 ${span.attempt}` : `调用 ${span.call_index}`}`}
        >
          <span>
            {span.kind === 'model' ? <Cpu size={15} /> : <Wrench size={15} />}
            <strong>{span.logical_node_id}</strong>
          </span>
          <span>
            <small>
              {span.kind === 'tool' ? `尝试 ${span.attempt}` : `调用 ${span.call_index}`}
            </small>
            <Status status={span.status} />
          </span>
        </button>
      )}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}
const nodeTypes = { call: Call };

function FitEvidence({ count }: { count: number }) {
  const initialized = useNodesInitialized();
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (initialized) void fitView({ padding: 0.12, duration: 0 });
  }, [count, initialized, fitView]);
  return null;
}

export default function ExecutionGraph({
  view,
  selected,
  select,
}: {
  view: RunView;
  selected: string | null;
  select: (id: string) => void;
}) {
  const graph = useMemo(() => {
    const graph = executionGraph(view, selected);
    return {
      ...graph,
      nodes: graph.nodes.map((node) => ({ ...node, data: { ...node.data, select } })),
    };
  }, [view, selected, select]);
  if (view.spans.length === 0)
    return (
      <div className="empty-state compact">
        <Layers2 />
        <h3>当前事件位置尚无调用</h3>
        <p>没有根据模板预画未执行的步骤。</p>
      </div>
    );
  return (
    <div className="graph-container" role="region" aria-label="实际执行图">
      <ReactFlow
        nodes={graph.nodes}
        edges={graph.edges}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        minZoom={0.3}
        maxZoom={1.5}
        fitViewOptions={{ padding: 0.12 }}
        ariaLabelConfig={{
          'controls.zoomIn.ariaLabel': '放大执行图',
          'controls.zoomOut.ariaLabel': '缩小执行图',
          'controls.fitView.ariaLabel': '适应执行图',
        }}
      >
        <Background color="#dfe8e1" gap={20} />
        <FitEvidence count={graph.nodes.length} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <p className="graph-legend">实线：父步骤引用 · 虚线：执行器重试 · 每次调用独立成点</p>
    </div>
  );
}
