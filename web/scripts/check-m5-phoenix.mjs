// Local tool observation for M5. This is never a real-user session or an Agent adapter.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = process.argv[2] ?? 'http://127.0.0.1:16007';
const payloadPath = process.argv[3] ?? `${root}artifacts/m5-phoenix-final.json`;
const output = process.argv[4] ?? `${root}artifacts/m5-phoenix-observation.json`;
const payload = JSON.parse(await readFile(payloadPath, 'utf8'));
const expected = payload.resourceSpans[0].scopeSpans[0].spans;
const sorted = (value) =>
  Array.isArray(value)
    ? value.map(sorted)
    : value && typeof value === 'object'
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, sorted(value[key])]),
        )
      : value;
const hash = (value) =>
  createHash('sha256')
    .update(JSON.stringify(sorted(value)))
    .digest('hex');
const attributes = (span) =>
  Object.fromEntries(
    span.attributes.map(({ key, value }) => [
      key,
      'intValue' in value ? Number(value.intValue) : Object.values(value)[0],
    ]),
  );
const get = async (path) => {
  const response = await fetch(`${base}${path}`);
  assert(response.ok, `phoenix_read_failed:${response.status}`);
  return response.json();
};
const readSpans = async () => (await get('/v1/projects/agenttinker-m5/spans?limit=1000')).data;
const before = await readSpans();
assert.equal(before.length, expected.length);
assert.equal(before.length, 22);
const indexed = new Map(before.map((span) => [span.context.span_id, span]));
const sourcePackages = [
  ...new Set(expected.map((span) => attributes(span)['agenttinker.package_sha256'])),
];
const files = ['tool-timeout.json', 'document-missing-v2.json'];
const sourceBefore = await Promise.all(
  files.map((file) => readFile(`${root}examples/m4/${file}`, 'utf8')),
);
assert.deepEqual(sourcePackages.sort(), sourceBefore.map((data) => hash(JSON.parse(data))).sort());
for (const span of expected) {
  const observed = indexed.get(span.spanId);
  assert(observed, 'missing_source_span');
  assert.equal(observed.context.trace_id, span.traceId);
  assert.equal(observed.parent_id, span.parentSpanId ?? null);
  assert.equal(observed.status_code, ['UNSET', 'OK', 'ERROR'][span.status.code]);
  for (const [key, value] of Object.entries(attributes(span))) {
    assert.deepEqual(
      key === 'openinference.span.kind' ? observed.span_kind : observed.attributes[key],
      value,
      key,
    );
  }
}
const sources = before.filter((span) => !span.attributes['agenttinker.derived_container']);
const models = sources.filter((span) => span.span_kind === 'LLM');
assert.equal(sources.length, 18);
assert.equal(models.length, 7);
assert.equal(
  models.reduce((count, span) => count + span.attributes['llm.token_count.total'], 0),
  5063,
);
for (const span of sources) {
  const cost = JSON.parse(span.attributes['agenttinker.source_cost']);
  assert.equal(cost.kind, 'unknown');
  assert.equal(cost.amount, null);
}
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? '/usr/bin/chromium',
  headless: true,
});
const mutations = [];
let displayedCost;
let toolVersion;
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  page.on('request', (request) => {
    if (!request.url().startsWith(base) || request.method() !== 'POST') return;
    const body = request.postDataJSON();
    if (body?.query && /^\s*mutation\b/.test(body.query))
      mutations.push(body.operationName ?? 'mutation');
  });
  await page.goto(base);
  toolVersion = await page.evaluate(() => window.Config.platformVersion);
  assert.equal(toolVersion, '20.23.0');
  assert.equal(await page.evaluate(() => window.Config.agentAssistantDisabled), true);
  await page.getByRole('link', { name: /agenttinker-m5/ }).click();
  const documentB = 'document-react:2 / run_b4955d8c41b54d18a6ad67c6a25cad20';
  await expect(page.getByRole('link', { name: documentB, exact: true })).toBeVisible();
  const projectUrl = page.url();
  await expect(page.getByRole('button', { name: '$0', exact: true }).first()).toBeVisible();
  displayedCost = '$0';
  await mkdir(`${root}artifacts`, { recursive: true });
  await page.screenshot({ path: `${root}artifacts/m5-phoenix-project.png`, fullPage: true });
  await page.getByRole('link', { name: documentB, exact: true }).click();
  await expect(page.getByText('model #3', { exact: true })).toBeVisible();
  await page.getByText('model #3', { exact: true }).click();
  await expect(page.locator('body')).toContainText('hrelease-v2');
  await page.screenshot({ path: `${root}artifacts/m5-phoenix-document-b.png`, fullPage: true });
  await page.goto(projectUrl);
  await page
    .getByRole('link', {
      name: 'serial-checkpoint:2 / run_39fe9ed03b7f419cba42fdcb5a6087e6',
      exact: true,
    })
    .click();
  await page.getByText('search_documents #1 attempt 1', { exact: true }).click();
  await expect(page.locator('body')).toContainText('TOOL_TIMEOUT');
  await page.screenshot({ path: `${root}artifacts/m5-phoenix-timeout-a.png`, fullPage: true });
  assert.deepEqual(mutations, []);
  const after = await readSpans();
  assert.equal(hash(after), hash(before));
  assert.deepEqual(
    await Promise.all(files.map((file) => readFile(`${root}examples/m4/${file}`, 'utf8'))),
    sourceBefore,
  );
  const proof = {
    schema_version: 'm5-tool-observation-1',
    checked_at: new Date().toISOString(),
    passed: true,
    observer_kind: 'assistant_tool_check',
    counts_as_user_session: false,
    user_completion_rate: null,
    user_elapsed_seconds: null,
    tool: 'Phoenix',
    tool_version: toolVersion,
    agent_assistant_disabled: true,
    browser: browser.version(),
    source_package_sha256: sourcePackages,
    source_run_count: 4,
    derived_container_spans: 4,
    source_spans: 18,
    source_model_spans: 7,
    source_tokens: 5063,
    inherited_prefix_not_duplicated: true,
    source_attributes_and_parent_mapping_verified: true,
    original_unknown_costs_preserved_in_attributes: true,
    original_citation_failure_preserved: true,
    timeout_error_and_document_answer_inspected_in_ui: true,
    collector_displayed_cost: displayedCost,
    collector_displayed_cost_is_actual_bill: false,
    graphql_mutations_during_navigation: mutations.length,
    before_sha256: hash(before),
    after_sha256: hash(after),
    limitations: [
      'Local historical observation only; no execution/fork or human task timing was tested.',
      'The four container spans and mapped IDs are derived. Source IDs, lineage, usage and opinions remain attributes.',
      'OTLP links were sent; the list API does not expose them. Source prefix IDs are preserved explicitly.',
      'Source evaluations are attributes, not new Phoenix evaluations or human reviews.',
      'The UI displayed $0 while the source amount remained unknown; no bill was verified.',
      'Studio and real-user sessions remain pending; this is not a product ranking.',
    ],
  };
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, `${JSON.stringify(proof, null, 2)}\n`);
  console.log(JSON.stringify({ passed: true, source_spans: sources.length, output }));
} finally {
  await browser.close();
}
