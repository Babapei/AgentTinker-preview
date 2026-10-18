// Local historical-data comparison in Phoenix, never a new Agent execution or user study.
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = process.argv[2] ?? 'http://127.0.0.1:16009';
assert.equal(new URL(base).hostname, '127.0.0.1', 'local_comparison_only');
const payloadPath = process.argv[3] ?? `${root}artifacts/m5-phoenix-experiments.json`;
const output = process.argv[4] ?? `${root}artifacts/m5-phoenix-comparison.json`;
const payload = JSON.parse(await readFile(payloadPath, 'utf8'));
assert.equal(payload.schema_version, 'm5-phoenix-experiments-1');
assert.equal(payload.dataset.inputs.length, 2);
const check = expect.configure({ timeout: 15_000 });
const canonical = (value) =>
  Array.isArray(value)
    ? value.map(canonical)
    : value && typeof value === 'object'
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, canonical(value[key])]),
        )
      : value;
const hash = (value) =>
  createHash('sha256')
    .update(JSON.stringify(canonical(value)))
    .digest('hex');
const files = ['tool-timeout.json', 'document-missing-v2.json'];
const sources = await Promise.all(
  files.map((file) => readFile(`${root}examples/m4/${file}`, 'utf8')),
);
assert.deepEqual(
  payload.dataset.metadata.map((item) => item.source_package_sha256),
  sources.map((source) => hash(JSON.parse(source))),
);
const requests = [];
async function request(path, body) {
  if (body) requests.push(path);
  const response = await fetch(`${base}${path}`, {
    signal: AbortSignal.timeout(30_000),
    method: body ? 'POST' : 'GET',
    ...(body
      ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : {}),
  });
  assert(response.ok, `phoenix_request_failed:${response.status}:${path}`);
  return response.json();
}
const spans = () => request('/v1/projects/agenttinker-m5/spans?limit=1000');
const originalSpans = await spans();
assert.equal(originalSpans.data.length, 22);
const datasetName = `${payload.dataset.name}-${randomUUID().slice(0, 8)}`;
const dataset = (
  await request('/v1/datasets/upload?sync=true', {
    ...payload.dataset,
    action: 'create',
    name: datasetName,
  })
).data;
assert.equal(dataset.num_created_examples, 2);
const examples = (
  await request(`/v1/datasets/${dataset.dataset_id}/examples?version_id=${dataset.version_id}`)
).data.examples;
const bySource = new Map(
  examples.map((example) => [example.metadata.source_package_sha256, example]),
);
assert.equal(bySource.size, 2);
const imported = [];
for (const variant of payload.variants) {
  const { runs, ...definition } = variant;
  const experiment = (
    await request(`/v1/datasets/${dataset.dataset_id}/experiments`, {
      ...definition,
      version_id: dataset.version_id,
      repetitions: 1,
    })
  ).data;
  const runIds = [];
  for (const row of runs) {
    const example = bySource.get(payload.dataset.metadata[row.case_index].source_package_sha256);
    assert.deepEqual(example.input, payload.dataset.inputs[row.case_index]);
    const run = (
      await request(`/v1/experiments/${experiment.id}/runs`, {
        ...row.request,
        dataset_example_id: example.id,
      })
    ).data;
    runIds.push(run.id);
    for (const evaluation of row.evaluations) {
      assert.equal(evaluation.annotator_kind, 'CODE');
      await request('/v1/experiment_evaluations', { ...evaluation, experiment_run_id: run.id });
    }
  }
  imported.push({ experiment, runIds });
}
await mkdir(`${root}artifacts`, { recursive: true });
await writeFile(
  `${root}artifacts/m5-phoenix-comparison-state.json`,
  JSON.stringify({ dataset, datasetName, imported }, null, 2),
);
const nativeRuns = await Promise.all(
  imported.map(({ experiment }) => request(`/v1/experiments/${experiment.id}/runs`)),
);
for (const [index, response] of nativeRuns.entries()) {
  assert.equal(response.data.length, 2);
  for (const expected of payload.variants[index].runs) {
    const observed = response.data.find((run) => run.trace_id === expected.request.trace_id);
    assert(observed, 'missing_historical_run');
    assert.deepEqual(observed.output, expected.request.output);
    assert.equal(observed.error, expected.request.error);
  }
}
const readExports = () =>
  Promise.all(imported.map(({ experiment }) => request(`/v1/experiments/${experiment.id}/json`)));
