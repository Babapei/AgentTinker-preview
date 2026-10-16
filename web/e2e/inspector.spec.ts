import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type { RunView } from '../src/protocol';

async function records(page: Page) {
  const response = await page.request.get('/api/v1/runs');
  const history = await response.json();
  const views: RunView[] = await Promise.all(
    history.items.map(async (run: { run_id: string }) => {
      const result = await page.request.get(`/api/v1/runs/${run.run_id}`);
      return result.json();
    }),
  );
  return {
    failed: views.find((view) => view.run.status === 'failed')!,
    retried: views.find((view) => view.run.status === 'succeeded')!,
  };
}

test('inspects native retry history with no execution requests', async ({ page }) => {
  const { retried } = await records(page);
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/') && request.method() !== 'GET') writes.push(request.url());
  });
  await page.goto(`/?run=${retried.run.run_id}`);
  await expect(page.getByRole('heading', { name: '运行检查台' })).toBeVisible();
  await expect(
    page.getByRole('region', { name: '执行步骤' }).getByRole('button', { name: /model 调用/ }),
  ).toHaveCount(2);
  const firstAttempt = page.getByRole('button', { name: /search_documents 尝试 1/ });
  await expect(firstAttempt).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByLabel('步骤详情')).toContainText('实验故障注入');
  await page.getByLabel('详情视图').getByRole('button', { name: '输入', exact: true }).click();
  await expect(page.getByLabel('步骤详情').locator('pre')).toContainText('effective_policy');
  await expect(page.getByLabel('步骤详情').locator('pre')).toContainText('tool_retry_limit');
  await page.getByLabel('详情视图').getByRole('button', { name: '输出', exact: true }).click();
  await expect(page.getByLabel('步骤详情').locator('pre')).toContainText('TOOL_TIMEOUT');
  await page.getByRole('button', { name: /model 调用 2/ }).click();
  await page.getByLabel('详情视图').getByRole('button', { name: '概览', exact: true }).click();
  await expect(page.getByLabel('步骤详情')).toContainText('没有真实提供商用量或账单');
  await expect(page.getByLabel('本次运行新增调用指标')).toContainText('未知');
  await expect(page.getByText('模拟模型输出', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '运行配置与来源' }).click();
  await expect(page.locator('.config-block pre')).toContainText('fixture_hash');
  await page.getByRole('button', { name: '刷新记录' }).click();
  await expect(page.getByRole('button', { name: '刷新记录' })).toBeEnabled();
  await expect(page.getByRole('button', { name: /model 调用 2/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  const after = await page.request.get(`/api/v1/runs/${retried.run.run_id}`);
  expect(await after.json()).toEqual(retried);
  expect(writes).toEqual([]);
  await page.getByRole('button', { name: '运行配置与来源' }).click();
  await firstAttempt.click();
  await page.evaluate(() => {
    (document.activeElement as HTMLElement)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: '../artifacts/m2-inspector-desktop.png', fullPage: true });
});

test('keeps run and step selection through reload, history navigation, and keyboard input', async ({
  page,
}) => {
  const { retried, failed } = await records(page);
  const step = retried.spans[2];
  await page.goto(`/?run=${retried.run.run_id}&span=${step.span_id}`);
  const secondAttempt = page.getByRole('button', { name: /search_documents 尝试 2/ });
  await expect(secondAttempt).toHaveAttribute('aria-pressed', 'true');
  await page.reload();
  await expect(secondAttempt).toHaveAttribute('aria-pressed', 'true');
  await page
    .getByLabel('选择运行记录')
    .getByRole('button', { name: /基线：首次检索超时/ })
    .click();
  await expect(page).toHaveURL(new RegExp(failed.run.run_id));
  await page.goBack();
  await expect(secondAttempt).toHaveAttribute('aria-pressed', 'true');
  await page.getByLabel('筛选步骤').selectOption('failed');
  await expect(page.getByRole('region', { name: '执行步骤' }).locator('.step-row')).toHaveCount(1);
  const failedAttempt = page.getByRole('button', { name: /search_documents 尝试 1/ });
  await failedAttempt.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('步骤详情')).toContainText('TOOL_TIMEOUT');
  await page.getByLabel('搜索已加载的运行').fill('并不存在的任务');
  await expect(page.getByText('没有匹配的已加载记录')).toBeVisible();
  await expect(page.getByLabel('步骤详情')).toContainText('TOOL_TIMEOUT');
});

