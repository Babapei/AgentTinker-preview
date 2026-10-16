import { beforeAll, expect, it } from 'vitest';
import { compareRuns, runEvidence } from './comparison';
import { eventFixtures } from './test/event-fixtures';

let examples: ReturnType<typeof eventFixtures>;
beforeAll(() => {
  examples = eventFixtures();
});

it('compares real native fork evidence without charging its inherited model prefix again', () => {
  const a = examples.failed.view,
    b = examples.forked.view;
  const comparison = compareRuns(a, b);
  expect(comparison).toMatchObject({
    lineage: true,
    singleFactor: true,
    sameCall: true,
    sameFirstFault: true,
    retryObserved: true,
  });
  expect(comparison.changed).toEqual([
    { path: 'tool_policy.tool_retry_limit', before: 0, after: 1 },
  ]);
  expect(comparison.source.modelCalls).toBe(1);
  expect(comparison.branch.modelCalls).toBe(1);
  expect(comparison.source.toolAttempts).toBe(1);
  expect(comparison.branch.toolAttempts).toBe(2);
  expect(comparison.branch.documents).toEqual(['release-v1', 'release-v2']);
  expect(comparison.branch.totalTokens).toBeNull();
  expect(comparison.branch.cost).toBeNull();
});

it.each(['task', 'mode', 'patch', 'lineage'] as const)(
  'refuses single-factor attribution with inconsistent %s',
  (defect) => {
    const a = structuredClone(examples.failed.view),
      b = structuredClone(examples.forked.view);
    if (defect === 'task') b.run.config.task = 'another task';
    if (defect === 'mode') b.run.mode = 'live';
    if (defect === 'patch') b.run.intervention!.patch.tool_retry_limit = 3;
    if (defect === 'lineage') b.run.parent_run_id = 'foreign';
    expect(compareRuns(a, b).singleFactor).toBe(false);
    expect(compareRuns(a, b).retryObserved).toBe(false);
  },
);

it('keeps the historical branch prefix free of future tools, documents and answers', () => {
  const prefix = examples.forked.prefixes[0];
  const comparison = compareRuns(examples.failed.view, prefix);
  expect(comparison.branch.modelCalls).toBe(0);
  expect(comparison.branch.toolAttempts).toBe(0);
  expect(comparison.branch.documents).toEqual([]);
  expect(comparison.retryObserved).toBe(false);
});

it('retains observed zero and unknown interrupted timing without inventing evaluation', () => {
  const view = structuredClone(examples.forked.view);
  view.spans.find((span) => span.kind === 'model')!.usage.total_tokens = 0;
  expect(runEvidence(view).totalTokens).toBe(0);
  view.spans[0].duration_ms = null;
  expect(runEvidence(view).callTime).toBeNull();
});