const nativeBefore = await readExports();
for (const [index, rows] of nativeBefore.entries()) {
  for (const expected of payload.variants[index].runs) {
    const observed = rows.find((row) => row.trace_id === expected.request.trace_id);
    assert(observed, 'missing_exported_run');
    assert.deepEqual(observed.output, expected.request.output);
    assert.equal(observed.annotations.length, expected.evaluations.length);
    for (const evaluation of expected.evaluations) {
      const annotation = observed.annotations.find((item) => item.name === evaluation.name);
      assert(annotation, 'missing_copied_rule');
      assert.equal(annotation.annotator_kind, 'CODE');
      for (const [key, value] of Object.entries(evaluation.result))
        assert.deepEqual(annotation[key], value);
      assert.deepEqual(annotation.metadata, evaluation.metadata);
      assert.equal(Date.parse(annotation.start_time), Date.parse(evaluation.start_time));
      assert.equal(Date.parse(annotation.end_time), Date.parse(evaluation.end_time));
    }
  }
}
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? '/usr/bin/chromium',
});
let page;
try {
  page = await browser.newPage({ viewport: { width: 1800, height: 1100 } });
  page.setDefaultTimeout(15_000);
  const mutations = [];
  page.on('request', (request) => {
    if (request.url() !== `${base}/graphql` || request.method() !== 'POST') return;
    const body = request.postDataJSON();
    if (body?.query && /^\s*mutation\b/.test(body.query))
      mutations.push(body.operationName ?? 'mutation');
  });
  await page.goto(base);
  assert.equal(await page.evaluate(() => window.Config.platformVersion), '20.23.0');
  assert.equal(await page.evaluate(() => window.Config.agentAssistantDisabled), true);
  await page.getByRole('link', { name: /Datasets & Experiments/ }).click();
  await page.getByRole('link', { name: datasetName, exact: true }).click();
  await check(page.locator('body')).toContainText('history-A');
  await check(page.locator('body')).toContainText('history-B');
  await check(page.getByText('No cost data', { exact: true })).toBeVisible();
  await page.screenshot({
    path: `${root}artifacts/m5-phoenix-experiments-list.png`,
    fullPage: true,
  });
  for (const name of ['history-A', 'history-B']) {
    const box = page
      .getByRole('row')
      .filter({ has: page.getByRole('link', { name, exact: true }) })
      .getByRole('checkbox');
    // Phoenix's styled checkbox covers the native input; use its normal keyboard interaction.
    await box.focus();
    await box.press('Space');
    await check(box).toBeChecked();
  }
  await page.getByRole('button', { name: 'Compare', exact: true }).click();
  await check(page).toHaveURL(/\/compare\?/);
  assert.deepEqual(
    new URL(page.url()).searchParams.getAll('experimentId'),
    imported.map(({ experiment }) => experiment.id),
  );
  await check(page.getByRole('columnheader', { name: /history-A/ })).toBeVisible();
  await check(page.getByRole('columnheader', { name: /history-B/ })).toBeVisible();
  const compareUrl = page.url();
  const caseRow = (index) =>
    page.getByRole('row').filter({
      has: page.getByRole('button', {
        name: `Copy example ID ${bySource.get(payload.dataset.metadata[index].source_package_sha256).id}`,
        exact: true,
      }),
    });
  const timeout = caseRow(0),
    document = caseRow(1);
  const cell = (row, variant) => row.getByRole('cell').nth(variant + 2);
  await check(cell(timeout, 0)).toContainText('failed');
  for (const [row, tokens] of [
    [timeout, ['374', '250']],
    [document, ['2,491', '1,948']],
  ])
    for (const [variant, total] of tokens.entries())
      await check(
        cell(row, variant).getByRole('button', { name: total, exact: true }),
      ).toBeVisible();
  for (const [variant, verdicts] of [
    [0, ['fail', 'fail', 'pass']],
    [1, ['pass', 'pass', 'fail']],
  ]) {
    for (const [index, name] of [
      'required_documents_returned',
      'required_documents_read',
      'citation_sources_read',
    ].entries()) {
      const verdict = verdicts[index];
      await check(
        cell(document, variant).getByRole('button', {
          name: `source/document-evidence:1/${name} ${verdict} ${verdict === 'pass' ? '1.00' : '0.00'}`,
          exact: true,
        }),
      ).toBeVisible();
    }
  }
  await page.screenshot({
    path: `${root}artifacts/m5-phoenix-native-comparison.png`,
    fullPage: true,
  });
  await cell(document, 1).getByRole('button', { name: 'View run trace', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: /Experiment Run Trace/ });
  const sourceModel = payload.variants[1].runs[1].request.output.source_view.spans
    .filter((span) => span.kind === 'model')
    .at(-1);
  const expectedModelId = createHash('sha256')
    .update(`m5:${payload.dataset.metadata[1].source_package_sha256}:span:${sourceModel.span_id}`)
    .digest('hex')
    .slice(0, 16);
  await dialog.getByRole('button', { name: /llm model #3/ }).click();
  await check(
    dialog.getByRole('button', { name: `Copy Span ID ${expectedModelId}`, exact: true }),
  ).toBeVisible();
  await check(dialog.getByRole('tabpanel', { name: 'Info', exact: true })).toContainText(
    'hrelease-v2',
  );
  await page.screenshot({
    path: `${root}artifacts/m5-phoenix-experiment-document-trace.png`,
    fullPage: true,
  });
  await page.goto(compareUrl);
  await cell(caseRow(0), 0).getByRole('button', { name: 'View run trace', exact: true }).click();
  await dialog.getByRole('button', { name: /tool search_documents #1 attempt 1/ }).click();
  await check(dialog.getByRole('tabpanel', { name: 'Info', exact: true })).toContainText(
    'TOOL_TIMEOUT',
  );
  await page.screenshot({
    path: `${root}artifacts/m5-phoenix-experiment-timeout-trace.png`,
    fullPage: true,
  });
  assert.equal(hash(await spans()), hash(originalSpans));
  assert.equal(hash(await readExports()), hash(nativeBefore));
  assert.deepEqual(
    await Promise.all(files.map((file) => readFile(`${root}examples/m4/${file}`, 'utf8'))),
    sources,
  );
  assert.deepEqual(mutations, []);
  const proof = {
    schema_version: 'm5-phoenix-comparison-1',
    checked_at: new Date().toISOString(),
    passed: true,
    observer_kind: 'assistant_tool_check',
    counts_as_user_session: false,
    user_completion_rate: null,
    user_elapsed_seconds: null,
    source_commit: execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: root,
      encoding: 'utf8',
    }).trim(),
    tool: 'Phoenix',
    tool_version: '20.23.0',
    browser: browser.version(),
    agent_assistant_disabled: true,
    observation_kind: 'imported_historical_record',
    source_package_sha256: payload.dataset.metadata.map((item) => item.source_package_sha256),
    dataset_examples: 2,
    native_experiments: 2,
    native_experiment_runs: 4,
    copied_code_annotations: payload.variants.flatMap((item) =>
      item.runs.flatMap((run) => run.evaluations),
    ).length,
    source_spans: 18,
    source_model_spans: 7,
    source_tokens: 5063,
    source_views_rules_and_provenance_reexport_verified: true,
    source_trace_snapshot_unchanged: true,
    native_comparison_grid_and_rule_differences_verified: true,
    original_timeout_and_citation_failure_inspected_in_linked_traces: true,
    original_unknown_costs_preserved: true,
    experiment_cost_display: 'No cost data',
    setup_post_requests: requests.length,
    graphql_mutations_during_navigation: mutations.length,
    before_sha256: hash(nativeBefore),
    after_sha256: hash(await readExports()),
    new_provider_requests: 0,
    human_reviews_created: 0,
    limitations: [
      'Historical source results and CODE rule annotations were copied; no Agent or evaluator was executed anew.',
      'Each case has one A/B pair, no gold answer or human semantic review; aggregate percentages do not establish a strategy or performance advantage.',
      'Run timing comes from original records. Annotation timestamps are copied point observations; annotation duration and user task times remain unknown.',
      'Linked trace details show $0 while the native experiment overview shows No cost data; neither verifies an actual bill.',
      'Checkpoint execution/fork, Studio and real-user feedback remain outside this observation.',
    ],
  };
  await writeFile(output, `${JSON.stringify(proof, null, 2)}\n`);
  console.log(JSON.stringify({ passed: true, historical_runs: 4, copied_rules: 6, output }));
} catch (error) {
  await writeFile(`${root}artifacts/m5-phoenix-comparison-failure.txt`, String(error));
  await page
    ?.screenshot({ path: `${root}artifacts/m5-phoenix-comparison-failure.png`, fullPage: true })
    .catch(() => {});
  console.log(JSON.stringify({ passed: false, error_code: error.name }));
  process.exitCode = 1;
} finally {
  await browser.close();
}