test('ignores a late response from the previous run', async ({ page }) => {
  const { retried, failed } = await records(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let entered!: () => void;
  const waiting = new Promise<void>((resolve) => {
    entered = resolve;
  });
  await page.route(`**/api/v1/runs/${failed.run.run_id}`, async (route) => {
    entered();
    await gate;
    await route.fulfill({ json: failed }).catch(() => undefined);
  });
  await page.goto(`/?run=${failed.run.run_id}`);
  await waiting;
  await page
    .getByLabel('选择运行记录')
    .getByRole('button', { name: /重试：比较虚构发布说明/ })
    .click();
  await expect(page.locator('.run-header')).toContainText(retried.run.config.task!);
  release();
  await page.waitForLoadState('networkidle');
  await expect(page.locator('.run-header')).toContainText(retried.run.config.task!);
  await expect(page).toHaveURL(new RegExp(retried.run.run_id));
});

test('paginates and searches loaded history without losing the selected run', async ({ page }) => {
  const { retried } = await records(page);
  await page.route('**/api/v1/runs?**', async (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    const items = Array.from({ length: offset === 0 ? 50 : 1 }, (_, index) => ({
      ...retried.run,
      run_id: `run_page_${offset + index}`,
      config: { ...retried.run.config, task: `分页记录 ${offset + index}` },
    }));
    await route.fulfill({ json: { items, total: 51, next_offset: offset === 0 ? 50 : null } });
  });
  await page.goto(`/?run=${retried.run.run_id}`);
  await expect(page.getByLabel('选择运行记录').getByRole('button')).toHaveCount(50);
  await page.getByRole('button', { name: /加载更多/ }).click();
  await expect(page.getByLabel('选择运行记录').getByRole('button')).toHaveCount(51);
  await page.getByLabel('搜索已加载的运行').fill('分页记录 50');
  await expect(page.getByLabel('选择运行记录').getByRole('button')).toHaveCount(1);
  await expect(page.locator('.run-header')).toContainText(retried.run.config.task!);
});

test('shows an honest empty state', async ({ page }) => {
  await page.route('**/api/v1/runs?**', (route) =>
    route.fulfill({ json: { items: [], total: 0, next_offset: null } }),
  );
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '每一次运行，都是一份证据' })).toBeVisible();
  await expect(page.getByText('暂无运行记录', { exact: true })).toBeVisible();
  await expect(page.locator('.metrics')).toHaveCount(0);
});

test('distinguishes a missing run, a backend failure, and incompatible data', async ({ page }) => {
  await page.goto('/?run=run_missing');
  await expect(page.getByRole('alert')).toContainText('找不到这条运行记录');
  const { retried } = await records(page);
  await page.route(`**/api/v1/runs/${retried.run.run_id}`, (route) =>
    route.fulfill({ status: 503, body: 'private-provider-error' }),
  );
  await page.goto(`/?run=${retried.run.run_id}`);
  await expect(page.getByRole('alert')).toContainText('暂时无法读取运行记录');
  await expect(page.locator('body')).not.toContainText('private-provider-error');
  await page.unroute(`**/api/v1/runs/${retried.run.run_id}`);
  await page.route(`**/api/v1/runs/${retried.run.run_id}`, (route) =>
    route.fulfill({ json: { ...retried, schema_version: '999' } }),
  );
  await page.getByRole('button', { name: '重新读取' }).click();
  await expect(page.getByRole('alert')).toContainText('运行记录的协议不兼容');
  await expect(page.locator('.metrics')).toHaveCount(0);
});

test('keeps cancellation pending and incomplete usage unknown while preserving observed zero', async ({
  page,
}) => {
  const { retried } = await records(page);
  const fixture = structuredClone(retried);
  fixture.run.status = 'cancel_requested';
  fixture.spans[0].duration_ms = 0;
  fixture.spans[0].usage.total_tokens = 0;
  await page.route(`**/api/v1/runs/${retried.run.run_id}`, (route) =>
    route.fulfill({ json: fixture }),
  );
  await page.goto(`/?run=${retried.run.run_id}&span=${retried.spans[0].span_id}`);
  await expect(page.locator('.run-header')).toContainText('正在取消');
  await expect(page.locator('.run-header')).not.toContainText('已取消');
  await expect(page.getByLabel('本次运行新增调用指标')).toContainText('1 / 2 次调用有用量');
  await expect(page.getByLabel('本次运行新增调用指标')).toContainText('未知');
  await expect(page.getByLabel('步骤详情')).toContainText('0.0 ms');
  await expect(
    page.getByLabel('步骤详情').locator('.facts > div').filter({ hasText: '总 Token' }),
  ).toContainText('0');
});

test('fits narrow screens and respects reduced motion', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const { retried } = await records(page);
  await page.goto(`/?run=${retried.run.run_id}`);
  await page.getByRole('button', { name: /search_documents 尝试 1/ }).click();
  await page.getByLabel('详情视图').getByRole('button', { name: '输入', exact: true }).click();
  await expect(page.getByLabel('步骤详情').locator('pre')).toContainText('tool_retry_limit');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(
    true,
  );
  await page.evaluate(() => {
    (document.activeElement as HTMLElement)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: '../artifacts/m2-inspector-mobile.png', fullPage: true });
});

test('keeps the default inspector accessible to keyboard and assistive technology', async ({
  page,
}) => {
  const { retried } = await records(page);
  await page.goto(`/?run=${retried.run.run_id}`);
  await expect(page.getByLabel('步骤详情')).toContainText('TOOL_TIMEOUT');
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  expect(results.violations).toEqual([]);
});
