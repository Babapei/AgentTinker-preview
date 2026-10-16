import { useCallback, useEffect, useState } from 'react';
import {
  ArrowDownLeft,
  ArrowUpRight,
  Braces,
  Check,
  ChevronRight,
  Circle,
  Clock3,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  Layers2,
  ListOrdered,
  LockKeyhole,
  RefreshCw,
  Search,
  Terminal,
  Workflow,
  Wrench,
  X,
} from 'lucide-react';
import { ApiError } from './api';
import type { Run, RunView, Span } from './protocol';
import { useHistory, useRun } from './use-records';
import RecordConnection from './RecordConnection';
import {
  dateTime,
  duration,
  modeLabels,
  modelAnswer,
  shortId,
  spanSummary,
  statusLabels,
  summarize,
  textField,
} from './observations';

function readSelection() {
  const query = new URLSearchParams(window.location.search);
  return { run: query.get('run'), span: query.get('span') };
}

function Status({ status }: { status: Run['status'] | Span['status'] }) {
  return (
    <span className={`status status-${status}`}>
      {status === 'succeeded' ? (
        <Check size={12} />
      ) : status === 'failed' ? (
        <X size={12} />
      ) : (
        <Circle size={9} />
      )}
      {statusLabels[status]}
    </span>
  );
}

function ErrorNotice({ error, retry }: { error: Error; retry: () => void }) {
  const missing = error instanceof ApiError && error.status === 404;
  const invalid = error.message === 'protocol_invalid';
  return (
    <div className="notice error-notice" role="alert">
      <p>
        {missing ? '找不到这条运行记录' : invalid ? '运行记录的协议不兼容' : '暂时无法读取运行记录'}
      </p>
      <span>
        {missing
          ? '检查运行 ID，或从左侧选择已有记录。'
          : invalid
            ? '请核对前后端版本后重试。'
            : '请确认本地服务已启动，稍后重新读取。'}
      </span>
      <button className="text-button" onClick={retry}>
        重新读取 <RefreshCw size={13} />
      </button>
    </div>
  );
}

function JsonBlock({ value, empty }: { value: unknown; empty: string }) {
  return value === null || value === undefined ? (
    <p className="empty-inline">{empty}</p>
  ) : (
    <pre className="json-block" tabIndex={0}>
      <code>{JSON.stringify(value, null, 2)}</code>
    </pre>
  );
}

function Metrics({ view }: { view: RunView }) {
  const metrics = summarize(view);
  return (
    <div className="metrics" aria-label="本次运行新增调用指标">
      <div>
        <span>模型调用</span>
        <strong>
          {metrics.modelCalls}
          <small> 次</small>
        </strong>
        <p>仅本次新增调用</p>
      </div>
      <div>
        <span>工具调用 / 尝试</span>
        <strong>
          {metrics.toolCalls}
          <small> / </small>
          {metrics.toolAttempts}
        </strong>
        <p>重试单独记录尝试</p>
      </div>
      <div>
        <span>Token 用量</span>
        <strong>
          {metrics.totalTokens === null ? '未知' : metrics.totalTokens.toLocaleString('zh-CN')}
        </strong>
        <p>
          {metrics.knownUsage} / {metrics.modelCalls} 次调用有用量
        </p>
      </div>
      <div>
        <span>{metrics.cost?.kind === 'actual' ? '有凭证费用' : '估算费用'}</span>
        <strong className="cost-value">
          {metrics.cost ? `${metrics.cost.amount} ${metrics.cost.currency}` : '未知'}
        </strong>
        <p>{metrics.cost?.kind === 'estimate' ? '按记录价格版本估算' : '实际扣费需独立凭证'}</p>
      </div>
    </div>
  );
}

