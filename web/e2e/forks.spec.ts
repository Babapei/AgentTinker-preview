import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type { RunView } from '../src/protocol';

async function baseline(page: Page): Promise<RunView> {
  const response = await page.request.post('/api/v1/runs', {
    headers: { 'Idempotency-Key': `browser-fork-${Date.now()}-${Math.random()}` },
    data: { mode: 'synthetic', task: `独立分支验证 ${Date.now()}-${Math.random()}` },
  });
  const id = (await response.json()).run.run_id;
  await expect
    .poll(async () => (await (await page.request.get(`/api/v1/runs/${id}`)).json()).run.status)
    .toBe('failed');
  return (await page.request.get(`/api/v1/runs/${id}`)).json();
}

async function openFork(page: Page, source: RunView) {
  await page.goto(`/?run=${source.run.run_id}`);
  await page.getByRole('button', { name: '检查分支可用性', exact: true }).click();
  await expect(page.getByRole('button', { name: '创建分支并运行', exact: true })).toBeEnabled();
}

test('forks the native timeout baseline and compares a single change without rewriting A', async ({
  page,
}) => {
  const source = await baseline(page);
  await openFork(page, source);
  await expect(page.locator('.patch-summary')).toContainText('0 → 1');
  await page.getByRole('button', { name: '创建分支并运行', exact: true }).click();
  await expect(page.locator('.run-header')).toContainText('执行成功');
  const id = new URL(page.url()).searchParams.get('run')!;
  expect(id).not.toBe(source.run.run_id);
  const comparison = page.getByLabel('A/B 运行对比');
  await expect(comparison).toContainText('tool_policy.tool_retry_limit');
  await expect(comparison).toContainText('B 引用 1 个既有步骤');
  await expect(comparison.getByRole('row', { name: /逻辑工具调用/ })).toContainText('1 / 2');
  await expect(
    comparison
      .getByRole('row', { name: /新增模型调用/ })
      .getByRole('cell')
      .last(),
  ).toHaveText('1');
  await expect(comparison.getByRole('row', { name: /新增 Token/ })).toContainText('未知');
  await expect(comparison).toContainText('重试由执行器负责');
  await expect(comparison.getByRole('row', { name: /答案评价/ })).toContainText('未评价');
  expect(await (await page.request.get(`/api/v1/runs/${source.run.run_id}`)).json()).toEqual(
    source,
  );
  const branch = await (await page.request.get(`/api/v1/runs/${id}`)).json();
  expect(branch.run.inherited_span_ids).toEqual([source.spans[0].span_id]);
  expect(branch.spans[0].input.tool_call).toEqual(source.spans[1].input!.tool_call);
  expect(branch.spans[0].output).toEqual(source.spans[1].output);
  await page.getByRole('button', { name: '隐藏实验讲解' }).click();
  await expect(page.getByLabel('实验讲解')).toHaveCount(0);
  await expect(page.locator('.step-row')).toHaveCount(3);
  await page.reload();
  await expect(page.getByLabel('A/B 运行对比')).toContainText(source.checkpoints[0].checkpoint_id);
  await expect(page.getByRole('button', { name: /查看父运行/ })).toBeVisible();
});

test('branch replay hides future B results and does not execute or refetch the prefix', async ({
  page,
}) => {
  const source = await baseline(page);
  await openFork(page, source);
  await page.getByRole('button', { name: '创建分支并运行', exact: true }).click();
  await expect(page.locator('.record-connection')).toContainText('事件已核对');
  await expect(page.getByLabel('A/B 运行对比')).toContainText('release-v1');
  const requests: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/')) requests.push(r.url());
  });
  await page.getByRole('button', { name: '回到第一个事件' }).click();
  const comparison = page.getByLabel('A/B 运行对比');
  await expect(
    comparison
      .getByRole('row', { name: /新增模型调用/ })
      .getByRole('cell')
      .last(),
  ).toHaveText('0');
  await expect(
    comparison
      .getByRole('row', { name: /取得的文档 ID/ })
      .getByRole('cell')
      .last(),
  ).toHaveText('未记录返回材料');
  await expect(page.getByRole('button', { name: '检查分支可用性', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: /返回最新/ }).click();
  await expect(comparison).toContainText('release-v1');
  expect(requests).toEqual([]);
});

