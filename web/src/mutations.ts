import equal from 'fast-deep-equal';
import { ApiError } from './api';

type Intent = { scope: string; body: unknown; key: string };
const storageKey = 'agenttinker.pending-requests.v1';

function intents(): Intent[] {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? '[]');
    if (
      !Array.isArray(value) ||
      value.some(
        (item) =>
          !item ||
          typeof item.scope !== 'string' ||
          typeof item.key !== 'string' ||
          !('body' in item),
      )
    )
      throw new Error('invalid_pending_requests');
    return value;
  } catch {
    throw new Error('request_memory_unavailable');
  }
}

export function pendingIntent(scope: string) {
  return (
    intents()
      .filter((item) => item.scope === scope)
      .at(-1) ?? null
  );
}

export function rememberIntent(scope: string, body: unknown): Intent {
  const pending = intents();
  const previous = pending.find((item) => item.scope === scope && equal(item.body, body));
  if (previous) return previous;
  const intent = { scope, body: structuredClone(body), key: crypto.randomUUID() };
  try {
    sessionStorage.setItem(storageKey, JSON.stringify([...pending, intent]));
  } catch {
    throw new Error('request_memory_unavailable');
  }
  return intent;
}

export function forgetIntent(key: string) {
  // A completed response is authoritative even if browser storage subsequently fails.
  try {
    sessionStorage.setItem(
      storageKey,
      JSON.stringify(intents().filter((item) => item.key !== key)),
    );
  } catch {
    /* Retaining an old key is safe: the server returns the same run. */
  }
}

export function actionError(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  const known: Record<string, string> = {
    provider_not_configured: '真实模型尚未配置。请在服务端配置提供商密钥与模型后重试。',
    invalid_patch: '请选择一个允许的参数，并改为不同的有效整数。',
    checkpoint_missing: '运行时检查点已缺失；可以继续查看历史，或从头创建实验。',
    runtime_incompatible: '运行时、数据或价格版本不兼容，请使用匹配版本或从头创建实验。',
    unsupported_capability: '这条记录不支持从检查点分支。',
    source_run_active: '请等待原运行结束后创建分支。',
    checkpoint_state_invalid: '检查点状态与原运行不一致，无法创建分支。',
    checkpoint_unreadable: '运行时检查点无法读取，可以继续查看已保存的记录。',
    idempotency_key_payload_conflict: '请求标识与已保存的内容冲突，请核对运行历史。',
    invalid_request: '配置未通过校验，请检查任务和参数。',
    protocol_invalid: '响应协议或运行来源不兼容，请核对前后端版本后重试同一请求。',
    request_memory_unavailable: '浏览器无法暂存请求，请启用本站会话存储后重试。',
    scenario_not_found: '该场景当前不可用，请重新读取场景定义。',
    assessment_not_found: '评价或复核记录不存在，请重新读取记录。',
    evaluation_run_active: '请等待运行结束后执行规则评价。',
    evaluation_context_mismatch: '用例、材料或评价版本不匹配，无法评价这条记录。',
    evaluator_unsupported: '当前服务不支持该评价器版本。',
    review_evidence_mismatch: '复核依据的输入摘要不匹配，请重新读取评价。',
    review_evaluation_failed: '规则评价尚未成功完成，请先新增一份规则评价。',
    package_invalid: '文件格式、版本、哈希或引用未通过校验，请选择完整的 AgentTinker JSON 包。',
    package_too_large: '文件超过实验包大小上限（8 MiB）。',
    package_run_active: '请等待实际运行结束后导出。',
    package_context_unsupported: '此运行的模板或上下文尚不支持导出实验包。',
    package_context_mismatch: '运行与实验定义不一致，无法导出。',
    artifact_not_exportable: '费用凭据尚未标记为可分发，无法导出。',
    artifact_contains_credentials: '费用凭据含已识别的密钥字段，请先处理源文件。',
    unsupported_package_type: '请选择 AgentTinker JSON 实验包。',
    imported_record_read_only: '导入记录只供检查，原评价保存在来源中。',
  };
  return (
    known[code] ??
    (error instanceof ApiError && error.status === 422
      ? '配置未通过校验，请检查任务和参数。'
      : '未能确认操作结果。请查看历史，或重试同一请求。')
  );
}
