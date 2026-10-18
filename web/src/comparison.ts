import equal from 'fast-deep-equal';
import type { RunView } from './protocol';
import { isRecord, summarize } from './observations';
import { isDocumentRun } from './document-experiment';

export type Difference = { path: string; before: unknown; after: unknown };
function differences(before: unknown, after: unknown, path = ''): Difference[] {
  if (equal(before, after)) return [];
  if (isRecord(before) && isRecord(after))
    return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap((key) =>
      differences(before[key], after[key], path ? `${path}.${key}` : key),
    );
  return [{ path, before, after }];
}

export function runEvidence(view: RunView) {
  const documents = view.spans
    .flatMap((span) => (Array.isArray(span.output?.documents) ? span.output.documents : []))
    .filter(isRecord)
    .map((doc) => (typeof doc.id === 'string' ? doc.id : null))
    .filter((id): id is string => id !== null);
  return {
    ...summarize(view),
    documents: [...new Set(documents)],
    readDocuments: [
      ...new Set(
        view.spans
          .filter(
            (span) =>
              span.kind === 'tool' &&
              span.status === 'succeeded' &&
              span.logical_node_id === 'read_document',
          )
          .map((span) => span.output?.document)
          .filter(isRecord)
          .map((doc) => doc.id)
          .filter((id): id is string => typeof id === 'string'),
      ),
    ],
    callTime: view.spans.some((span) => span.duration_ms === null)
      ? null
      : view.spans.reduce((sum, span) => sum + span.duration_ms!, 0),
  };
}

export function compareRuns(source: RunView, branch: RunView) {
  const changed = differences(source.run.config, branch.run.config);
  if (source.run.mode !== branch.run.mode)
    changed.unshift({ path: 'mode', before: source.run.mode, after: branch.run.mode });
  const intervention = branch.run.intervention;
  const documentCase =
    isDocumentRun(source.run) &&
    isDocumentRun(branch.run) &&
    [source, branch].every(
      (view) =>
        view.run.config.case?.id === 'release-v2-evidence' && view.run.config.case.version === '1',
    );
  const derivedVariant =
    documentCase &&
    source.run.config.agent.version === branch.run.config.agent.version &&
    [source, branch].every(({ run }) => {
      const k = run.config.tool_policy.top_k;
      return (
        typeof k === 'number' &&
        Number.isInteger(k) &&
        k >= 1 &&
        k <= 3 &&
        run.config.tool_policy.tool_retry_limit === 0 &&
        run.config.variant?.id === `document-top${k}` &&
        run.config.variant.version === '1'
      );
    });
  const factors = derivedVariant
    ? changed.filter((change) => change.path !== 'variant.id')
    : changed;
  const lineage =
    branch.run.parent_run_id === source.run.run_id &&
    source.checkpoints.some((cp) => cp.checkpoint_id === branch.run.source_checkpoint_id);
  const singleFactor =
    lineage &&
    (!documentCase || derivedVariant) &&
    !!intervention &&
    Object.keys(intervention.patch).length === 1 &&
    factors.length === 1 &&
    intervention.parent_run_id === source.run.run_id &&
    intervention.source_checkpoint_id === branch.run.source_checkpoint_id &&
    factors[0].path === `tool_policy.${Object.keys(intervention.patch)[0]}` &&
    equal({ ...intervention.before, ...intervention.patch }, intervention.after) &&
    equal(intervention.before, source.run.config.tool_policy) &&
    equal(intervention.after, branch.run.config.tool_policy);
  const a = source.spans.filter((span) => span.kind === 'tool'),
    b = branch.spans.filter((span) => span.kind === 'tool');
  const sameCall = !!a[0] && !!b[0] && equal(a[0].input?.tool_call, b[0].input?.tool_call);
  const sameFirstFault =
    !!a[0] &&
    !!b[0] &&
    a[0].status === 'failed' &&
    b[0].status === 'failed' &&
    a[0].output?.origin === 'injected' &&
    b[0].output?.origin === 'injected' &&
    a[0].output?.error_code === b[0].output?.error_code &&
    equal(source.run.config.fault_plan, branch.run.config.fault_plan) &&
    equal(source.run.config.fault_parameters, branch.run.config.fault_parameters);
  return {
    changed,
    lineage,
    singleFactor,
    derivedVariant,
    documentCase,
    sameCall,
    sameFirstFault,
    retryObserved:
      singleFactor &&
      intervention?.patch.tool_retry_limit !== undefined &&
      source.run.config.tool_policy.tool_retry_limit === 0 &&
      sameCall &&
      sameFirstFault &&
      b.some((span) => span.attempt === 2 && span.status === 'succeeded'),
    source: runEvidence(source),
    branch: runEvidence(branch),
  };
}
