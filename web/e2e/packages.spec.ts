import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type { RunView } from '../src/protocol';

type PackageData = {
  format: string;
  format_version: string;
  manifest: {
    kind: string;
    root_run_id: string;
    entries: { path: string; sha256: string; size_bytes: number; media_type: string }[];
  };
  files: Record<string, any>;
};
const key = () => `package-${Date.now()}-${Math.random()}`;
async function readRun(page: Page, id: string): Promise<RunView> {
  return (await page.request.get(`/api/v1/runs/${id}`)).json();
}
async function pair(page: Page, document = true) {
  const response = await page.request.post(
    document ? '/api/v1/scenarios/document-missing/runs' : '/api/v1/runs',
    {
      headers: { 'Idempotency-Key': key() },
      data: { mode: 'synthetic' },
    },
  );
  expect(response.status()).toBe(201);
  const aId = (await response.json()).run.run_id;
  await expect
    .poll(async () => (await readRun(page, aId)).run.status)
    .toBe(document ? 'succeeded' : 'failed');
  const a = await readRun(page, aId);
  const fork = await page.request.post(`/api/v1/runs/${aId}/forks`, {
    headers: { 'Idempotency-Key': key() },
    data: {
      source_checkpoint_id: a.checkpoints[0].checkpoint_id,
      patch: document ? { top_k: 3 } : { tool_retry_limit: 1 },
    },
  });
  expect(fork.status()).toBe(201);
  const bId = (await fork.json()).run.run_id;
  await expect.poll(async () => (await readRun(page, bId)).run.status).toBe('succeeded');
  if (document) {
    const evaluation = await (
      await page.request.post(`/api/v1/runs/${bId}/evaluations`, {
        headers: { 'Idempotency-Key': key() },
        data: {},
      })
    ).json();
    const review = await page.request.post(`/api/v1/runs/${bId}/reviews`, {
      headers: { 'Idempotency-Key': key() },
      data: {
        evaluation_id: evaluation.evaluation_id,
        input_hash: evaluation.input_hash,
        reviewer: '浏览器导入测试',
        fact_coverage: { 'configurable-retries': 'covered', 'citation-fix': 'covered' },
        judgement: 'uncertain',
        explanation: '离线导入测试意见，不代表真实用户研究。',
      },
    });
    expect(review.status()).toBe(201);
  }
  return { a, b: await readRun(page, bId) };
}
async function download(page: Page) {
  const ready = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出实验包', exact: true }).click();
  const file = await ready;
  expect(file.suggestedFilename()).toMatch(/^agenttinker-.*\.json$/);
  return readFile((await file.path())!);
}
async function select(page: Page, buffer: Buffer, name = 'experiment.json') {
  await page.getByRole('button', { name: '导入文件', exact: true }).click();
  await page
    .getByLabel('JSON 实验包文件')
    .setInputFiles({ name, mimeType: 'application/json', buffer });
  await expect(page.getByRole('button', { name: '导入并打开记录' })).toBeEnabled();
}
async function upload(page: Page, buffer: Buffer) {
  await select(page, buffer);
  await page.getByRole('button', { name: '导入并打开记录' }).click();
  await expect(page.getByLabel('导入来源与原意见')).toContainText('原记录模式');
  return new URL(page.url()).searchParams.get('run')!;
}

