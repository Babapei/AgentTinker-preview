// Hosted Studio controls over local synthetic nodes; never a user-study session.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = (process.argv[2] ?? 'http://127.0.0.1:12025').replace(/\/$/, '');
const endpoint = new URL(base);
assert.equal(endpoint.protocol, 'http:');
assert.equal(endpoint.hostname, '127.0.0.1', 'local_comparison_only');
assert.equal(endpoint.pathname, '/');
assert.equal(endpoint.username + endpoint.password + endpoint.search + endpoint.hash, '');
const directory = resolve(process.argv[3] ?? `${root}artifacts/m5-studio-local`);
const output = process.argv[4] ?? `${root}artifacts/m5-studio-browser.json`;
const check = expect.configure({ timeout: 20_000 });
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

// These helper requests only inspect state; all execution/state writes use UI controls.
async function inspect(path, body) {
  if (body) assert(/\/assistants\/search$|\/history$/.test(path), 'read_helper_only');
  const response = await fetch(`${base}${path}`, {
    signal: AbortSignal.timeout(20_000),
    method: body ? 'POST' : 'GET',
    ...(body
      ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : {}),
  });
  assert(response.ok, `studio_api_read_failed:${response.status}`);
  return response.json();
}
const historyOf = (thread) => inspect(`/threads/${thread}/history`, { limit: 100 });
const stateOf = (thread, checkpoint) =>
  inspect(`/threads/${thread}/state${checkpoint ? `/${checkpoint.checkpoint_id}` : ''}`);
const studioURL = (assistant, thread) => {
  const url = new URL('https://smith.langchain.com/studio/');
  url.searchParams.set('baseUrl', base);
  url.searchParams.set('assistantId', assistant);
  if (thread) url.searchParams.set('threadId', thread);
  return url.href;
};
const cases = [
  ['timeout', 'tool-timeout.json', 'tool_retry_limit', 1],
  ['document', 'document-missing-v2.json', 'top_k', 3],
];
const sources = await Promise.all(
  cases.map(([, file]) => readFile(`${root}examples/m4/${file}`, 'utf8')),
);
const info = await inspect('/info');
assert.equal(info.flags.langsmith, false, 'comparison_requires_tracing_disabled');
await mkdir(`${root}artifacts`, { recursive: true });
const proxy = process.env.HTTPS_PROXY ?? process.env.HTTP_PROXY;
let browser,
  page,
  activeWrites = [],
  stage = 'launch';
const results = [],
  privateStates = [];