function StepDetails({ span, view }: { span: Span | null; view: RunView }) {
  const [tab, setTab] = useState<'overview' | 'input' | 'output' | 'metadata'>('overview');
  if (span === null)
    return (
      <aside className="detail-panel">
        <div className="empty-state">
          <Braces />
          <h3>选择一个步骤</h3>
          <p>查看它的输入、输出和执行证据。</p>
        </div>
      </aside>
    );
  const error = textField(span.output, 'error_code');
  const origin = textField(span.output, 'origin');
  return (
    <aside className="detail-panel" aria-label="步骤详情">
      <div className="detail-heading">
        <span className="eyebrow">STEP INSPECTOR</span>
        <h2>步骤详情</h2>
        <div className="detail-step-name">
          {span.kind === 'model' ? <Cpu size={17} /> : <Wrench size={17} />}
          <strong>{span.logical_node_id}</strong>
          <Status status={span.status} />
        </div>
        <p className="mono muted">{shortId(span.span_id)}</p>
      </div>
      <div className="detail-tabs" aria-label="详情视图">
        {(['overview', 'input', 'output', 'metadata'] as const).map((key) => (
          <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>
            {{ overview: '概览', input: '输入', output: '输出', metadata: '元数据' }[key]}
          </button>
        ))}
      </div>
      <div className="detail-content">
        {tab === 'input' && (
          <>
            <h3>
              <ArrowDownLeft size={15} /> 原始输入
            </h3>
            <JsonBlock value={span.input} empty="输入尚未记录" />
          </>
        )}
        {tab === 'output' && (
          <>
            <h3>
              <ArrowUpRight size={15} /> 原始输出
            </h3>
            <JsonBlock value={span.output} empty="未取得输出，不推断调用结果" />
          </>
        )}
        {tab === 'metadata' && (
          <>
            <h3>原始步骤记录</h3>
            <JsonBlock value={span} empty="未记录元数据" />
          </>
        )}
        {tab === 'overview' && (
          <>
            {error && (
              <div className="failure-evidence">
                <span>已记录错误</span>
                <strong className="mono">{error}</strong>
                <p>
                  来源：
                  {origin === 'injected'
                    ? '实验故障注入'
                    : origin === 'tool'
                      ? '工具执行'
                      : '以原始返回记录为准'}
                </p>
              </div>
            )}
            <dl className="facts">
              <div>
                <dt>类型</dt>
                <dd>
                  {span.kind === 'model' ? '模型调用' : span.kind === 'tool' ? '工具尝试' : '评价'}
                </dd>
              </div>
              <div>
                <dt>调用编号</dt>
                <dd>
                  #{span.call_index}
                  {span.attempt !== null && ` · 第 ${span.attempt} 次尝试`}
                </dd>
              </div>
              <div>
                <dt>耗时</dt>
                <dd>{duration(span.duration_ms)}</dd>
              </div>
              {span.kind === 'model' && (
                <>
                  <div>
                    <dt>模型</dt>
                    <dd>{span.model ?? '未知'}</dd>
                  </div>
                  <div>
                    <dt>提供商</dt>
                    <dd>{span.provider ?? '未知'}</dd>
                  </div>
                </>
              )}
              {span.kind === 'tool' && (
                <div>
                  <dt>逻辑调用 ID</dt>
                  <dd className="mono">{span.logical_call_id ?? '未知'}</dd>
                </div>
              )}
            </dl>
            {span.kind === 'model' && (
              <>
                <h3>用量与费用</h3>
                <dl className="facts">
                  <div>
                    <dt>输入 / 输出 Token</dt>
                    <dd>
                      {span.usage.prompt_tokens ?? '未知'} /{' '}
                      {span.usage.completion_tokens ?? '未知'}
                    </dd>
                  </div>
                  <div>
                    <dt>总 Token</dt>
                    <dd>{span.usage.total_tokens ?? '未知'}</dd>
                  </div>
                  <div>
                    <dt>缓存命中 Token</dt>
                    <dd>{span.usage.cached_input_tokens ?? '未知'}</dd>
                  </div>
                  <div>
                    <dt>费用</dt>
                    <dd>
                      {span.cost.amount === null
                        ? '未知'
                        : `${span.cost.amount} ${span.cost.currency} · ${span.cost.kind === 'estimate' ? '估算' : '有凭证'}`}
                    </dd>
                  </div>
                  {span.cost.price_version && (
                    <div>
                      <dt>价格版本</dt>
                      <dd>{span.cost.price_version}</dd>
                    </div>
                  )}
                </dl>
              </>
            )}
            <h3>步骤摘要</h3>
            <p className="step-summary">{spanSummary(span)}</p>
            <div className="detail-note">
              <FileText size={16} />
              <p>
                {view.run.mode === 'synthetic'
                  ? '这是模拟运行的记录。没有真实提供商用量或账单。'
                  : '这里展示已保存的观测。执行成功不代表答案已经通过评价。'}
              </p>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

function RunInspector({
  view,
  selectedSpan,
  selectSpan,
}: {
  view: RunView;
  selectedSpan: string | null;
  selectSpan: (id: string) => void;
}) {
  const [filter, setFilter] = useState('all');
  const [configOpen, setConfigOpen] = useState(false);
  const selected =
    selectedSpan === null
      ? (view.spans.find((span) => span.status === 'failed') ?? view.spans[0] ?? null)
      : (view.spans.find((span) => span.span_id === selectedSpan) ?? null);
  const visibleSpans = view.spans.filter(
    (span) =>
      filter === 'all' || span.kind === filter || (filter === 'failed' && span.status === 'failed'),
  );
  const answer = modelAnswer(view);
  return (
    <>
      <div className="run-header">
        <div className="run-heading">
          <span className="mode-tag">{modeLabels[view.run.mode]}</span>
          <span className="mono muted" title={view.run.run_id}>
            {shortId(view.run.run_id)}
          </span>
          <Status status={view.run.status} />
        </div>
        <h2>{view.run.config.task ?? '未记录任务文本'}</h2>
        <p>
          <Clock3 size={13} /> {dateTime(view.run.created_at)} <span>·</span>{' '}
          {view.run.config.agent.id} <span>·</span>{' '}
          {view.run.parent_run_id ? '分支运行' : '从头运行'} <span>·</span> 记录快照 #
          {view.last_seq}
        </p>
      </div>
      <Metrics view={view} />
      <div className="inspector-grid">
        <section className="process-panel" aria-label="执行步骤">
          <div className="panel-heading">
            <div>
              <ListOrdered size={17} />
              <h2>执行过程</h2>
              <span className="count-pill">{view.spans.length}</span>
            </div>
            <select
              aria-label="筛选步骤"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">全部步骤</option>
              <option value="model">模型调用</option>
              <option value="tool">工具尝试</option>
              <option value="failed">失败步骤</option>
            </select>
          </div>
          <div className="process-caption">
            <span>按实际调用顺序</span>
            <span>状态 / 耗时</span>
          </div>
          <ol className="step-list">
            {visibleSpans.map((span) => (
              <li key={span.span_id}>
                <button
                  className={`step-row ${selected?.span_id === span.span_id ? 'is-selected' : ''}`}
                  aria-pressed={selected?.span_id === span.span_id}
                  onClick={() => selectSpan(span.span_id)}
                >
                  <span className={`step-icon kind-${span.kind}`}>
                    {span.kind === 'model' ? <Cpu size={18} /> : <Wrench size={18} />}
                  </span>
                  <span className="step-body">
                    <span className="step-title">
                      {span.logical_node_id}
                      <small>
                        {span.kind === 'tool' ? `尝试 ${span.attempt}` : `调用 ${span.call_index}`}
                      </small>
                    </span>
                    <span className="step-description">{spanSummary(span)}</span>
                  </span>
                  <span className="step-end">
                    <Status status={span.status} />
                    <span className="mono">{duration(span.duration_ms)}</span>
                  </span>
                  <ChevronRight size={14} className="row-chevron" />
                </button>
              </li>
            ))}
          </ol>
          {visibleSpans.length === 0 && (
            <div className="empty-state compact">
              <Layers2 size={24} />
              <h3>{view.spans.length === 0 ? '尚无调用记录' : '没有匹配的步骤'}</h3>
              <p>
                {view.spans.length === 0
                  ? '刷新记录可读取已保存的新进度。'
                  : '试试切换步骤筛选条件。'}
              </p>
            </div>
          )}
          {selectedSpan !== null && selected === null && (
            <p className="notice" role="status">
              此步骤不在当前运行中，请选择已有步骤。
            </p>
          )}
          <div className="process-footnote">
            <Database size={13} /> 已保存的运行记录 · 查看不会执行模型或工具
          </div>
          {view.run.inherited_span_ids.length > 0 && (
            <p className="notice">
              继承 {view.run.inherited_span_ids.length} 个步骤引用；上方指标只统计本次新增调用。
            </p>
          )}
          {answer && (
            <section className="answer-block">
              <div>
                <FileText size={16} />
                <h3>{view.run.mode === 'synthetic' ? '模拟模型输出' : '模型输出'}</h3>
                <span>尚未评价</span>
              </div>
              <p>{answer}</p>
            </section>
          )}
          <section className="config-block">
            <button
              className="config-toggle"
              aria-expanded={configOpen}
              onClick={() => setConfigOpen(!configOpen)}
            >
              <span>
                <Braces size={15} />
                运行配置与来源
              </span>
              <ChevronRight size={15} className={configOpen ? 'rotated' : ''} />
            </button>
            {configOpen && <JsonBlock value={view.run} empty="配置未知" />}
          </section>
          {!view.run.capabilities.fork_from_checkpoint && (
            <p className="capability-note">
              <LockKeyhole size={13} /> 此记录当前不支持从检查点创建分支。
            </p>
          )}
        </section>
        <StepDetails span={selected} view={view} />
      </div>
    </>
  );
}

export default function App() {
  const [selection, setSelection] = useState(readSelection);
  const [revision, setRevision] = useState(0);
  const [query, setQuery] = useState('');
  const history = useHistory(revision);
  const current = useRun(selection.run, revision);
  const refresh = () => setRevision((value) => value + 1);
  const navigate = useCallback((run: string, span: string | null, replace = false) => {
    const url = new URL(window.location.href);
    url.searchParams.set('run', run);
    if (span === null) url.searchParams.delete('span');
    else url.searchParams.set('span', span);
    window.history[replace ? 'replaceState' : 'pushState'](null, '', url);
    setSelection({ run, span });
  }, []);
  useEffect(() => {
    const back = () => setSelection(readSelection());
    window.addEventListener('popstate', back);
    return () => window.removeEventListener('popstate', back);
  }, []);
  useEffect(() => {
    if (selection.run === null && history.runs.length > 0)
      navigate(history.runs[0].run_id, null, true);
  }, [history.runs, selection.run, navigate]);
  const search = query.trim().toLocaleLowerCase();
  const runs = history.runs
    .map((run) => (current.view?.run.run_id === run.run_id ? current.view.run : run))
    .filter((run) => `${run.config.task ?? ''} ${run.run_id}`.toLocaleLowerCase().includes(search));
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        跳到运行检查
      </a>
      <aside className="sidebar" aria-label="运行历史">
        <a className="brand" href="/">
          <span className="brand-mark">
            <Workflow size={22} />
          </span>
          <span>
            AgentTinker<small>交互式 Agent 实验室</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="workspace-icon">
            <FlaskConical size={16} />
          </span>
          <span>
            本地工作区<small>实验与运行记录</small>
          </span>
        </div>
        <div className="sidebar-section-title">
          <span>运行历史</span>
          <span>{history.total ?? '—'}</span>
        </div>
        <label className="history-search">
          <Search size={14} />
          <input
            aria-label="搜索已加载的运行"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索已加载的记录"
          />
        </label>
        {history.loading && history.runs.length === 0 && (
          <p className="sidebar-message" role="status">
            正在读取历史…
          </p>
        )}
        {history.error && (
          <div className="sidebar-message" role="alert">
            历史读取失败
            <button className="text-button" onClick={refresh}>
              重试
            </button>
          </div>
        )}
        <nav className="history-list" aria-label="选择运行记录">
          {runs.map((run) => (
            <button
              className={`history-item ${selection.run === run.run_id ? 'is-active' : ''}`}
              aria-current={selection.run === run.run_id ? 'page' : undefined}
              key={run.run_id}
              onClick={() => navigate(run.run_id, null)}
            >
              <span className="history-item-top">
                <span>
                  {run.mode === 'synthetic' ? <FlaskConical size={13} /> : <Terminal size={13} />}
                  {modeLabels[run.mode]}
                </span>
                <span>{dateTime(run.created_at)}</span>
              </span>
              <strong>{run.config.task ?? shortId(run.run_id)}</strong>
              <span className="history-item-bottom">
                <Status status={run.status} />
                <code>{run.run_id.slice(-6)}</code>
              </span>
            </button>
          ))}
        </nav>
        {!history.loading && !history.error && runs.length === 0 && (
          <p className="sidebar-message">{search ? '没有匹配的已加载记录' : '暂无运行记录'}</p>
        )}
        {history.next !== null && !history.error && (
          <button className="load-more" disabled={history.loading} onClick={history.loadMore}>
            {history.loading ? '读取中…' : `加载更多 · 已载入 ${history.runs.length} 条`}
          </button>
        )}
        <div className="sidebar-footer">
          <span>
            <Database size={14} /> 本机记录
          </span>
          <small>检查历史 · 保留证据</small>
        </div>
      </aside>
      <main id="main" className="main" tabIndex={-1}>
        <header className="topbar">
          <div>
            <span>工作区</span>
            <ChevronRight size={13} />
            <strong>运行记录</strong>
          </div>
          <span className="readonly-tag">
            <LockKeyhole size={12} />
            只读检查
          </span>
        </header>
        <div className="main-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">OBSERVE · UNDERSTAND</p>
              <h1>
                运行检查台<span className="preview-tag">PREVIEW</span>
              </h1>
              <p>沿着每一次调用，找到结果背后的证据。</p>
            </div>
            <button
              className="button"
              onClick={refresh}
              disabled={history.loading || current.loading}
            >
              <RefreshCw size={14} />
              {current.loading ? '读取中…' : '刷新记录'}
            </button>
          </div>
          {current.error && <ErrorNotice error={current.error} retry={refresh} />}
          {current.loading && !current.view && (
            <div className="empty-state loading-state" role="status">
              <RefreshCw size={26} />
              <h2>正在读取运行记录</h2>
              <p>读取已保存的状态和步骤…</p>
            </div>
          )}
          {current.view && (
            <RecordConnection
              connection={current.connection}
              error={current.streamError}
              count={current.events.length}
              head={current.view.last_seq}
              retry={refresh}
            />
          )}
          {current.view && (
            <RunInspector
              key={current.view.run.run_id}
              view={current.view}
              selectedSpan={selection.span}
              selectSpan={(span) => navigate(current.view!.run.run_id, span)}
            />
          )}
          {selection.run === null && !history.loading && (
            <div className="empty-state welcome">
              <span className="welcome-icon">
                <Workflow size={32} />
              </span>
              <p className="eyebrow">YOUR NEXT DISCOVERY</p>
              <h2>{history.error ? '连接本地运行服务' : '每一次运行，都是一份证据'}</h2>
              <p>
                {history.error
                  ? '服务连接后，可以继续检查保存的实验。'
                  : '选择一条运行，检查模型决策、工具尝试与实际返回。暂无记录时，先在后端运行一个实验。'}
              </p>
              <span className="empty-hint">
                <Database size={13} /> 查看历史不会调用模型
              </span>
            </div>
          )}
          <footer className="main-footer">
            <span>AgentTinker · 让 Agent 的每一步都有据可查</span>
            <span>只读检查 · 事件补读与订阅</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
