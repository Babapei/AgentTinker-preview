import { useRef, useState } from 'react';
import { Square } from 'lucide-react';
import { cancelRun } from './api';
import { actionError } from './mutations';
import { terminal } from './event-log';
import type { RunView } from './protocol';
import Status from './Status';

export default function RunControl({ view, cancelled }: { view: RunView; cancelled: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const sending = useRef(false);
  if (terminal(view.run.status)) return null;
  const pending = view.run.status === 'cancel_requested' || acknowledged;
  async function cancel() {
    if (sending.current || pending) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      await cancelRun(view.run.run_id);
      setAcknowledged(true);
      cancelled();
    } catch (reason) {
      setError(actionError(reason));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="run-control" aria-label="实际运行控制">
      <div>
        <strong>实际任务</strong>
        <Status status={pending ? 'cancel_requested' : view.run.status} />
        <p>
          {pending
            ? '取消已请求，等待在途调用返回；收到的结果与用量会保留。'
            : '取消后不再启动后续调用；已发出的请求可能仍需等待返回。'}
        </p>
      </div>
      <button className="button" disabled={busy || pending} onClick={cancel}>
        <Square size={13} />
        {pending ? '等待取消完成' : busy ? '正在请求取消…' : '取消实际运行'}
      </button>
      {error && (
        <p className="action-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