try {
  browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? '/usr/bin/chromium',
    ...(proxy ? { proxy: { server: proxy, bypass: '127.0.0.1,localhost' } } : {}),
  });
  for (const [index, [name, , field, value]] of cases.entries()) {
    stage = `${name}:prepare`;
    const state = JSON.parse(await readFile(`${directory}/input-${name}.json`, 'utf8'));
    state.run_id = `studio_ui_${randomUUID()}`;
    assert.equal(state.run_config.provider, 'synthetic');
    const source = Object.values(JSON.parse(sources[index]).files).find(
      (file) => file.view?.run && !file.view.run.parent_run_id,
    ).view.run.config;
    for (const key of ['agent', 'task', 'fixture_hash', 'prompt_version', 'tool_policy'])
      assert.deepEqual(state.run_config[key], source[key]);
    const [assistant] = await inspect('/assistants/search', { graph_id: name });
    assert(assistant, 'missing_comparison_graph');
    const context = await browser.newContext({ viewport: { width: 1700, height: 1100 } });
    page = await context.newPage();
    page.setDefaultTimeout(20_000);
    const writes = [],
      remoteFailures = [],
      pageErrors = [];
    activeWrites = writes;
    page.on('request', (request) => {
      if (!request.url().startsWith(`${base}/`) || request.method() !== 'POST') return;
      const path = new URL(request.url()).pathname;
      if (/\/(search|history)$/.test(path)) return;
      writes.push({ path, body: request.postDataJSON() });
    });
    page.on('response', (response) => {
      const url = new URL(response.url());
      if (url.hostname.endsWith('smith.langchain.com') && response.status() >= 400)
        remoteFailures.push({ path: url.pathname, status: response.status() });
    });
    page.on('pageerror', (error) => pageErrors.push(error.name));
    stage = `${name}:submit-A`;
    await page.goto(studioURL(assistant.assistant_id), {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    });
    await page.getByTestId('graph-assistant-select-trigger').click();
    await page.getByRole('dialog').getByRole('button', { name, exact: true }).click();
    await check(page.getByTestId('graph-assistant-select-trigger')).toHaveText(name);
    await check(
      page.getByRole('group', { name: 'Edge from model to tool', exact: true }),
    ).toBeAttached();
    await page.getByRole('button', { name: 'View Raw', exact: true }).click();
    await page.locator('[contenteditable=true]').fill(JSON.stringify(state, null, 2));
    await check(page.getByTestId('graph-assistant-select-trigger')).toHaveText(name);
    await page.getByRole('button', { name: 'Submit', exact: true }).click();
    await check.poll(() => writes.some((item) => /\/runs\/stream$/.test(item.path))).toBe(true);
    const executionA = writes.find((item) => /\/runs\/stream$/.test(item.path));
    assert.equal(executionA.body.assistant_id, assistant.assistant_id);
    const thread = executionA.path.split('/')[2];
    await check
      .poll(async () => (await inspect(`/threads/${thread}`)).status)
      .toBe(name === 'timeout' ? 'error' : 'idle');
    const baseline = await stateOf(thread);
    const oldHistory = await historyOf(thread);
    const before = await Promise.all(oldHistory.map((item) => stateOf(thread, item.checkpoint)));
    assert.equal(before.length, name === 'timeout' ? 3 : 8);
    const boundaries = before.filter(
      (item) => item.next.join() === 'tool' && item.values.tool_span_id === null,
    );
    assert.equal(boundaries.length, 1);
    const boundary = boundaries[0];
    assert.deepEqual(executionA.body.input, state);
    if (name === 'timeout')
      assert(baseline.tasks.some((task) => task.error?.includes('TOOL_TIMEOUT')));

    // Reload the saved thread through the normal URL to check persisted history.
    stage = `${name}:inspect-A`;
    await page.goto(studioURL(assistant.assistant_id, thread), {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    });
    const log = page.getByTestId('thread-log');
    const firstModelHeader = log
      .getByText('model', { exact: true })
      .first()
      .locator('..')
      .locator('..');
    await firstModelHeader.getByRole('button', { name: 'Expand node', exact: true }).click();
    if (name === 'timeout') await check(log).toContainText('TOOL_TIMEOUT');
    await page.screenshot({ path: `${root}artifacts/m5-studio-${name}-A.png` });
    await firstModelHeader.hover();
    await firstModelHeader.getByRole('button', { name: 'Edit node state', exact: true }).click();
    const rawToggle = log.getByRole('button', { name: 'View Raw', exact: true });
    const toggledRawEditor = (await rawToggle.count()) > 0;
    if (toggledRawEditor) await rawToggle.click();
    const config = structuredClone(state.run_config);
    config.tool_policy[field] = value;
    if (name === 'document') config.variant = { id: `document-top${value}`, version: '1' };
    const owner = `studio_ui_${randomUUID()}`;
    // Retain the exact first model output. Only ownership/configuration is changed.
    const patch = {
      messages: boundary.values.messages,
      tool_call: boundary.values.tool_call,
      model_span_id: boundary.values.model_span_id,
      ...(name === 'document'
        ? {
            pending_calls: boundary.values.pending_calls,
            model_calls: boundary.values.model_calls,
            span_ids: boundary.values.span_ids,
          }
        : {}),
      run_id: owner,
      run_config: config,
    };
    stage = `${name}:fork-B`;
    await log.locator('[contenteditable=true]').fill(JSON.stringify(patch, null, 2));
    await log.getByRole('button', { name: 'Fork', exact: true }).click();
    await check
      .poll(() => writes.filter((item) => /\/runs\/stream$/.test(item.path)).length)
      .toBe(2);
    await check.poll(async () => (await inspect(`/threads/${thread}`)).status).toBe('idle');
    const candidate = await stateOf(thread);
    const newHistory = await historyOf(thread);
    const edits = writes.filter((item) => item.path.endsWith('/state'));
    assert.equal(edits.length, 1);
    const edit = edits[0].body;
    // Current Studio copies the node's input checkpoint and substitutes its
    // output write. Older clients update the output checkpoint as that node.
    const sourceCheckpoint =
      edit.as_node === '__copy__' ? boundary.parent_checkpoint : boundary.checkpoint;
    assert.equal(
      edit.checkpoint?.checkpoint_id ?? edit.checkpoint_id,
      sourceCheckpoint.checkpoint_id,
    );
    if (edit.as_node === '__copy__') assert.deepEqual(edit.values, [[patch, 'model']]);
    else {
      assert.equal(edit.as_node, 'model');
      assert.deepEqual(edit.values, patch);
    }
    assert.equal(candidate.values.run_id, owner);
    assert.deepEqual(candidate.values.run_config, config);
    assert.deepEqual(candidate.next, []);
    assert.deepEqual(candidate.values.messages.slice(0, 3), boundary.values.messages);
    const oldModels = new Set(before.map((item) => item.values.model_span_id).filter(Boolean));
    const models = new Set(
      newHistory
        .filter((item) => item.values.run_id === owner)
        .map((item) => item.values.model_span_id)
        .filter((id) => id && !oldModels.has(id)),
    );
    assert.equal(models.size, name === 'timeout' ? 1 : 2);
    const oldTools = new Set(before.map((item) => item.values.tool_span_id).filter(Boolean));
    const tools = new Set(
      newHistory
        .filter((item) => item.values.run_id === owner)
        .map((item) => item.values.tool_span_id)
        .filter((id) => id && !oldTools.has(id)),
    );
    assert.equal(tools.size, name === 'timeout' ? 1 : 4);
    const after = await Promise.all(oldHistory.map((item) => stateOf(thread, item.checkpoint)));
    assert.deepEqual(after, before);

    stage = `${name}:inspect-B`;
    await check(log).toContainText('Fork 2 of 2');
    await page.screenshot({ path: `${root}artifacts/m5-studio-${name}-B.png` });
    const executions = writes.filter((item) => /\/runs\/stream$/.test(item.path));
    const branchCheckpoint = executions[1].body.checkpoint;
    assert(branchCheckpoint?.checkpoint_id, 'UI_must_resume_explicit_branch_checkpoint');
    const branchState = await stateOf(thread, branchCheckpoint);
    assert.equal(branchState.values.model_span_id, boundary.values.model_span_id);
    assert.deepEqual(branchState.values.run_config, config);
    assert.deepEqual(branchState.next, ['tool']);
    results.push({
      case: name,
      source_package_sha256: hash(JSON.parse(sources[index])),
      agent: state.run_config.agent,
      fixture_hash: state.run_config.fixture_hash,
      thread_id: thread,
      baseline_checkpoint: baseline.checkpoint,
      branch_point: boundary.checkpoint,
      ui_state_edit: {
        as_node: edit.as_node,
        applied_node: 'model',
        source_checkpoint: sourceCheckpoint,
      },
      candidate_checkpoint: candidate.checkpoint,
      execution_policy_patch: { [field]: value },
      a_model_steps: oldModels.size,
      b_new_model_steps: models.size,
      b_new_successful_tool_graph_steps: tools.size,
      old_checkpoints_checked: before.length,
      before_sha256: hash(before),
      after_sha256: hash(after),
      ui_actions: [
        'Select graph',
        'View Raw',
        'Submit',
        'Reload saved thread',
        'Expand model',
        'Edit node state',
        toggledRawEditor ? 'View Raw' : 'Raw state editor already selected',
        'Fork',
      ],
      ui_local_writes: writes.map((item) => item.path.replace(thread, '{thread}')),
      execution_stream_modes: executions.map((item) => item.body.stream_mode),
      remote_http_failures: [
        ...new Map(remoteFailures.map((item) => [JSON.stringify(item), item])).values(),
      ],
      page_error_names: [...new Set(pageErrors)],
    });
    privateStates.push({ name, state, before, candidate, branchState, writes });
    await context.close();
    page = undefined;
    console.log(
      JSON.stringify({ case: name, passed: true, old_checkpoints_checked: before.length }),
    );
  }
  assert.deepEqual(
    await Promise.all(cases.map(([, file]) => readFile(`${root}examples/m4/${file}`, 'utf8'))),
    sources,
  );
  const proof = {
    schema_version: 'm5-studio-browser-1',
    checked_at: new Date().toISOString(),
    source_commit: execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: root,
      encoding: 'utf8',
    }).trim(),
    passed: true,
    observer_kind: 'scripted_hosted_studio_ui',
    counts_as_user_session: false,
    user_completion_rate: null,
    user_elapsed_seconds: null,
    mode: 'synthetic',
    tool: 'LangSmith Studio with local Agent Server',
    browser: browser.version(),
    api_version: info.version,
    langgraph_version: info.langgraph_py_version,
    langsmith_tracing: false,
    cases: results,
    new_provider_requests: 0,
    human_reviews_created: 0,
    limitations: [
      'Fresh guest browser, no account login or LangSmith tracing/evaluator configuration.',
      'Execution and state writes used visible Studio controls; local API reads verify persisted checkpoints.',
      'Generic JSON state edits require the bridge run_id/config convention; they are not platform ForkRequest validation or Intervention records.',
      'Internal tool retries are not separate Studio graph nodes; completed Span observations are checked separately by the API control.',
      'No user timing, product ranking, cancellation or restart equivalence is claimed.',
      'Synthetic success does not replace the original live citation failure or unknown bills.',
    ],
  };
  await writeFile(
    output.replace(/\.json$/, '.state.json'),
    JSON.stringify(privateStates, null, 2) + '\n',
  );
  await writeFile(output, JSON.stringify(proof, null, 2) + '\n');
} catch (error) {
  if (page)
    await page
      .screenshot({ path: `${root}artifacts/m5-studio-browser-failure.png` })
      .catch(() => {});
  await writeFile(
    `${root}artifacts/m5-studio-browser-failure.json`,
    JSON.stringify({
      stage,
      error_code: error.name,
      local_script_lines: [...(error.stack ?? '').matchAll(/check-m5-studio\.mjs:(\d+)/g)].map(
        (match) => Number(match[1]),
      ),
      local_writes: activeWrites,
    }),
  );
  console.error(JSON.stringify({ passed: false, stage, error_code: error.name }));
  process.exitCode = 1;
} finally {
  await browser?.close();
}
