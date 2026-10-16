import { useEffect, useRef, useState } from 'react';
import { GitBranch, RefreshCw } from 'lucide-react';
import { forkRun, getCheckpointAvailability } from './api';
import { actionError, forgetIntent, pendingIntent, rememberIntent } from './mutations';
import {
  parseProtocol,
  type CheckpointAvailability,
  type ForkRequest,
  type RunView,
} from './protocol';
import { shortId } from './observations';

function restored(runId: string) {
  try {
    const pending = pendingIntent(`fork:${runId}`);
    return pending ? parseProtocol('fork_request', pending.body) : null;
  } catch {
    return null;
  }
}

export default function ForkPanel({
  view,
  created,
}: {
  view: RunView;
  created: (view: RunView) => void;
}) {
  const [initial] = useState(() => restored(view.run.run_id));
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [items, setItems] = useState<CheckpointAvailability[]>([]);
  const [loading, setLoading] = useState(false);
  const [point, setPoint] = useState(
    initial?.source_checkpoint_id ?? view.checkpoints[0]?.checkpoint_id ?? '',
  );
  const [field, setField] = useState<'tool_retry_limit' | 'top_k'>(
    initial?.patch.top_k !== undefined ? 'top_k' : 'tool_retry_limit',
  );
  const before = Number(view.run.config.tool_policy[field]);
  const [value, setValue] = useState(Number(initial?.patch[field] ?? (before === 0 ? 1 : 0)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getCheckpointAvailability(view.run.run_id, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setItems(result);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(actionError(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, revision, view.run.run_id]);
  if (!view.run.capabilities.fork_from_checkpoint || !view.run.capabilities.patch_tool_policy)
    return null;
  if (!view.checkpoints.length)
    return (
      <p className="capability-note">
        当前记录位置没有工具前检查点；请继续检查实际事件，不能从显示位置直接恢复。
      </p>
    );
  const visible = items.filter((item) =>
    view.checkpoints.some((cp) => cp.checkpoint_id === item.checkpoint.checkpoint_id),
  );
  const selected = visible.find((item) => item.checkpoint.checkpoint_id === point) ?? visible[0];
  async function submit() {
    if (sending.current || !selected?.available || value === before) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    const body: ForkRequest = {
      source_checkpoint_id: selected.checkpoint.checkpoint_id,
      patch: { [field]: value },
    };
    try {
      const intent = rememberIntent(`fork:${view.run.run_id}`, body);
      const branch = await forkRun(view.run.run_id, body, intent.key);
      forgetIntent(intent.key);
      if (active.current) created(branch);
    } catch (reason) {
      if (active.current) setError(actionError(reason));
    } finally {
      sending.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section className="experiment-panel fork-panel" aria-label="检查点分支">
      <div className="panel-heading">
        <div>
          <GitBranch size={16} />
          <h2>改变一个因素，创建分支</h2>
        </div>
        <button
          className="button"
          disabled={loading || busy}
          onClick={() => {
            setOpen(true);
            setRevision((n) => n + 1);
          }}
        >
          <RefreshCw size={13} />
          {loading ? '正在检查…' : open ? '重新检查分支可用性' : '检查分支可用性'}
        </button>
      </div>
      <p>
        从已保存的工具前状态开始新运行，原记录保留。复用的模型前缀不会重新调用；真实模式的后续调用可能产生费用。
      </p>
      {open && (
        <>
          {selected && !selected.available && (
            <p className="action-error" role="status">
              {actionError(new Error(selected.reason ?? 'unsupported_capability'))}
            </p>
          )}
          {selected && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <fieldset
                disabled={busy || loading || !selected.available}
                onChange={() => setError(null)}
              >
                <div className="form-grid">
                  <label className="form-field">
                    工具前检查点
                    <select
                      value={selected.checkpoint.checkpoint_id}
                      onChange={(e) => setPoint(e.target.value)}
                    >
                      {visible.map((item) => (
                        <option
                          key={item.checkpoint.checkpoint_id}
                          value={item.checkpoint.checkpoint_id}
                        >
                          {shortId(item.checkpoint.checkpoint_id)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="form-field">
                    只修改一个参数
                    <select
                      value={field}
                      onChange={(e) => {
                        const next = e.target.value as typeof field;
                        setField(next);
                        const old = Number(view.run.config.tool_policy[next]);
                        setValue(next === 'top_k' ? (old === 3 ? 2 : 3) : old === 0 ? 1 : 0);
                      }}
                    >
                      <option value="tool_retry_limit">工具重试上限</option>
                      <option value="top_k">检索文档数 top_k</option>
                    </select>
                  </label>
                  <label className="form-field">
                    修改后的值
                    <select value={value} onChange={(e) => setValue(Number(e.target.value))}>
                      {(field === 'top_k' ? [1, 2, 3] : [0, 1, 2, 3]).map((n) => (
                        <option key={n} value={n}>
                          {n}
                          {n === before ? ' · 原值' : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </fieldset>
              <p className="patch-summary">
                <code>{field}</code>：{before} → {value}；任务、模型查询与调用
                ID、数据及故障计划保持相同。
              </p>
              <p className="form-note">每个分支的首次尝试仍按原故障规则执行。重试由执行器负责。</p>
              <button
                className="button primary-button"
                type="submit"
                disabled={
                  busy ||
                  loading ||
                  !selected.available ||
                  !selected.allowed_patch_fields.includes(field) ||
                  before === value
                }
              >
                <GitBranch size={14} />
                {busy ? '正在创建分支…' : error ? '重试同一分支请求' : '创建分支并运行'}
              </button>
            </form>
          )}
          {error && (
            <p className="action-error" role="alert">
              {error} 相同补丁重试沿用原请求标识。
            </p>
          )}
        </>
      )}
    </section>
  );
}
