import { useEffect, useState } from 'react';
import { getProvenance } from './api';
import { coverageLabels, judgementLabels } from './document-experiment';
import { terminal } from './event-log';
import { modeLabels } from './observations';
import type { ImportProvenance, RunView } from './protocol';
import JsonBlock from './JsonBlock';

const verdicts = { pass: '通过', fail: '未满足', unknown: '未知' };

export default function ImportProvenancePanel({ view }: { view: RunView }) {
  const [source, setSource] = useState<ImportProvenance | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  const [limit, setLimit] = useState(10);
  const runId = view.run.run_id;
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    getProvenance(runId, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        if (value === null) setError(true);
        else setSource(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, [runId, revision]);
  const showOpinions = terminal(view.run.status);
  return (
    <section
      className="experiment-panel comparison-panel package-panel"
      aria-label="导入来源与原意见"
    >
      <h2>导入来源与原意见</h2>
      <p className="notice">
        外部记录声明，未核验来源身份、提供商调用或实际账单。当前只供检查，不支持运行、取消、分支或新增评价。
      </p>
      {!view.run.capabilities.record_playback && (
        <p>此包仅含摘要，没有完整事件可播放；所示状态是来源记录的观测状态。</p>
      )}
      {error ? (
        <div role="alert">
          <p>暂时无法读取来源信息。</p>
          <button className="button" onClick={() => setRevision((n) => n + 1)}>
            重读来源
          </button>
        </div>
      ) : !source ? (
        <p role="status">正在读取包来源…</p>
      ) : (
        <>
          <h3>{source.title}</h3>
          <dl className="evidence-documents">
            <dt>原记录模式</dt>
            <dd>{modeLabels[source.source_mode]}（来源声明）</dd>
            <dt>原运行 ID</dt>
            <dd>
              <code>{source.source_run_id}</code>
            </dd>
            <dt>来源说明</dt>
            <dd>{source.source}</dd>
            <dt>包许可</dt>
            <dd>{source.license ?? '未知'}</dd>
          </dl>
          {source.context && (
            <details>
              <summary>实验任务、成功标准与材料</summary>
              <p>{source.context.experiment.description}</p>
              <ul>
                {source.context.experiment.success_criteria.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
              <p>任务：{source.context.case.task}</p>
              <JsonBlock value={source.context} empty="未记录实验上下文" />
            </details>
          )}
          <details>
            <summary>来源与可分发内容摘要</summary>
            <p>
              原摘要与去除定位/能力后的摘要分别保留。原意见仍绑定包内源 ID，不是对本地新 ID
              的重新评价。
            </p>
            <JsonBlock
              value={{
                source_package_sha256: source.source_package_sha256,
                portable_package_sha256: source.portable_package_sha256,
                source_view_sha256: source.source_view_sha256,
                portable_view_sha256: source.portable_view_sha256,
              }}
              empty="摘要未知"
            />
          </details>
          {!showOpinions ? (
            <p>当前位置尚未结束，结束后的原评价与人工意见在这里隐藏。</p>
          ) : (
            <div className="source-opinions">
              <h3>原规则评价 · {source.evaluations.length} 份</h3>
              <p>来源中保存的规则结果与人工意见分别展示；单次记录不作统计结论。</p>
              {source.evaluations.slice(0, limit).map((evaluation) => (
                <article className="assessment-result" key={evaluation.evaluation_id}>
                  <strong>
                    {evaluation.evaluator.id}:{evaluation.evaluator.version} ·{' '}
                    {evaluation.status === 'failed' ? '评价失败' : '规则结果'}
                  </strong>
                  <p>
                    原评价 ID：<code>{evaluation.evaluation_id}</code>
                  </p>
                  {evaluation.failure_code && <p>失败类型：{evaluation.failure_code}</p>}
                  <ul className="evidence-checks">
                    {evaluation.checks.map((check) => (
                      <li key={check.check_id}>
                        {check.check_id}：{verdicts[check.verdict]} · {check.explanation}
                      </li>
                    ))}
                  </ul>
                  <details>
                    <summary>原评价与证据绑定</summary>
                    <JsonBlock
                      value={{
                        evaluation,
                        binding: source.evaluation_bindings.find(
                          (b) => b.evaluation_id === evaluation.evaluation_id,
                        ),
                      }}
                      empty="未记录"
                    />
                  </details>
                </article>
              ))}
              <h3>原人工意见 · {source.reviews.length} 份</h3>
              {source.reviews.slice(0, limit).map((review) => (
                <article className="human-review" key={review.review_id}>
                  <strong>{judgementLabels[review.judgement]}</strong>
                  <p>来源署名（未认证）：{review.reviewer}</p>
                  <p>{review.explanation}</p>
                  <ul>
                    {Object.entries(review.fact_coverage).map(([id, value]) => (
                      <li key={id}>
                        {id}：{coverageLabels[value]}
                      </li>
                    ))}
                  </ul>
                  <details>
                    <summary>原意见与评价依据</summary>
                    <JsonBlock value={review} empty="未记录" />
                  </details>
                </article>
              ))}
              {(source.evaluations.length > limit || source.reviews.length > limit) && (
                <button className="button" onClick={() => setLimit((n) => n + 10)}>
                  显示更多原意见
                </button>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
