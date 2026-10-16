import Decimal from 'decimal.js';
import type { Run, RunView, Span } from './protocol';

export const statusLabels: Record<Run['status'] | Span['status'], string> = {
  queued: '排队中',
  running: '运行中',
  cancel_requested: '正在取消',
  succeeded: '执行成功',
  failed: '执行失败',
  cancelled: '已取消',
  interrupted: '已中断',
};

export const modeLabels: Record<Run['mode'], string> = {
  live: '真实调用',
  synthetic: '模拟运行',
  recorded: '录制记录',
  imported: '导入记录',
};

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function textField(value: unknown, key: string): string | null {
  return isRecord(value) && typeof value[key] === 'string' ? value[key] : null;
}

export function modelAnswer(view: RunView): string | null {
  const lastModel = [...view.spans].reverse().find((span) => span.kind === 'model');
  return textField(lastModel?.output?.message, 'content');
}

function sumCosts(amounts: string[]): string {
  const values = amounts.map((amount) => new Decimal(amount));
  const decimals = Math.max(...values.map((value) => value.decimalPlaces()));
  const integerDigits = Math.max(1, ...values.map((value) => value.e + 1));
  const Sum = Decimal.clone({
    precision: integerDigits + decimals + Math.ceil(Math.log10(values.length)) + 1,
  });
  return values.reduce((sum, value) => sum.plus(value), new Sum(0)).toFixed();
}

export function summarize(view: RunView) {
  const models = view.spans.filter((span) => span.kind === 'model');
  const tools = view.spans.filter((span) => span.kind === 'tool');
  const known = models.filter((span) => span.usage.total_tokens !== null);
  const knownTokens = known.reduce((sum, span) => sum + span.usage.total_tokens!, 0);
  const costs = models.map((span) => span.cost);
  const first = costs[0];
  const comparable =
    costs.length > 0 &&
    costs.every(
      (cost) =>
        cost.amount !== null &&
        cost.kind !== 'unknown' &&
        cost.kind === first.kind &&
        cost.currency === first.currency &&
        cost.price_version === first.price_version,
    );
  return {
    modelCalls: models.length,
    toolCalls: new Set(tools.map((span) => span.logical_call_id)).size,
    toolAttempts: tools.length,
    knownUsage: known.length,
    totalTokens: known.length === models.length ? knownTokens : null,
    cost: comparable
      ? {
          amount: sumCosts(costs.map((cost) => cost.amount!)),
          kind: first.kind,
          currency: first.currency,
        }
      : null,
  };
}

export function duration(value: number | null): string {
  if (value === null) return '未知';
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(1)} ms`;
}

export function shortId(value: string): string {
  return value.length > 20 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value;
}

export function dateTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value));
}

export function spanSummary(span: Span): string {
  const error = textField(span.output, 'error_code');
  if (error) return error;
  if (span.status === 'running') return '等待调用返回';
  if (span.status === 'interrupted' && span.output === null) return '调用中断，未取得结果';
  if (span.output === null) return '未记录输出';
  const documents = span.output.documents;
  if (Array.isArray(documents)) return `返回 ${documents.length} 份本地文档`;
  const message = span.output.message;
  const content = textField(message, 'content');
  if (content) return content;
  if (isRecord(message) && Array.isArray(message.tool_calls)) return '请求调用工具';
  return '查看原始输出';
}
