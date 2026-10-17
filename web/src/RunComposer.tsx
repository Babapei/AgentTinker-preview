import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Play, X } from 'lucide-react';
import { createRun } from './api';
import { actionError, forgetIntent, pendingIntent, rememberIntent } from './mutations';
import { parseProtocol, type RunRequest, type RunView } from './protocol';
import DocumentComposer from './DocumentComposer';

const task = '比较虚构发布说明中的版本差异，检索 release，并在回答中标注返回的文档 ID。';

function restored(): RunRequest | null {
  try {
    const pending = pendingIntent('create');
    return pending ? parseProtocol('run_request', pending.body) : null;
  } catch {
    return null;
  }
}

function TimeoutComposer({
  created,
  close,
  busyChanged,
}: {
  created: (view: RunView) => void;
  close: () => void;
  busyChanged: (busy: boolean) => void;
}) {
  const [initial] = useState(restored);
  const [mode, setMode] = useState<RunRequest['mode'] | ''>(initial?.mode ?? '');
  const [text, setText] = useState(initial?.task ?? task);
  const [provider, setProvider] = useState<'deepseek' | 'openai'>(initial?.provider ?? 'deepseek');
  const [model, setModel] = useState(initial?.model ?? '');
  const [retry, setRetry] = useState(initial?.policy.tool_retry_limit ?? 0);
  const [topK, setTopK] = useState(initial?.policy.top_k ?? 2);
  const [fault, setFault] = useState(initial?.inject_timeout ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitting = useRef(false);
  useEffect(() => busyChanged(busy), [busy, busyChanged]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || !mode || !text.trim()) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    const body: RunRequest = {
      mode,
      task: text.trim(),
      policy: { tool_retry_limit: retry, top_k: topK },
      inject_timeout: fault,
      provider: mode === 'live' ? provider : null,
      model: mode === 'live' && model.trim() ? model.trim() : null,
    };
    try {
      const intent = rememberIntent('create', body);
      const view = await createRun(body, intent.key);
      forgetIntent(intent.key);
      created(view);
    } catch (reason) {
      setError(actionError(reason));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <section className="experiment-panel" aria-label="新建实验配置">
      <div className="panel-heading">
        <div>
          <Play size={16} />
          <h2>工具超时以后发生了什么</h2>
        </div>
        <button className="icon-button" aria-label="关闭实验配置" disabled={busy} onClick={close}>
          <X size={17} />
        </button>
      </div>
      <p>
        使用固定的虚构发布说明与本地只读检索。先以不重试的策略观察首次超时，再修改一个因素验证判断。
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy} onChange={() => setError(null)}>
          <label className="form-field">
            任务
            <textarea
              required
              maxLength={8000}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <div className="form-grid">
            <label className="form-field">
              运行模式
              <select
                required
                value={mode}
                onChange={(e) => setMode(e.target.value as typeof mode)}
              >
                <option value="">请选择运行模式</option>
                <option value="synthetic">模拟运行 · 不调用提供商</option>
                <option value="live">真实调用 · 使用服务端模型</option>
              </select>
            </label>
            <label className="form-field">
              工具重试上限
              <select value={retry} onChange={(e) => setRetry(Number(e.target.value))}>
                {[0, 1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n} 次重试{n === 0 ? ' · 基线' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field">
              检索文档数 top_k
              <select value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
                {[1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n} 份文档
                  </option>
                ))}
              </select>
            </label>
            {mode === 'live' && (
              <>
                <label className="form-field">
                  提供商
                  <select
                    value={provider}
                    onChange={(e) => setProvider(e.target.value as typeof provider)}
                  >
                    <option value="deepseek">DeepSeek</option>
                    <option value="openai">OpenAI</option>
                  </select>
                </label>
                <label className="form-field">
                  模型名称（可选）
                  <input
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="留空使用服务端默认模型"
                  />
                </label>
              </>
            )}
          </div>
          <label className="check-field">
            <input type="checkbox" checked={fault} onChange={(e) => setFault(e.target.checked)} />
            每次运行的首次工具尝试注入超时
          </label>
        </fieldset>
        <p className="form-note">
          {mode === 'live'
            ? '真实请求可能产生提供商费用；密钥由服务端配置，未知用量或费用仍显示未知。'
            : mode === 'synthetic'
              ? '模拟模型按固定规则返回，不产生真实模型用量或账单。'
              : '请先明确选择模拟或真实调用。'}
        </p>
        {initial && (
          <p className="form-note">已恢复上次未确认的请求；相同配置重试会使用同一请求标识。</p>
        )}
        {error && (
          <p className="action-error" role="alert">
            {error} 相同配置重试不会重复创建运行。
          </p>
        )}
        <button
          className="button primary-button"
          type="submit"
          disabled={busy || !mode || !text.trim()}
        >
          <Play size={14} />
          {busy ? '正在提交…' : error ? '重试同一请求' : '开始运行实验'}
        </button>
      </form>
    </section>
  );
}

export default function RunComposer(props: {
  created: (view: RunView) => void;
  close: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [scenario, setScenario] = useState(() => {
    try {
      return pendingIntent('create-document') ? 'document' : 'timeout';
    } catch {
      return 'timeout';
    }
  });
  return (
    <>
      <div className="experiment-panel scenario-picker">
        <label className="form-field">
          实验场景
          <select disabled={busy} value={scenario} onChange={(e) => setScenario(e.target.value)}>
            <option value="timeout">工具超时以后发生了什么</option>
            <option value="document">没有检索到，还是没有正确使用</option>
          </select>
        </label>
      </div>
      {scenario === 'document' ? (
        <DocumentComposer {...props} busyChanged={setBusy} />
      ) : (
        <TimeoutComposer {...props} busyChanged={setBusy} />
      )}
    </>
  );
}
