import { useEffect, useRef, useState, type FormEvent } from 'react';
import { createDocumentRun, getScenarios } from './api';
import { documentScenario } from './document-experiment';
import { actionError, forgetIntent, pendingIntent, rememberIntent } from './mutations';
import { parseProtocol, type DocumentRunRequest, type RunView, type Scenario } from './protocol';

function restored() {
  try {
    const pending = pendingIntent('create-document');
    return pending ? parseProtocol('document_run_request', pending.body) : null;
  } catch {
    return null;
  }
}

export default function DocumentComposer({
  created,
  close,
  busyChanged,
}: {
  created: (view: RunView) => void;
  close: () => void;
  busyChanged: (busy: boolean) => void;
}) {
  const [initial] = useState(restored);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [mode, setMode] = useState<DocumentRunRequest['mode'] | ''>(initial?.mode ?? '');
  const [provider, setProvider] = useState<'deepseek' | 'openai'>(initial?.provider ?? 'deepseek');
  const [model, setModel] = useState(initial?.model ?? '');
  const [variant, setVariant] = useState<DocumentRunRequest['variant']>(
    initial?.variant ?? 'baseline',
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const sending = useRef(false);
  useEffect(() => busyChanged(busy), [busy, busyChanged]);
  useEffect(() => {
    const controller = new AbortController();
    getScenarios(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) {
          setScenario(documentScenario(items));
          setError(null);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(actionError(reason));
      });
    return () => controller.abort();
  }, [revision]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (sending.current || !mode || !scenario) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    const body: DocumentRunRequest = {
      mode,
      variant,
      provider: mode === 'live' ? provider : null,
      model: mode === 'live' && model.trim() ? model.trim() : null,
    };
    try {
      const intent = rememberIntent('create-document', body);
      const view = await createDocumentRun(body, scenario, intent.key);
      forgetIntent(intent.key);
      created(view);
    } catch (reason) {
      setError(actionError(reason));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="experiment-panel" aria-label="新建文档实验配置">
      <div className="panel-heading">
        <h2>没有检索到，还是没有正确使用</h2>
        <button className="text-button" disabled={busy} onClick={close}>
          关闭实验配置
        </button>
      </div>
      {!scenario && !error && <p role="status">正在读取场景定义…</p>}
      {error && (
        <p className="action-error" role="alert">
          {error}
        </p>
      )}
      {!scenario && error && (
        <button className="button" onClick={() => setRevision((n) => n + 1)}>
          重新读取场景
        </button>
      )}
      {scenario && (
        <form onSubmit={submit}>
          <p>{scenario.definition.description}</p>
          <p className="scenario-task">任务：{scenario.case.task}</p>
          <ul>
            {scenario.definition.success_criteria.map((criterion) => (
              <li key={criterion}>{criterion}</li>
            ))}
          </ul>
          <fieldset disabled={busy}>
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
                实验变体
                <select
                  value={variant}
                  onChange={(e) => setVariant(e.target.value as typeof variant)}
                >
                  <option value="baseline">基线 · top_k=2</option>
                  <option value="candidate">候选 · top_k=3</option>
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
          </fieldset>
          <p className="form-note">
            检索只返回标题与
            ID，读取工具才返回正文；模型自主选择工具或回答。此处固定版本用例，无超时注入，重试上限为
            0。对照时应运行基线后，从首次检索前分支只改 top_k。
          </p>
          <p className="form-note">
            {mode === 'live'
              ? '真实请求可能产生提供商费用，凭据由服务端配置。'
              : '模拟行为与真实模型能力分开标记，未知用量和费用不补零。'}
          </p>
          {initial && (
            <p className="form-note">已恢复未确认的文档请求；相同配置重试使用同一请求标识。</p>
          )}
          <button className="button primary-button" disabled={busy || !mode} type="submit">
            {busy ? '正在提交…' : error ? '重试同一请求' : '开始运行实验'}
          </button>
        </form>
      )}
    </section>
  );
}
