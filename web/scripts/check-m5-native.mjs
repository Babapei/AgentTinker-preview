// Scripted M5 walkthrough against the actual local CLI and production bundle, never user research.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, open, readFile, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const root = fileURLToPath(new URL('../../', import.meta.url));
const output = process.argv[2] ?? `${root}artifacts/m5-native-walkthrough.json`;
const check = expect.configure({ timeout: 15_000 });
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
const sourceFiles = ['tool-timeout.json', 'document-missing-v2.json'];
const sources = await Promise.all(
  sourceFiles.map((name) => readFile(`${root}examples/m4/${name}`, 'utf8')),
);
await mkdir(`${root}artifacts`, { recursive: true });
const directory = await mkdtemp(`${root}artifacts/m5-native-`);
const log = await open(`${directory}/server.log`, 'w');
const port = await new Promise((resolve, reject) => {
  const listener = createServer();
  listener.on('error', reject).listen(0, '127.0.0.1', () => {
    const port = listener.address().port;
    listener.close((error) => (error ? reject(error) : resolve(port)));
  });
});
const base = `http://127.0.0.1:${port}`;
const environment = { ...process.env };
for (const name of ['DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL', 'OPENAI_API_KEY', 'OPENAI_MODEL'])
  delete environment[name];
const server = spawn(
  'uv',
  [
    'run',
    'agenttinker-server',
    '--database',
    `${directory}/runs.sqlite`,
    '--web-dist',
    `${root}web/dist`,
    '--port',
    String(port),
  ],
  {
    cwd: root,
    env: environment,
    detached: true,
    stdio: ['ignore', log.fd, log.fd],
  },
);
let exited = false;
server.on('exit', () => {
  exited = true;
});
server.on('error', () => {
  exited = true;
});
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const json = async (path) => {
  const response = await fetch(`${base}${path}`);
  assert(response.ok, 'native_api_read_failed');
  return response.json();
};
const view = (id) => json(`/api/v1/runs/${id}`);
let browser,
  page,
  stage = 'start';
