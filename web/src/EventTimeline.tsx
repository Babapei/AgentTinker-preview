import { useState } from 'react';
import { Clock3, ListOrdered } from 'lucide-react';
import type { RuntimeEvent } from './protocol';
import { dateTime, statusLabels } from './observations';
import JsonBlock from './JsonBlock';

export function eventTitle(event: RuntimeEvent): string {
  switch (event.type) {
    case 'run.created':
      return '创建运行';
    case 'run.status_changed':
      return `${statusLabels[event.data.before]} → ${statusLabels[event.data.after]}`;
    case 'span.started':
      return `开始 ${event.data.logical_node_id} · ${event.data.kind === 'tool' ? `尝试 ${event.data.attempt}` : `调用 ${event.data.call_index}`}`;
    case 'span.finished':
      return `${event.data.logical_node_id} · ${statusLabels[event.data.status]}`;
    case 'tool.attempt_failed':
      return `${event.data.origin === 'injected' ? '注入故障' : '工具故障'} · ${event.data.error_code}`;
    case 'tool.retry_scheduled':
      return `执行器安排第 ${event.data.next_attempt} 次尝试`;
    case 'checkpoint.saved':
      return '保存工具前检查点引用';
  }
}

export default function EventTimeline({
  events,
  head,
  choose,
}: {
  events: readonly RuntimeEvent[];
  head: number;
  choose: (event: RuntimeEvent) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const current = events.find((event) => event.event_id === selected) ?? events.at(-1);
  const [filter, setFilter] = useState('all');
  const visible = events.filter((event) => filter === 'all' || event.type.startsWith(filter));
  return (
    <section className="timeline-panel" aria-label="事件时间线">
      <div className="panel-heading">
        <div>
          <Clock3 size={17} />
          <h2>事件时间线</h2>
          <span className="count-pill">
            {events.length} / {head}
          </span>
        </div>
        <select
          aria-label="筛选事件"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        >
          <option value="all">全部事件</option>
          <option value="run.">运行状态</option>
          <option value="span.">调用记录</option>
          <option value="tool.">故障与重试</option>
          <option value="checkpoint.">检查点引用</option>
        </select>
      </div>
      <p className="timeline-caption">按已应用序号排序 · 时间仅作展示 · 点击事件回到该记录位置</p>
      <div className="timeline-grid">
        <ol className="event-list">
          {visible.map((event) => (
            <li key={event.event_id}>
              <button
                aria-pressed={current?.event_id === event.event_id}
                onClick={() => {
                  setSelected(event.event_id);
                  choose(event);
                }}
              >
                <code>#{event.seq}</code>
                <span>
                  <strong>{eventTitle(event)}</strong>
                  <small>{event.type}</small>
                </span>
                <time dateTime={event.occurred_at}>{dateTime(event.occurred_at)}</time>
              </button>
            </li>
          ))}
          {visible.length === 0 && <li className="empty-inline">当前已应用事件中没有匹配记录。</li>}
        </ol>
        <div className="event-evidence" aria-label="事件原始记录">
          <h3>
            <ListOrdered size={14} />
            {current ? `已应用事件 #${current.seq}` : '尚无事件'}
          </h3>
          <JsonBlock value={current ?? null} empty="完整事件补读后可检查原始事实。" />
        </div>
      </div>
    </section>
  );
}
