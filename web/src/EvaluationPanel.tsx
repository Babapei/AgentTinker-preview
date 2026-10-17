import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  evaluateRun,
  getEvaluation,
  getEvaluations,
  getReviews,
  getScenarios,
  reviewRun,
} from './api';
import { coverageLabels, documentScenario, judgementLabels } from './document-experiment';
import { terminal } from './event-log';
import { actionError, forgetIntent, pendingIntent, rememberIntent } from './mutations';
import { shortId } from './observations';
import {
  parseProtocol,
  type Evaluation,
  type EvaluationPage,
  type ReviewPage,
  type ReviewRequest,
  type RunView,
  type Scenario,
} from './protocol';

function restoredReview(runId: string) {
  try {
    const pending = pendingIntent(`review:${runId}`);
    return pending ? parseProtocol('review_request', pending.body) : null;
  } catch {
    return null;
  }
}

const checkLabels: Record<string, string> = {
  required_documents_returned: '必需文档是否返回',
  required_documents_read: '必需正文是否读取',
  citation_sources_read: '引用 ID 是否来自已读文档',
};
const verdictLabels = { pass: '通过', fail: '未满足', unknown: '未知' } as const;

function ReviewForm({
  evaluation,
  scenario,
  busy,
  submit,
}: {
  evaluation: Evaluation;
  scenario: Scenario;
  busy: boolean;
  submit: (body: ReviewRequest) => Promise<void>;
}) {
  const [initial] = useState(() => {
    const value = restoredReview(evaluation.run_id);
    return value?.evaluation_id === evaluation.evaluation_id ? value : null;
  });
  const [reviewer, setReviewer] = useState(initial?.reviewer ?? '');
  const [coverage, setCoverage] = useState<ReviewRequest['fact_coverage']>(
    initial?.fact_coverage ?? {},
  );
  const [judgement, setJudgement] = useState<ReviewRequest['judgement'] | ''>(
    initial?.judgement ?? '',
  );
  const [explanation, setExplanation] = useState(initial?.explanation ?? '');
  function send(event: FormEvent) {
    event.preventDefault();
    if (!judgement || busy) return;
    void submit({
      evaluation_id: evaluation.evaluation_id,
      input_hash: evaluation.input_hash,
      reviewer: reviewer.trim(),
      fact_coverage: coverage,
      judgement,
      explanation: explanation.trim(),
    });
  }
  return (
    <form onSubmit={send} className="human-review-form" aria-label="人工复核表单">
      <h3>人工复核答案</h3>
      <p>逐项复核事实和材料。材料不足时如实说明可以是合适行为；规则的“未满足”不等于编造。</p>
      <fieldset disabled={busy}>
        <div className="form-grid">
          <label className="form-field">
            复核者署名（本地填写）
            <input
              required
              maxLength={160}
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
          </label>
          {scenario.case.required_facts.map((fact) => (
            <label className="form-field" key={fact.fact_id}>
              {fact.description}
              <select
                required
                value={coverage[fact.fact_id] ?? ''}
                onChange={(e) =>
                  setCoverage({
                    ...coverage,
                    [fact.fact_id]: e.target.value as ReviewRequest['fact_coverage'][string],
                  })
                }
              >
                <option value="">请明确选择</option>
                {Object.entries(coverageLabels).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <label className="form-field">
            人工判断
            <select
              required
              value={judgement}
              onChange={(e) => setJudgement(e.target.value as typeof judgement)}
            >
              <option value="">请选择判断</option>
              {Object.entries(judgementLabels).map(([key, value]) => (
                <option key={key} value={key}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="form-field">
          复核说明
          <textarea
            required
            maxLength={8000}
            value={explanation}
            onChange={(e) => setExplanation(e.target.value)}
          />
        </label>
      </fieldset>
      <p className="form-note">
        署名由本地填写。每次提交追加一份意见，保留旧记录；未确认的相同内容重试沿用原请求标识。
      </p>
      {initial && <p className="form-note">已恢复未确认的复核内容和评价依据。</p>}
      <button
        className="button"
        type="submit"
        disabled={busy || !reviewer.trim() || !explanation.trim() || !judgement}
      >
        {busy ? '正在保存…' : '保存人工复核'}
      </button>
    </form>
  );
}

export default function EvaluationPanel({ view, latest }: { view: RunView; latest: RunView }) {
  const runId = view.run.run_id;
  const ready = terminal(latest.run.status);
  const [initial] = useState(() => restoredReview(runId));
  const [evaluations, setEvaluations] = useState<EvaluationPage | null>(null);
  const [reviews, setReviews] = useState<ReviewPage | null>(null);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [restored, setRestored] = useState<Evaluation | null>(null);
  const [selected, setSelected] = useState(initial?.evaluation_id ?? '');
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [pendingEvaluation, setPendingEvaluation] = useState(() => {
    try {
      return pendingIntent(`evaluate:${runId}`) !== null;
    } catch {
      return false;
    }
  });
  const active = useRef(true),
    sending = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.all([
      getEvaluations(runId, 0, controller.signal),
      getReviews(runId, 0, controller.signal),
      getScenarios(controller.signal),
      initial
        ? getEvaluation(runId, initial.evaluation_id, controller.signal)
        : Promise.resolve(null),
    ])
      .then(([results, opinions, scenarios, anchor]) => {
        if (controller.signal.aborted) return;
        setEvaluations(results);
        setReviews(opinions);
        setScenario(documentScenario(scenarios));
        setRestored(anchor);
        setSelected((value) => value || results.items[0]?.evaluation_id || '');
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(actionError(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [runId, ready, revision, initial]);

  async function assess(body?: ReviewRequest) {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const evaluationBody = { evaluator: { id: 'document-evidence', version: '1' } };
      const intent = rememberIntent(
        `${body ? 'review' : 'evaluate'}:${runId}`,
        body ?? evaluationBody,
      );
      if (!body) setPendingEvaluation(true);
      const result = body
        ? await reviewRun(runId, body, intent.key)
        : await evaluateRun(runId, evaluationBody, intent.key);
      forgetIntent(intent.key);
      if (active.current) {
        if (!body) setPendingEvaluation(false);
        setSelected(result.evaluation_id);
        setRevision((n) => n + 1);
        setSaved(
          body ? '人工意见已保存，既有记录保留。' : '规则评价已保存；答案语义仍需人工复核。',
        );
      }
    } catch (reason) {
      if (active.current) setError(actionError(reason));
    } finally {
      sending.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function more(kind: 'evaluations' | 'reviews') {
    const page = kind === 'evaluations' ? evaluations : reviews;
    if (!page || page.next_offset === null || loading) return;
    setLoading(true);
    setError(null);
    try {
      if (kind === 'evaluations') {
        const next = await getEvaluations(runId, page.next_offset);
        if (active.current)
          setEvaluations((old) => ({
            ...next,
            items: [
              ...(old?.items ?? []),
              ...next.items.filter(
                (item) =>
                  !old?.items.some((previous) => previous.evaluation_id === item.evaluation_id),
              ),
            ],
          }));
      } else {
        const next = await getReviews(runId, page.next_offset);
        if (active.current)
          setReviews((old) => ({
            ...next,
            items: [
              ...(old?.items ?? []),
              ...next.items.filter(
                (item) => !old?.items.some((previous) => previous.review_id === item.review_id),
              ),
            ],
          }));
      }
    } catch (reason) {
      if (active.current) setError(actionError(reason));
    } finally {
      if (active.current) setLoading(false);
    }
  }
  const items = [...(evaluations?.items ?? [])];
  if (restored && !items.some((item) => item.evaluation_id === restored.evaluation_id))
    items.push(restored);
  const current = items.find((item) => item.evaluation_id === selected) ?? items[0];
  return (
    <section className="experiment-panel evaluation-panel" aria-label="文档证据与答案评价">
      <h2>文档证据与答案评价</h2>
      {!terminal(view.run.status) ? (
        <p>当前记录位置尚未结束；结束后的评价与人工复核在这里隐藏。</p>
      ) : (
        <>
          <p>执行状态与答案质量分开。当前为 1 个案例，多次评价不增加独立样本数，不提供统计结论。</p>
          <div className="assessment-actions">
            <button
              className="button primary-button"
              disabled={!ready || busy || loading}
              onClick={() => void assess()}
            >
              {busy
                ? '正在保存…'
                : pendingEvaluation
                  ? '重试未确认规则评价'
                  : evaluations?.total
                    ? '新增一份规则评价'
                    : '运行规则评价'}
            </button>
            <button
              className="text-button"
              disabled={busy || loading}
              onClick={() => setRevision((n) => n + 1)}
            >
              刷新评价记录
            </button>
          </div>
          {loading && <p role="status">正在读取评价记录…</p>}
          {error && (
            <p className="action-error" role="alert">
              {error} 未确认的相同请求可重试，不会重复创建记录。
            </p>
          )}
          {saved && <p role="status">{saved}</p>}
          {evaluations && (
            <p className="form-note">
              规则评价：已载入 {evaluations.items.length} / {evaluations.total} 份；人工意见：已载入{' '}
              {reviews?.items.length ?? 0} / {reviews?.total ?? 0} 份。
            </p>
          )}
          {items.length > 0 && (
            <label className="form-field">
              查看规则评价
              <select
                value={current?.evaluation_id ?? ''}
                disabled={busy}
                onChange={(e) => setSelected(e.target.value)}
              >
                {items.map((item) => (
                  <option key={item.evaluation_id} value={item.evaluation_id}>
                    {shortId(item.evaluation_id)} ·{' '}
                    {item.status === 'failed' ? '评价器失败' : '规则已完成'} · {item.created_at}
                  </option>
                ))}
              </select>
            </label>
          )}
          {evaluations?.next_offset !== null && evaluations?.next_offset !== undefined && (
            <button
              className="text-button"
              disabled={loading || busy}
              onClick={() => void more('evaluations')}
            >
              加载更多规则评价
            </button>
          )}
          {!current && !loading && evaluations && <p>尚未进行规则评价。查看记录不会自动评价。</p>}
          {current && (
            <div className="assessment-result">
              <p>
                评价器：{current.evaluator.id}:{current.evaluator.version} · 输入摘要：
                <code>{current.input_hash}</code>
              </p>
              {current.status === 'failed' ? (
                <p className="action-error">
                  评价器失败：{current.failure_code}。没有生成分数或检查结论，可新增评价重试。
                </p>
              ) : (
                <>
                  <dl className="evidence-documents">
                    <dt>已返回</dt>
                    <dd>{current.returned_document_ids.join('、') || '未记录'}</dd>
                    <dt>已读取正文</dt>
                    <dd>{current.read_document_ids.join('、') || '未记录'}</dd>
                    <dt>回答引用</dt>
                    <dd>{current.cited_document_ids.join('、') || '未记录'}</dd>
                  </dl>
                  <ul className="evidence-checks">
                    {current.checks.map((check) => (
                      <li key={check.check_id}>
                        <strong>
                          {checkLabels[check.check_id] ?? check.check_id}：
                          {verdictLabels[check.verdict]}
                        </strong>
                        <p>{check.explanation}</p>
                      </li>
                    ))}
                  </ul>
                  <p>
                    规则不判定事实语义或是否编造。人工答案评价：
                    {reviews?.items.some((item) => item.evaluation_id === current.evaluation_id)
                      ? '已有人工意见，见下方独立记录'
                      : !reviews || reviews.next_offset !== null
                        ? '人工意见尚未读齐，请继续加载后核对'
                        : '未复核'}
                  </p>
                  {scenario && (
                    <ReviewForm
                      key={current.evaluation_id}
                      evaluation={current}
                      scenario={scenario}
                      busy={busy || loading}
                      submit={assess}
                    />
                  )}
                </>
              )}
            </div>
          )}
          <h3>已保存的人工意见</h3>
          {reviews?.total === 0 && !loading && <p>尚无人工复核记录。规则检查不代替人工意见。</p>}
          {reviews?.items.map((review) => (
            <article className="human-review" key={review.review_id}>
              <p>
                <strong>{judgementLabels[review.judgement]}</strong> · {review.reviewer} ·{' '}
                {review.created_at}
              </p>
              <p>{review.explanation}</p>
              <ul>
                {Object.entries(review.fact_coverage).map(([fact, coverage]) => (
                  <li key={fact}>
                    {scenario?.case.required_facts.find((item) => item.fact_id === fact)
                      ?.description ?? fact}
                    ：{coverageLabels[coverage]}
                  </li>
                ))}
              </ul>
              <p className="form-note">
                依据评价 {review.evaluation_id} · {review.evaluator.id}:{review.evaluator.version} ·{' '}
                <code>{review.input_hash}</code>
              </p>
            </article>
          ))}
          {reviews?.next_offset !== null && reviews?.next_offset !== undefined && (
            <button
              className="text-button"
              disabled={loading || busy}
              onClick={() => void more('reviews')}
            >
              加载更多人工意见
            </button>
          )}
        </>
      )}
    </section>
  );
}
