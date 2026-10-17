import { useEffect, useRef, useState, type FormEvent } from 'react';
import { importPackage } from './api';
import { actionError, forgetIntent, pendingIntent, rememberIntent } from './mutations';

const maxBytes = 8 * 1024 * 1024;

export default function PackageImport({
  close,
  imported,
}: {
  close: () => void;
  imported: (runId: string) => void;
}) {
  const [file, setFile] = useState<{
    name: string;
    bytes: Uint8Array<ArrayBuffer>;
    sha: string;
  } | null>(null);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending] = useState(() => {
    try {
      return pendingIntent('import') !== null;
    } catch {
      return false;
    }
  });
  const active = useRef(true),
    sending = useRef(false),
    revision = useRef(0);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      revision.current++;
    };
  }, []);

  async function select(selected: File | undefined) {
    const ticket = ++revision.current;
    setFile(null);
    setError(null);
    if (!selected) return;
    setReading(true);
    try {
      if (selected.size > maxBytes) throw new Error('package_too_large');
      const bytes = new Uint8Array(await selected.arrayBuffer());
      const hash = await crypto.subtle.digest('SHA-256', bytes);
      const sha = Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('');
      if (active.current && ticket === revision.current)
        setFile({ name: selected.name, bytes, sha });
    } catch (reason) {
      if (active.current && ticket === revision.current) setError(actionError(reason));
    } finally {
      if (active.current && ticket === revision.current) setReading(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      // Remember only a byte digest; the file itself is never stored in sessionStorage.
      const intent = rememberIntent('import', { sha256: file.sha });
      const result = await importPackage(file.bytes, intent.key);
      forgetIntent(intent.key);
      if (active.current) imported(result.root_run_id);
    } catch (reason) {
      if (active.current) setError(actionError(reason));
    } finally {
      sending.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section className="experiment-panel package-panel" aria-label="导入实验包">
      <div className="panel-heading">
        <h2>导入实验包</h2>
        <button className="text-button" onClick={close} disabled={busy}>
          关闭导入
        </button>
      </div>
      <p>
        选择 AgentTinker JSON 包（最多 8
        MiB）。导入后可检查记录；完整事件可回放，不会调用模型或恢复执行。
      </p>
      {pending && (
        <p className="notice">
          有未确认的导入。请重新选择同一文件后显式重试；相同文件沿用原请求标识。
        </p>
      )}
      <form onSubmit={submit}>
        <fieldset disabled={busy || reading}>
          <label className="form-field">
            JSON 实验包文件
            <input
              type="file"
              accept=".json,application/json"
              onChange={(event) => void select(event.target.files?.[0])}
            />
          </label>
        </fieldset>
        {file && (
          <p className="form-note">
            已选择：{file.name} · {file.bytes.byteLength.toLocaleString('zh-CN')} 字节
          </p>
        )}
        {error && (
          <p className="action-error" role="alert">
            {error}
          </p>
        )}
        <button className="button primary-button" type="submit" disabled={!file || busy || reading}>
          {busy ? '正在导入…' : reading ? '正在读取文件…' : '导入并打开记录'}
        </button>
      </form>
    </section>
  );
}