test('stale availability never bypasses a rejected server fork, then retries the same intent', async ({
  page,
}) => {
  const source = await baseline(page),
    keys: string[] = [];
  await page.route(`**/api/v1/runs/${source.run.run_id}/forks`, async (route) => {
    keys.push(route.request().headers()['idempotency-key']);
    if (keys.length === 1)
      await route.fulfill({ status: 409, json: { detail: 'runtime_incompatible' } });
    else await route.continue();
  });
  await openFork(page, source);
  await page.getByRole('button', { name: '创建分支并运行', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('不兼容');
  await expect(page).toHaveURL(new RegExp(source.run.run_id));
  await page.getByRole('button', { name: '重新检查分支可用性' }).click();
  await page.getByRole('button', { name: '创建分支并运行', exact: true }).click();
  await expect(page.locator('.run-header')).toContainText('执行成功');
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});

test('restores an uncertain fork after reload and receives the same B without another execution', async ({
  page,
}) => {
  const source = await baseline(page),
    keys: string[] = [];
  let id = '';
  await page.route(`**/api/v1/runs/${source.run.run_id}/forks`, async (route) => {
    keys.push(route.request().headers()['idempotency-key']);
    const response = await route.fetch();
    id = (await response.json()).run.run_id;
    if (keys.length === 1) await route.abort('failed');
    else await route.fulfill({ response });
  });
  await openFork(page, source);
  await page.getByRole('button', { name: '创建分支并运行', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('未能确认操作结果');
  await page.reload();
  await page.getByRole('button', { name: '检查分支可用性', exact: true }).click();
  await expect(page.locator('.patch-summary')).toContainText('0 → 1');
  await page.getByRole('button', { name: '创建分支并运行', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(id));
  await expect(page.locator('.run-header')).toContainText('执行成功');
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  const history = await (await page.request.get('/api/v1/runs')).json();
  expect(
    history.items.filter(
      (run: { parent_run_id: string }) => run.parent_run_id === source.run.run_id,
    ),
  ).toHaveLength(1);
});

test('missing runtime state keeps history readable and disables branching', async ({ page }) => {
  const source = await baseline(page);
  await page.route(`**/api/v1/runs/${source.run.run_id}/checkpoint-availability`, async (route) => {
    const response = await route.fetch();
    const items = await response.json();
    await route.fulfill({
      json: items.map((item: unknown) => ({
        ...(item as object),
        available: false,
        reason: 'checkpoint_missing',
        allowed_patch_fields: [],
      })),
    });
  });
  await page.goto(`/?run=${source.run.run_id}`);
  await page.getByRole('button', { name: '检查分支可用性', exact: true }).click();
  await expect(page.getByLabel('检查点分支')).toContainText('检查点已缺失');
  await expect(page.getByRole('button', { name: '创建分支并运行', exact: true })).toBeDisabled();
  await expect(page.locator('.step-row')).toHaveCount(2);
});

test('supports a top_k fork, comparison accessibility and narrow layouts', async ({ page }) => {
  const source = await baseline(page);
  await openFork(page, source);
  await page.getByRole('combobox', { name: '只修改一个参数', exact: true }).selectOption('top_k');
  await expect(page.locator('.patch-summary')).toContainText('2 → 3');
  await page.getByRole('button', { name: '创建分支并运行', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.run-header')).toContainText('执行失败');
  const comparison = page.getByLabel('A/B 运行对比');
  await expect(comparison).toContainText('tool_policy.top_k');
  expect(
    (
      await new AxeBuilder({ page })
        .include('.comparison-panel')
        .include('.fork-panel')
        .withTags(['wcag2a', 'wcag2aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({ path: '../artifacts/m3-comparison-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../artifacts/m3-comparison-mobile.png', fullPage: true });
});