try {
  await check
    .poll(
      async () => {
        if (exited) throw new Error('native_cli_exited');
        try {
          return (await json('/api/v1/runs')).total;
        } catch {
          return null;
        }
      },
      { timeout: 30_000 },
    )
    .toBe(0);
  browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ?? '/usr/bin/chromium',
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'reduce',
  });
  page = await context.newPage();
  const writes = [],
    playbackRequests = [],
    errors = [];
  let playing = false;
  page.on('pageerror', (error) => errors.push(error.name));
  page.on('request', (request) => {
    if (!request.url().startsWith(`${base}/api/`)) return;
    if (request.method() === 'POST') writes.push(new URL(request.url()).pathname);
    if (playing) playbackRequests.push(new URL(request.url()).pathname);
  });
  const ready = async (id) => {
    if (id) {
      await check(page).toHaveURL(new RegExp(`[?&]run=${id}(?:&|$)`));
      await check(page.locator('.run-header [title]')).toHaveAttribute('title', id);
    }
    await check(page.locator('.record-connection')).toContainText('事件已核对');
  };
  const selected = () => new URL(page.url()).searchParams.get('run');
  async function download() {
    const pending = page.waitForEvent('download');
    await page.getByRole('button', { name: '导出实验包', exact: true }).click();
    return readFile(await (await pending).path());
  }
  async function readPackage(bytes, name) {
    const original = JSON.parse(bytes.toString());
    await page.getByRole('button', { name: '导入文件', exact: true }).click();
    await page
      .getByLabel('JSON 实验包文件')
      .setInputFiles({ name, mimeType: 'application/json', buffer: bytes });
    const response = page.waitForResponse(
      (response) =>
        response.url() === `${base}/api/v1/imports` && response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '导入并打开记录', exact: true }).click();
    const result = await (await response).json();
    await ready(result.root_run_id);
    const source = page.getByLabel('导入来源与原意见');
    await check(source).toContainText('原记录模式');
    const id = selected(),
      before = await view(id);
    assert.equal(before.run.mode, 'imported');
    await check(page.getByRole('button', { name: '检查分支可用性', exact: true })).toHaveCount(0);
    await check(page.getByRole('button', { name: '运行规则评价', exact: true })).toHaveCount(0);
    playing = true;
    try {
      await page.getByRole('button', { name: '回到第一个事件' }).click();
      await page.getByRole('button', { name: /返回最新/ }).click();
    } finally {
      playing = false;
    }
    assert.deepEqual(JSON.parse((await download()).toString()), original);
    assert.equal(hash(await view(id)), hash(before));
    const provenance = await json(`/api/v1/runs/${id}/provenance`);
    assert.equal(provenance.source_package_sha256, hash(original));
    return {
      file: name,
      local_run_id: id,
      source_package_sha256: hash(original),
      source_mode: provenance.source_mode,
      view_unchanged: true,
      reexport_identical: true,
    };
  }
  const pairs = [];
  for (const document of [false, true]) {
    stage = document ? 'native_document_v2' : 'native_timeout';
    const scenario = stage;
    const reference = JSON.parse(sources[document ? 1 : 0]);
    const originalRun = reference.files[`runs/${reference.manifest.root_run_id}.json`].view.run;
    await page.goto(base);
    await page.getByRole('button', { name: '新建实验', exact: true }).click();
    await page
      .getByRole('combobox', { name: '实验场景', exact: true })
      .selectOption(document ? 'document' : 'timeout');
    const form = page.getByLabel(document ? '新建文档实验配置' : '新建实验配置', { exact: true });
    if (!document) await form.getByLabel('任务').fill(originalRun.config.task);
    await form.getByLabel('运行模式').selectOption('synthetic');
    const creation = page.waitForResponse(
      (response) =>
        response.url() ===
          `${base}${document ? '/api/v1/scenarios/document-missing/runs' : '/api/v1/runs'}` &&
        response.request().method() === 'POST',
    );
    await form.getByRole('button', { name: '开始运行实验', exact: true }).click();
    const aId = (await (await creation).json()).run.run_id;
    stage += ':baseline';
    await ready(aId);
    await check
      .poll(async () => (await view(aId)).run.status)
      .toBe(document ? 'succeeded' : 'failed');
    const a = await view(aId);
    assert.equal(a.run.mode, 'synthetic');
    assert.equal(a.run.config.task, originalRun.config.task);
    assert.equal(a.run.config.fixture_hash, originalRun.config.fixture_hash);
    assert.deepEqual(a.run.config.agent, originalRun.config.agent);
    if (document) {
      assert.equal(a.run.config.agent.version, '2');
      await page.getByRole('button', { name: '运行规则评价', exact: true }).click();
      await check(page.getByLabel('文档证据与答案评价')).toContainText('必需正文是否读取：未满足');
    } else {
      assert.equal(
        a.spans.filter((span) => span.kind === 'tool')[0].output.error_code,
        'TOOL_TIMEOUT',
      );
    }
    await page.getByRole('button', { name: '检查分支可用性', exact: true }).click();
    await check(page.getByLabel('只修改一个参数')).toHaveValue(
      document ? 'top_k' : 'tool_retry_limit',
    );
    const branching = page.waitForResponse(
      (response) =>
        response.url() === `${base}/api/v1/runs/${aId}/forks` &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '创建分支并运行', exact: true }).click();
    const bId = (await (await branching).json()).run.run_id;
    stage += ':branch';
    await ready(bId);
    await check.poll(async () => (await view(bId)).run.status).toBe('succeeded');
    await check(page.getByLabel('A/B 运行对比')).toContainText(
      document ? '实际只改一个执行器参数' : 'tool_policy.tool_retry_limit',
    );
    const b = await view(bId);
    assert.notEqual(aId, bId);
    assert.equal(b.run.parent_run_id, aId);
    assert.deepEqual(b.run.inherited_span_ids, [a.spans[0].span_id]);
    assert.deepEqual(b.run.intervention.patch, document ? { top_k: 3 } : { tool_retry_limit: 1 });
    assert.deepEqual(
      b.spans.find((span) => span.kind === 'tool').input.tool_call,
      a.spans.find((span) => span.kind === 'tool').input.tool_call,
    );
    if (document) {
      await page.getByRole('button', { name: '运行规则评价', exact: true }).click();
      await check(page.getByLabel('文档证据与答案评价')).toContainText('必需正文是否读取：通过');
      for (const id of [aId, bId])
        assert.equal((await json(`/api/v1/runs/${id}/reviews`)).total, 0);
      assert.deepEqual(
        (await json(`/api/v1/runs/${bId}/evaluations`)).items[0].checks.map((item) => item.verdict),
        ['pass', 'pass', 'pass'],
      );
      assert.deepEqual((await new AxeBuilder({ page }).include('main').analyze()).violations, []);
      await page.screenshot({ path: `${root}artifacts/m5-native-desktop.png`, fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.deepEqual((await new AxeBuilder({ page }).include('main').analyze()).violations, []);
      await page.screenshot({ path: `${root}artifacts/m5-native-mobile.png`, fullPage: true });
      await page.setViewportSize({ width: 1440, height: 1000 });
    } else {
      assert.deepEqual(
        b.spans.filter((span) => span.kind === 'tool').map((span) => span.status),
        ['failed', 'succeeded'],
      );
      await check(page.getByLabel('A/B 运行对比')).toContainText('重试由执行器负责');
    }
    assert.equal(hash(await view(aId)), hash(a));
    stage += ':roundtrip';
    const imported = await readPackage(await download(), `${scenario}.json`);
    assert.equal(hash(await view(aId)), hash(a));
    assert.equal(hash(await view(bId)), hash(b));
    pairs.push({
      scenario,
      a_run_id: aId,
      b_run_id: bId,
      source_mode: 'synthetic',
      a_status: a.run.status,
      b_status: b.run.status,
      a_model_steps: a.spans.filter((span) => span.kind === 'model').length,
      b_new_model_steps: b.spans.filter((span) => span.kind === 'model').length,
      source_view_sha256: hash(a),
      source_view_unchanged: true,
      task_fixture_and_agent_match_reference: true,
      imported,
    });
  }
  const references = [];
  for (const [index, file] of sourceFiles.entries()) {
    stage = `reference:${file}`;
    const imported = await readPackage(Buffer.from(sources[index]), file);
    assert.equal(imported.source_mode, 'live');
    if (file === 'document-missing-v2.json') {
      const source = page.getByLabel('导入来源与原意见');
      await check(source).toContainText('citation_sources_read：未满足');
      await check(source).toContainText('hrelease-v2');
    }
    references.push(imported);
  }
  stage = 'unconfigured_live';
  const beforeLive = await json('/api/v1/runs?limit=100');
  assert.equal(beforeLive.total, 12);
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await page.getByRole('combobox', { name: '实验场景', exact: true }).selectOption('timeout');
  const form = page.getByLabel('新建实验配置', { exact: true });
  await form.getByLabel('运行模式').selectOption('live');
  const response = page.waitForResponse(
    (response) =>
      response.url() === `${base}/api/v1/runs` && response.request().method() === 'POST',
  );
  await form.getByRole('button', { name: '开始运行实验', exact: true }).click();
  assert.equal((await response).status(), 503);
  await check(page.getByRole('alert')).toContainText('真实模型尚未配置');
  assert.deepEqual(await json('/api/v1/runs?limit=100'), beforeLive);
  assert.deepEqual(playbackRequests, []);
  assert.deepEqual(errors, []);
  assert.equal(writes.filter((path) => path.endsWith('/reviews')).length, 0);
  assert.equal(writes.filter((path) => path === '/api/v1/imports').length, 4);
  assert.deepEqual(
    await Promise.all(sourceFiles.map((file) => readFile(`${root}examples/m4/${file}`, 'utf8'))),
    sources,
  );
  const proof = {
    schema_version: 'm5-native-walkthrough-1',
    checked_at: new Date().toISOString(),
    passed: true,
    observer_kind: 'scripted_production_ui',
    counts_as_user_session: false,
    user_completion_rate: null,
    user_elapsed_seconds: null,
    source_commit: execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: root,
      encoding: 'utf8',
    }).trim(),
    browser: browser.version(),
    actual_cli_and_production_bundle: true,
    provider_configuration_removed: true,
    pairs,
    historical_reference_readings: references,
    final_run_count: beforeLive.total,
    playback_api_requests: playbackRequests.length,
    human_reviews_created: 0,
    unconfigured_live_status: 503,
    new_provider_requests: 0,
    desktop_mobile_axe_checked: true,
    limitations: [
      'Scripted assistant walkthrough, not a real-user session or task timing.',
      'Native executions used the explicitly selected deterministic synthetic driver; historical live records were read only.',
      'Original real citation failure, unknown costs and unreviewed answers remain unchanged.',
      'Studio, real-user sessions and feedback decisions remain pending.',
    ],
  };
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, `${JSON.stringify(proof, null, 2)}\n`);
  console.log(JSON.stringify({ passed: true, runs: beforeLive.total, output }));
} catch (error) {
  await writeFile(
    `${directory}/failure.json`,
    JSON.stringify({ stage, error_code: error.name, message: error.message }, null, 2),
  );
  if (page && !page.isClosed())
    await page.screenshot({ path: `${directory}/failure.png`, fullPage: true }).catch(() => {});
  console.log(JSON.stringify({ passed: false, stage, error_code: error.name }));
  process.exitCode = 1;
} finally {
  await browser?.close();
  if (!exited) {
    process.kill(-server.pid, 'SIGINT');
    for (let index = 0; index < 100 && !exited; index++) await pause(100);
    if (!exited) process.kill(-server.pid, 'SIGTERM');
  }
  await log.close();
}
