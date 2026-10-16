import { Database, Radio, RefreshCw, TriangleAlert } from 'lucide-react';
import type { Connection } from './event-stream';

export default function RecordConnection({
  connection,
  error,
  count,
  head,
  retry,
}: {
  connection: Connection;
  error: Error | null;
  count: number;
  head: number;
  retry: () => void;
}) {
  const caughtUp = count >= head;
  if (error || connection === 'unavailable')
    return (
      <div className="record-connection connection-warning" role="status">
        <TriangleAlert size={14} />
        <span>
          {error ? '事件记录未能完整核对，保留当前快照。' : '此记录没有可订阅的完整事件。'}{' '}
          历史播放暂不可用。
        </span>
        <button className="text-button" onClick={retry}>
          重新补读
        </button>
      </div>
    );
  const label =
    connection === 'reconnecting'
      ? '连接中断，正在从已应用序号补读'
      : !caughtUp
        ? `正在补读历史事件 ${count} / ${head}`
        : connection === 'complete'
          ? '事件已核对 · 运行已结束'
          : '正在跟随已保存的运行进度';
  return (
    <div className="record-connection" role="status">
      {connection === 'reconnecting' ? (
        <RefreshCw size={14} />
      ) : connection === 'complete' ? (
        <Database size={14} />
      ) : (
        <Radio size={14} />
      )}
      <span>{label}</span>
      <code>#{count}</code>
    </div>
  );
}
