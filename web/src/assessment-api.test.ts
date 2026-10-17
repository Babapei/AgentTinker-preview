import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import {
  createDocumentRun,
  evaluateRun,
  getEvaluations,
  getReviews,
  getScenarios,
  reviewRun,
} from './api';
import {
  parseProtocol,
  type DocumentRunRequest,
  type Evaluation,
  type EvaluationPage,
  type HumanReview,
  type ReviewPage,
  type ReviewRequest,
  type RunView,
  type Scenario,
} from './protocol';

let fixture: {
  scenario: Scenario;
  view: RunView;
  evaluation: Evaluation;
  review: HumanReview;
  evaluation_page: EvaluationPage;
  review_page: ReviewPage;
};
beforeAll(() => {
  fixture = JSON.parse(
    execFileSync('uv', ['run', 'python', 'scripts/export_assessment_fixtures.py'], {
      cwd: fileURLToPath(new URL('../../', import.meta.url)),
      encoding: 'utf8',
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

it('validates real Python scenario/evaluation/review response contracts', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async () => Response.json([fixture.scenario])),
  );
  expect(await getScenarios()).toEqual([fixture.scenario]);
  expect(parseProtocol('evaluation', fixture.evaluation).answer_review).toBe('unreviewed');
  expect(parseProtocol('human_review', fixture.review).judgement).toBe('justified_insufficiency');
  expect(() => parseProtocol('evaluation', { ...fixture.evaluation, status: 'perfect' })).toThrow(
    'protocol_invalid',
  );
});

it('writes the selected document case and rejects a different provenance', async () => {
  const body: DocumentRunRequest = {
    mode: 'synthetic',
    provider: null,
    model: null,
    variant: 'baseline',
  };
  const fetcher = vi.fn().mockImplementation(async () => Response.json(fixture.view));
  vi.stubGlobal('fetch', fetcher);
  expect(await createDocumentRun(body, fixture.scenario, 'document-key')).toEqual(fixture.view);
  expect(fetcher.mock.calls[0][1].headers['Idempotency-Key']).toBe('document-key');
  await expect(
    createDocumentRun({ ...body, variant: 'candidate' }, fixture.scenario, 'wrong'),
  ).rejects.toThrow('protocol_invalid');
});

it('preserves assessment pages and rejects another run in either list', async () => {
  const run = fixture.view.run.run_id;
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async () => Response.json(fixture.evaluation_page)),
  );
  expect(await getEvaluations(run)).toEqual(fixture.evaluation_page);
  await expect(getEvaluations('foreign')).rejects.toThrow('protocol_invalid');
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async () => Response.json(fixture.review_page)),
  );
  expect(await getReviews(run)).toEqual(fixture.review_page);
  await expect(getReviews('foreign')).rejects.toThrow('protocol_invalid');
});

it('checks evaluator identity and every submitted review field before acknowledging', async () => {
  const run = fixture.view.run.run_id;
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async () => Response.json(fixture.evaluation)),
  );
  const body = { evaluator: { id: 'document-evidence', version: '1' } };
  expect(await evaluateRun(run, body, 'key')).toEqual(fixture.evaluation);
  await expect(
    evaluateRun(run, { evaluator: { ...body.evaluator, version: '2' } }, 'other'),
  ).rejects.toThrow('protocol_invalid');
  const review: ReviewRequest = {
    evaluation_id: fixture.review.evaluation_id,
    input_hash: fixture.review.input_hash,
    reviewer: fixture.review.reviewer,
    fact_coverage: fixture.review.fact_coverage,
    judgement: fixture.review.judgement,
    explanation: fixture.review.explanation,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(async () => Response.json(fixture.review)),
  );
  expect(await reviewRun(run, review, 'review-key')).toEqual(fixture.review);
  await expect(reviewRun(run, { ...review, explanation: 'different' }, 'bad')).rejects.toThrow(
    'protocol_invalid',
  );
});
