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
import { documentRequestIdentity, documentScenario, isDocumentRun } from './document-experiment';
import { offlineFixture } from './test/offline-fixtures';

let fixture: {
  scenario: Scenario;
  scenarios: Scenario[];
  v2_view: RunView;
  view: RunView;
  evaluation: Evaluation;
  review: HumanReview;
  evaluation_page: EvaluationPage;
  review_page: ReviewPage;
};
beforeAll(() => {
  fixture = offlineFixture('assessments');
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

it('keeps omitted legacy request fields valid and applies their server defaults', async () => {
  const body = { mode: 'synthetic' } as const;
  expect(parseProtocol('document_run_request', body)).toEqual(body);
  expect(() => parseProtocol('document_run_request', { ...body, agent_version: '3' })).toThrow(
    'protocol_invalid',
  );
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(fixture.view)));
  expect(await createDocumentRun(body, fixture.scenario, 'legacy-defaults')).toEqual(fixture.view);
});

it('rejects a request and scenario version mismatch before sending a write', async () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  await expect(
    createDocumentRun({ mode: 'synthetic', agent_version: '2' }, fixture.scenario, 'wrong-version'),
  ).rejects.toThrow('protocol_invalid');
  expect(fetcher).not.toHaveBeenCalled();
});

it('selects the newest known scenario while restoring the requested legacy version', () => {
  expect(documentScenario(fixture.scenarios).agent.ref.version).toBe('2');
  expect(documentScenario(fixture.scenarios, '1')).toEqual(fixture.scenario);
  expect(documentScenario([fixture.scenario]).agent.ref.version).toBe('1');
  expect(() => documentScenario([fixture.scenarios[0]], '1')).toThrow('protocol_invalid');
});

it('rejects mismatched scenario, prompt and agent versions', () => {
  const mixed = structuredClone(fixture.scenarios[0]);
  mixed.agent.ref.version = '1';
  expect(() => documentScenario([mixed])).toThrow('protocol_invalid');
  const prompt = structuredClone(fixture.scenarios[0]);
  prompt.agent.prompt_version = 'document-react-v1';
  expect(() => documentScenario([prompt])).toThrow('protocol_invalid');
});

it('recognizes both document versions while refusing mixed or unknown identities', () => {
  expect(isDocumentRun(fixture.view.run)).toBe(true);
  expect(isDocumentRun(fixture.v2_view.run)).toBe(true);
  const mixed = structuredClone(fixture.v2_view.run);
  mixed.config.experiment!.version = '1';
  expect(isDocumentRun(mixed)).toBe(false);
  mixed.config.agent.version = '3';
  expect(isDocumentRun(mixed)).toBe(false);
});

it('compares defaulted request meaning without changing the original stored body', () => {
  const legacy = { mode: 'synthetic' } as const;
  expect(documentRequestIdentity(legacy)).toBe(
    documentRequestIdentity({
      ...legacy,
      provider: null,
      model: null,
      variant: 'baseline',
      agent_version: '1',
    }),
  );
  expect(documentRequestIdentity(legacy)).not.toBe(
    documentRequestIdentity({ ...legacy, agent_version: '2' }),
  );
  expect(legacy).toEqual({ mode: 'synthetic' });
});

it('checks a v2 creation response against its own definition', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(fixture.v2_view)));
  const body = { mode: 'synthetic', agent_version: '2' } as const;
  expect(await createDocumentRun(body, fixture.scenarios[0], 'v2')).toEqual(fixture.v2_view);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(fixture.view)));
  await expect(createDocumentRun(body, fixture.scenarios[0], 'mixed-response')).rejects.toThrow(
    'protocol_invalid',
  );
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
