import { useRef, useState } from 'react';
import { Download } from 'lucide-react';
import { exportPackage } from './api';
import { terminal } from './event-log';
import { actionError } from './mutations';
import type { RunView } from './protocol';

export default function PackageExport({ view }: { view: RunView }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false);
  async function download() {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      const blob = await exportPackage(view.run.run_id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `agenttinker-${view.run.run_id}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) {
      setError(actionError(reason));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="package-export" aria-label="实验包导出">
      <button
        className="button"
        disabled={busy || (view.run.mode !== 'imported' && !terminal(view.run.status))}
        onClick={() => void download()}
      >
        <Download size={14} />
        {busy ? '正在准备文件…' : '导出实验包'}
      </button>
      <p>导出完整记录及所需祖先，保留任务、消息与人工署名等内容；实际运行结束后可导出。</p>
      {error && (
        <p className="action-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
