import { useEffect, useState } from 'react';
import { getRun } from './api';
import { compareRuns, runEvidence } from './comparison';
import { actionError } from './mutations';
import { duration, modeLabels, modelAnswer, shortId } from './observations';
import type { RunView } from './protocol';
import Status from './Status';

function cost(value: ReturnType<typeof runEvidence>['cost']) {
  return value
    ? `${value.amount} ${value.currency} · ${value.kind === 'estimate' ? '估算' : '有凭证'}`
    : '未知';
}

export default function ComparisonPanel({
  view,
  navigate,
}: {
  view: RunView;
  navigate: (run: string) => void;
}) {
  const [source, setSource] = useState<RunView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [guidance, setGuidance] = useState(true);
  const parent = view.run.parent_run_id;
  useEffect(() => {
    if (!parent) return;
    const controller = new AbortController();
    setSource(null);
    setError(null);
    getRun(parent, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setSource(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(actionError(reason));
      });
    return () => controller.abort();
  }, [parent, revision]);
  if (!parent) return null;
  const comparison = source ? compareRuns(source, view) : null;
  return (
    <section className="experiment-panel comparison-panel" aria-label="A/B 运行对比">
      <div className="panel-heading">
        <div>
          <h2>A/B 运行对比</h2>
        </div>
        <button
          className="text-button"
          aria-pressed={guidance}
          onClick={() => setGuidance((value) => !value)}
        >
          {guidance ? '隐藏实验讲解' : '显示实验讲解'}
        </button>
      </div>
      <p className="comparison-lineage">
        A：
        <button className="text-button mono" onClick={() => navigate(parent)}>
          {shortId(parent)} · 查看父运行
        </button>{' '}
        → B：<code>{shortId(view.run.run_id)}</code>
        <br />
        分支点：<code>{view.run.source_checkpoint_id}</code>
      </p>
      {error && (
        <p className="action-error" role="alert">
          {error}
          <button className="text-button" onClick={() => setRevision((n) => n + 1)}>
            重新读取父运行
          </button>
        </p>
      )}
      {!source && !error && <p role="status">正在读取父运行证据…</p>}
      {source && comparison && (
        <>
          <div className="config-differences">
            <h3>先看配置改动</h3>
            {comparison.changed.map((change) => (
              <p key={change.path}>
                <code>{change.path}</code>：<code>{JSON.stringify(change.before) ?? '未知'}</code> →{' '}
                <code>{JSON.stringify(change.after) ?? '未知'}</code>
              </p>
            ))}
            {!comparison.changed.length && <p>未检测到配置改动。</p>}
            {!comparison.singleFactor && (
              <p className="action-error" role="status">
                配置或来源不满足单变量对照，不能仅归因于这一参数。
              </p>
            )}
          </div>
          <p className="form-note">
            B 引用 {view.run.inherited_span_ids.length} 个既有步骤，只计分支后的新增调用、Token
            与费用。A 为完整父运行，B 随当前历史记录位置显示。单次结果仅是个例。
          </p>
          <div className="comparison-table-wrap">
            <table className="comparison-table">
              <caption>已记录的过程与新增量</caption>
              <thead>
                <tr>
                  <th scope="col">观测项</th>
                  <th scope="col">A · 完整父运行</th>
                  <th scope="col">B · 当前记录位置</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">模式</th>
                  <td>{modeLabels[source.run.mode]}</td>
                  <td>{modeLabels[view.run.mode]}</td>
                </tr>
                <tr>
                  <th scope="row">执行状态</th>
                  <td>
                    <Status status={source.run.status} />
                  </td>
                  <td>
                    <Status status={view.run.status} />
                  </td>
                </tr>
                <tr>
                  <th scope="row">新增模型调用</th>
                  <td>{comparison.source.modelCalls}</td>
                  <td>{comparison.branch.modelCalls}</td>
                </tr>
                <tr>
                  <th scope="row">逻辑工具调用 / 尝试</th>
                  <td>
                    {comparison.source.toolCalls} / {comparison.source.toolAttempts}
                  </td>
                  <td>
                    {comparison.branch.toolCalls} / {comparison.branch.toolAttempts}
                  </td>
                </tr>
                <tr>
                  <th scope="row">新增 Token</th>
                  <td>{comparison.source.totalTokens ?? '未知'}</td>
                  <td>{comparison.branch.totalTokens ?? '未知'}</td>
                </tr>
                <tr>
                  <th scope="row">已记录费用</th>
                  <td>{cost(comparison.source.cost)}</td>
                  <td>{cost(comparison.branch.cost)}</td>
                </tr>
                <tr>
                  <th scope="row">新增调用耗时合计</th>
                  <td>{duration(comparison.source.callTime)}</td>
                  <td>{duration(comparison.branch.callTime)}</td>
                </tr>
                <tr>
                  <th scope="row">取得的文档 ID</th>
                  <td>{comparison.source.documents.join('、') || '未记录返回材料'}</td>
                  <td>{comparison.branch.documents.join('、') || '未记录返回材料'}</td>
                </tr>
                <tr>
                  <th scope="row">答案评价</th>
                  <td>未评价</td>
                  <td>未评价</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="comparison-outputs">
            {[source, view].map((run, index) => (
              <div key={`${index}:${run.run.run_id}`}>
                <h3>{index === 0 ? 'A' : 'B'} · 已记录回答</h3>
                <p>{modelAnswer(run) ?? '未记录最终回答'}</p>
              </div>
            ))}
          </div>
          {guidance && (
            <aside className="experiment-explanation" aria-label="实验讲解">
              <h3>这份证据说明什么</h3>
              <p>
                {comparison.retryObserved
                  ? '两次运行的首次工具尝试均发生相同注入超时；B 的第二次尝试取得材料。新增重试由执行器负责，不能据此称模型学会了恢复。'
                  : comparison.sameFirstFault
                    ? '两次运行已记录相同首次故障，请继续检查后续尝试与最终状态。'
                    : '当前证据尚不足以验证同一首次超时后的修复；未触发故障时不纳入超时结论。'}
              </p>
              <p>
                分支沿用原模型查询与调用身份：
                {comparison.sameCall ? '已在工具记录中核对' : '当前记录尚无法核对'}
                。模型重新生成的答案可能变化；执行成功不代表答案正确，引用与内容仍需独立评价。
              </p>
            </aside>
          )}
        </>
      )}
    </section>
  );
}