for (const isDoc of [true, false]) {
  test(`downloads and imports the native ${isDoc ? 'document' : 'timeout'} A/B without execution, keeps source opinions and replays`, async ({
    page,
  }) => {
    const { a, b } = await pair(page, isDoc);
    await page.goto(`/?run=${b.run.run_id}`);
    await expect(page.locator('.record-connection')).toContainText('事件已核对');
    const bytes = await download(page);
    const original = JSON.parse(bytes.toString());
    const local = await upload(page, bytes);
    expect(local).not.toBe(b.run.run_id);
    await expect(page.locator('.record-connection')).toContainText('事件已核对');
    const source = page.getByLabel('导入来源与原意见');
    await expect(source).toContainText('模拟运行（来源声明）');
    await expect(source).toContainText('未核验来源身份');
    await expect(page.getByRole('button', { name: '检查分支可用性' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '运行规则评价', exact: true })).toHaveCount(0);
    await expect(page.getByLabel('人工复核表单')).toHaveCount(0);
    await expect(page.getByLabel('实际运行控制')).toHaveCount(0);
    if (isDoc) {
      await expect(source).toContainText('原规则评价 · 1 份');
      await expect(source).toContainText('原人工意见 · 1 份');
      await expect(source).toContainText('来源署名（未认证）：浏览器导入测试');
    }
    const imported = await readRun(page, local);
    expect(imported.run.mode).toBe('imported');
    expect(imported.run.parent_run_id).not.toBe(a.run.run_id);
    const comparison = page.getByLabel('A/B 运行对比');
    await expect(comparison).toContainText('先看配置改动');
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/')) requests.push(request.method() + ' ' + request.url());
    });
    await page.getByRole('button', { name: '回到第一个事件' }).click();
    await expect(source).toContainText('结束后的原评价与人工意见在这里隐藏');
    await expect(source.locator('.source-opinions')).toHaveCount(0);
    await page.getByRole('button', { name: /返回最新/ }).click();
    await expect(source.locator('.source-opinions')).toHaveCount(1);
    expect(requests).toEqual([]);
    expect(JSON.parse((await download(page)).toString())).toEqual(original);
    expect(await readRun(page, a.run.run_id)).toEqual(a);
    expect(await readRun(page, b.run.run_id)).toEqual(b);
    if (isDoc) {
      expect((await new AxeBuilder({ page }).include('main').analyze()).violations).toEqual([]);
      await page.screenshot({ path: '../artifacts/m4-package-desktop.png', fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      expect((await new AxeBuilder({ page }).include('main').analyze()).violations).toEqual([]);
      await page.screenshot({ path: '../artifacts/m4-package-mobile.png', fullPage: true });
    }
  });
}

test('reselects the same file after a lost import response with its original key and no duplicate records', async ({
  page,
}) => {
  const { b } = await pair(page);
  const bytes = await (await page.request.get(`/api/v1/runs/${b.run.run_id}/export`)).body();
  const keys: string[] = [];
  let local = '';
  await page.route('**/api/v1/imports', async (route) => {
    keys.push(route.request().headers()['idempotency-key']);
    const response = await route.fetch();
    local = (await response.json()).root_run_id;
    await route.abort('failed');
  });
  await page.goto(`/?run=${b.run.run_id}`);
  await select(page, bytes);
  await page.getByRole('button', { name: '导入并打开记录' }).click();
  await expect(page.getByRole('alert')).toContainText('未能确认操作结果');
  await page.unroute('**/api/v1/imports');
  await page.reload();
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST') writes.push(request.url());
  });
  await page.getByRole('button', { name: '导入文件', exact: true }).click();
  await expect(page.getByLabel('导入实验包')).toContainText('有未确认的导入');
  expect(writes).toEqual([]);
  await page.route('**/api/v1/imports', async (route) => {
    keys.push(route.request().headers()['idempotency-key']);
    await route.continue();
  });
  await page.getByLabel('JSON 实验包文件').setInputFiles({
    name: 'renamed-same-content.json',
    mimeType: 'application/json',
    buffer: bytes,
  });
  await page.getByRole('button', { name: '导入并打开记录' }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('run')).toBe(local);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  const source = await (await page.request.get(`/api/v1/runs/${local}/provenance`)).json();
  const result = await (await page.request.get(`/api/v1/imports/${source.import_id}`)).json();
  const again = await page.request.post('/api/v1/imports', {
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key() },
    data: bytes,
  });
  expect(again.status()).toBe(200);
  expect(await again.json()).toEqual(result);
  expect(
    await page.evaluate(() => sessionStorage.getItem('agenttinker.pending-requests.v1')),
  ).not.toContain(b.run.run_id);
});

