// Import checked-in reference files into a fresh, credential-free production-build server.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';
import { chromium, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const root = fileURLToPath(new URL('../../', import.meta.url));
const output = process.argv[2] ?? `${root}artifacts/m4-reference-browser-v2.json`;
const files = ['tool-timeout.json', 'document-missing.json', 'document-missing-v2.json'];
const packages = await Promise.all(
  files.map(async (file) => ({
    file,
    data: JSON.parse(await readFile(`${root}examples/m4/${file}`, 'utf8')),
  })),
);
const port = await new Promise((resolve, reject) => {
  const server = createServer();
  server.on('error', reject).listen(0, '127.0.0.1', () => {
    const value = server.address().port;
    server.close((error) => (error ? reject(error) : resolve(value)));
  });
});
const base = `http://127.0.0.1:${port}`;
const environment = { ...process.env };
for (const name of ['DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL', 'OPENAI_API_KEY', 'OPENAI_MODEL'])
  delete environment[name];
const server = spawn(
  'uv',
  ['run', 'python', 'scripts/serve_reference_check.py', '--port', String(port)],
  { cwd: root, env: environment, stdio: 'ignore' },
);
let exited = false;
server.on('error', () => {
  exited = true;
});
server.on('exit', () => {
  exited = true;
});
const pause = () => new Promise((resolve) => setTimeout(resolve, 100));
const json = async (path) => {
  const response = await fetch(`${base}${path}`);
  assert(response.ok, 'reference_api_response_failed');
  return response.json();
};
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
let browser;
let stage = 'start';
try {
  let ready = false;
  for (let attempt = 0; attempt < 200 && !ready && !exited; attempt++) {
    try {
      ready = (await fetch(`${base}/__reference__/stats`)).ok;
    } catch {
      /* Not ready yet. */
    }
    if (!ready) await pause();
  }
  assert(ready, 'reference_check_server_not_ready');
  stage = 'launch';
  browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const writes = [],
    playbackRequests = [],
    imported = [];
  let observingPlayback = false;
  page.on('request', (request) => {
    if (request.url().includes('/api/') && request.method() !== 'GET')
      writes.push(new URL(request.url()).pathname);
    if (observingPlayback && request.url().includes('/api/')) playbackRequests.push(request.url());
  });
  for (const { file, data } of packages) {
    stage = `import:${file}`;
    await page.goto(base);
    await page.getByRole('button', { name: '导入文件', exact: true }).click();
    await page.getByLabel('JSON 实验包文件').setInputFiles(`${root}examples/m4/${file}`);
    const receipt = page.waitForResponse(
      (response) =>
        response.url() === `${base}/api/v1/imports` && response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '导入并打开记录' }).click();
    const response = await receipt;
    assert.equal(response.status(), 201);
    const result = await response.json();
    assert.equal(result.source_package_sha256, hash(data));
    const before = {};
    const measurements = {};
    for (const link of result.runs) {
      stage = `inspect:${file}:${link.source_run_id}`;
      const view = await json(`/api/v1/runs/${link.local_run_id}`);
      before[link.local_run_id] = view;
      const models = view.spans.filter((span) => span.kind === 'model');
      const tokens = models.map((span) => span.usage.total_tokens);
      assert(tokens.every((value) => value !== null));
      measurements[link.source_run_id] = {
        execution_status: view.run.status,
        new_model_calls: models.length,
        new_total_tokens: tokens.reduce((sum, n) => sum + n, 0),
        rule_verdicts: data.files[`runs/${link.source_run_id}.json`].evaluations.map((evaluation) =>
          Object.fromEntries(evaluation.checks.map((check) => [check.check_id, check.verdict])),
        ),
      };
      await page.goto(`${base}/?run=${link.local_run_id}`);
      await expect(page.locator('.record-connection')).toContainText('事件已核对');
      const source = page.getByLabel('导入来源与原意见');
      await expect(source).toContainText('真实调用（来源声明）');
      await expect(source).toContainText(data.manifest.title);
      await expect(page.locator('.cost-value')).toHaveText('未知');
      await expect(page.getByLabel('本次运行新增调用指标')).toContainText(
        measurements[link.source_run_id].new_total_tokens.toLocaleString('zh-CN'),
      );
      await expect(page.getByLabel('实际运行控制')).toHaveCount(0);
      await expect(page.getByRole('button', { name: '检查分支可用性' })).toHaveCount(0);
      await expect(page.getByLabel('人工复核表单')).toHaveCount(0);
      if (file === 'document-missing.json' && view.run.parent_run_id) {
        await expect(page.locator('.run-header')).toContainText('执行失败');
        await expect(source).toContainText('required_documents_returned：通过');
        await expect(source).toContainText('required_documents_read：未满足');
        await expect(source).toContainText('citation_sources_read：未知');
      }
      if (file === 'document-missing-v2.json' && view.run.parent_run_id) {
        await expect(page.locator('.run-header')).toContainText('执行成功');
        await expect(source).toContainText('required_documents_returned：通过');
        await expect(source).toContainText('required_documents_read：通过');
        await expect(source).toContainText('citation_sources_read：未满足');
        await expect(source).toContainText('hrelease-v2');
      }
      if (view.run.parent_run_id)
        await expect(page.getByLabel('A/B 运行对比')).toContainText('先看配置改动');
      await expect(source.locator('.source-opinions')).toHaveCount(1);
      observingPlayback = true;
      await page.getByRole('button', { name: '回到第一个事件' }).click();
      await expect(source.locator('.source-opinions')).toHaveCount(0);
      await expect(page.locator('.step-row')).toHaveCount(0);
      await page.getByRole('button', { name: /返回最新/ }).click();
      await expect(source.locator('.source-opinions')).toHaveCount(1);
      observingPlayback = false;
      const exported = await json(`/api/v1/runs/${link.local_run_id}/export`);
      assert.deepEqual(exported, data);
    }
    const after = {};
    for (const id of Object.keys(before)) after[id] = await json(`/api/v1/runs/${id}`);
    assert.deepEqual(before, after);
    imported.push({
      file,
      package_sha256: hash(data),
      import_id: result.import_id,
      root_run_id: result.root_run_id,
      measurements,
      before_sha256: hash(before),
      after_sha256: hash(after),
      record_playback_verified: true,
      unknown_costs_preserved: true,
    });
    if (file.startsWith('document-missing')) {
      stage = 'accessibility';
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`${base}/?run=${result.root_run_id}`);
      const source = page.getByLabel('导入来源与原意见');
      await expect(source).toContainText('原规则评价 · 1 份');
      await expect(source).toContainText('原人工意见 · 0 份');
      assert.deepEqual((await new AxeBuilder({ page }).include('main').analyze()).violations, []);
      await page.screenshot({
        path: `${root}artifacts/m4-real-reference-${file.slice(0, -5)}-desktop.png`,
        fullPage: true,
      });
      await page.setViewportSize({ width: 390, height: 844 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.deepEqual((await new AxeBuilder({ page }).include('main').analyze()).violations, []);
      await page.screenshot({
        path: `${root}artifacts/m4-real-reference-${file.slice(0, -5)}-mobile.png`,
        fullPage: true,
      });
    }
  }
  assert.deepEqual(playbackRequests, []);
  assert.deepEqual(
    writes,
    files.map(() => '/api/v1/imports'),
  );
  const runCount = imported.reduce(
    (count, reference) => count + Object.keys(reference.measurements).length,
    0,
  );
  stage = 'unconfigured_live';
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await page.getByRole('combobox', { name: '实验场景', exact: true }).selectOption('document');
  const composer = page.getByLabel('新建文档实验配置');
  await composer.getByLabel('运行模式').selectOption('live');
  const rejected = page.waitForResponse(
    (response) =>
      response.url().endsWith('/scenarios/document-missing/runs') &&
      response.request().method() === 'POST',
  );
  await composer.getByRole('button', { name: '开始运行实验', exact: true }).click();
  assert.equal((await rejected).status(), 503);
  await expect(composer.getByRole('alert')).toContainText('真实模型尚未配置');
  assert.equal((await json('/__reference__/stats')).model_constructions, 0);
  assert.equal((await json('/api/v1/runs')).total, runCount);
  const proof = {
    schema_version: 'm4-reference-browser-1',
    checked_at: new Date().toISOString(),
    passed: true,
    browser: browser.version(),
    production_build: true,
    provider_credentials_removed: true,
    model_constructions: 0,
    import_posts: packages.length,
    playback_api_requests: 0,
    unconfigured_live_status: 503,
    preserved_run_count: runCount,
    references: imported,
    limitations: [
      'Imported source claims remain unverified; this check proves reading and playback only.',
      'No new provider calls or human judgements were made.',
    ],
  };
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify(proof, null, 2) + '\n');
  process.stdout.write(
    JSON.stringify({ passed: true, output, references: imported.length, model_constructions: 0 }) +
      '\n',
  );
} catch (error) {
  process.stderr.write(
    JSON.stringify({
      passed: false,
      error_code: error?.name ?? 'Error',
      stage,
      detail: error.message?.slice(0, 700),
    }) + '\n',
  );
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  const stopped = new Promise((resolve) => server.once('exit', resolve));
  server.kill('SIGTERM');
  await Promise.race([stopped, new Promise((resolve) => setTimeout(resolve, 5000))]);
}