function sorted(value: any): any {
  return Array.isArray(value)
    ? value.map(sorted)
    : value !== null && typeof value === 'object'
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, sorted(value[key])]),
        )
      : value;
}
function summaryPackage(original: PackageData) {
  const path = `runs/${original.manifest.root_run_id}.json`;
  const record = original.files[path];
  record.view.run.mode = record.source.mode = 'live'; // An external claim, never dispatches a model.
  record.view.run.status = 'running';
  record.view.run.capabilities.record_playback = false;
  record.view.spans = [{ ...record.view.spans[0], input: null, output: null, duration_ms: null }];
  record.view.checkpoints = [];
  record.events = null;
  record.evaluations = record.reviews = record.evaluation_bindings = [];
  original.files = { [path]: record };
  original.manifest.kind = 'trace';
  const data = Buffer.from(JSON.stringify(sorted(record)));
  original.manifest.entries = [
    {
      path,
      sha256: createHash('sha256').update(data).digest('hex'),
      size_bytes: data.byteLength,
      media_type: 'application/json',
    },
  ];
  return Buffer.from(JSON.stringify(original));
}

test('opens an active external summary without invented events or local execution controls', async ({
  page,
}) => {
  const { a } = await pair(page);
  const original = await (await page.request.get(`/api/v1/runs/${a.run.run_id}/export`)).json();
  const bytes = summaryPackage(original);
  await page.goto('/');
  const id = await upload(page, bytes);
  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/')) requests.push(request.url());
  });
  await expect(page.getByLabel('导入来源与原意见')).toContainText('此包仅含摘要');
  await expect(page.getByLabel('导入来源与原意见')).toContainText('真实调用（来源声明）');
  await expect(page.getByLabel('实际运行控制')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '播放历史记录' })).toBeDisabled();
  await expect(page.getByLabel('已应用事件位置')).toHaveText('仅摘要');
  await expect(page.getByRole('button', { name: '检查分支可用性' })).toHaveCount(0);
  await expect(page.getByLabel('本次运行新增调用指标')).toContainText('未知');
  expect((await readRun(page, id)).run.status).toBe('running');
  expect(requests.filter((url) => url.endsWith('/events'))).toEqual([]);
  await page.reload();
  await expect(page.getByLabel('导入来源与原意见')).toContainText('此包仅含摘要');
  expect((await readRun(page, id)).run.status).toBe('running');
  await expect(page.getByLabel('实际运行控制')).toHaveCount(0);
});

test('rejects malformed or oversized files without changing history, and keeps file input accessible', async ({
  page,
}) => {
  await page.goto('/');
  const before = await (await page.request.get('/api/v1/runs')).json();
  await select(page, Buffer.from('{"private-input-marker":'));
  await page.getByRole('button', { name: '导入并打开记录' }).click();
  const error = page.getByLabel('导入实验包').getByRole('alert');
  await expect(error).toContainText('未通过校验');
  await expect(error).not.toContainText('private-input-marker');
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST') writes.push(request.url());
  });
  await page.getByLabel('JSON 实验包文件').setInputFiles({
    name: 'oversized.json',
    mimeType: 'application/json',
    buffer: Buffer.alloc(8 * 1024 * 1024 + 1),
  });
  await expect(error).toContainText('8 MiB');
  await expect(page.getByRole('button', { name: '导入并打开记录' })).toBeDisabled();
  expect(writes).toEqual([]);
  expect(await (await page.request.get('/api/v1/runs')).json()).toEqual(before);
  expect(
    (await new AxeBuilder({ page }).include('[aria-label="导入实验包"]').analyze()).violations,
  ).toEqual([]);
  await page.getByLabel('JSON 实验包文件').focus();
  await expect(page.getByLabel('JSON 实验包文件')).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
