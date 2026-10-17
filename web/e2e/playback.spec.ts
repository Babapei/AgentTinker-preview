import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import type { RuntimeEvent, RunView } from '../src/protocol';

async function example(page: Page) {
  const history = await (await page.request.get('/api/v1/runs')).json();
  const id = history.items.find(
    (run: RunView['run']) => run.config.task === '重试：比较虚构发布说明',
  ).run_id;
  const view: RunView = await (await page.request.get(`/api/v1/runs/${id}`)).json();
  const events: RuntimeEvent[] = await (
    await page.request.get(`http://127.0.0.1:8000/__test__/runs/${id}/events`)
  ).json();
  return { view, events };
}

test('replays real event prefixes without fetching or exposing future results', async ({
  page,
}) => {
  const { view } = await example(page);
  await page.goto(`/?run=${view.run.run_id}`);
  await expect(page.locator('.record-connection')).toContainText('事件已核对');
  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/')) requests.push(request.url());
  });
  await page.getByRole('button', { name: /model 调用 2/ }).click();
  await page.getByRole('button', { name: '回到第一个事件' }).click();
  await expect(page.locator('.run-header')).toContainText('排队中');
  await expect(page.locator('.playback-heading')).toContainText('实际运行：执行成功');
  await expect(page.locator('.step-row')).toHaveCount(0);
  await expect(page.getByText('模拟模型输出', { exact: true })).toHaveCount(0);
  const slider = page.getByRole('slider', { name: '历史事件位置' });
  await slider.focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(page.getByLabel('已应用事件位置')).toHaveText(`3 / ${view.last_seq}`);
  await expect(page.locator('.step-row')).toHaveCount(1);
  await page.getByRole('button', { name: /model 调用 1/ }).click();
  await page.getByLabel('详情视图').getByRole('button', { name: '输出', exact: true }).click();
  await expect(page.getByLabel('步骤详情')).toContainText('未取得输出');
  await expect(page.getByLabel('事件时间线').getByRole('button')).toHaveCount(3);
  await page.getByRole('button', { name: '回到第一个事件' }).click();
  await page.getByLabel('历史播放速度').selectOption('4');
  await page.getByRole('button', { name: '播放历史记录' }).click();
  await expect(page.getByRole('button', { name: '暂停历史播放' })).toBeVisible();
  await page.getByRole('button', { name: '暂停历史播放' }).click();
  const position = await page.getByLabel('已应用事件位置').textContent();
  await page.clock.install();
  await page.clock.runFor(5000);
  await expect(page.getByLabel('已应用事件位置')).toHaveText(position!);
  await page.getByRole('button', { name: '播放历史记录' }).click();
  await expect(page.getByLabel('已应用事件位置')).toHaveText(`${view.last_seq} / ${view.last_seq}`);
  await expect(page.getByRole('button', { name: '播放历史记录' })).toBeVisible();
  await page.getByRole('button', { name: /返回最新/ }).click();
  await expect(page.locator('.step-row')).toHaveCount(4);
  await expect(page.getByText('模拟模型输出', { exact: true })).toBeVisible();
  expect(requests).toEqual([]);
  const after = await (await page.request.get(`/api/v1/runs/${view.run.run_id}`)).json();
  expect(after).toEqual(view);
});

test('links graph nodes and raw events to the same projected step evidence', async ({ page }) => {
  const { view, events } = await example(page);
  await page.goto(`/?run=${view.run.run_id}`);
  await expect(page.locator('.record-connection')).toContainText('事件已核对');
  await page.getByLabel('执行过程视图').getByRole('button', { name: '执行图' }).click();
  const graph = page.getByRole('region', { name: '实际执行图' });
  await expect(graph.getByRole('button', { name: /^检查步骤/ })).toHaveCount(4);
  await expect(graph.getByText('执行器重试', { exact: true })).toBeVisible();
  const retried = graph.getByRole('button', { name: '检查步骤 search_documents 尝试 2' });
  await retried.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('步骤详情')).toContainText('第 2 次尝试');
  await expect(page).toHaveURL(new RegExp(view.spans[2].span_id));
  const failure = events.find((event) => event.type === 'tool.attempt_failed')!;
  await page.getByLabel('筛选事件').selectOption('tool.');
  await page.getByRole('button', { name: `#${failure.seq} 注入故障 · TOOL_TIMEOUT` }).click();
  await expect(graph.getByRole('button', { name: /^检查步骤/ })).toHaveCount(2);
  await expect(page.getByLabel('事件原始记录').locator('pre')).toContainText(
    '"origin": "injected"',
  );
  await expect(page.getByLabel('步骤详情')).toContainText('TOOL_TIMEOUT');
  await page.getByRole('button', { name: /返回最新/ }).click();
  await page.getByLabel('筛选事件').selectOption('all');
  await expect(graph.getByRole('button', { name: /^检查步骤/ })).toHaveCount(4);
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  expect(results.violations).toEqual([]);
  await page.evaluate(() => {
    (document.activeElement as HTMLElement)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: '../artifacts/m2-execution-graph.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(graph.getByRole('button', { name: /^检查步骤/ })).toHaveCount(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../artifacts/m2-execution-graph-mobile.png', fullPage: true });
});

test('keeps replay frozen while a real background run finishes and shows new facts separately', async ({
  page,
}) => {
  const started = await page.request.post('http://127.0.0.1:8000/__test__/runs');
  const { run_id: id } = await started.json();
  try {
    await page.goto(`/?run=${id}`);
    await expect(page.locator('.record-connection')).toContainText('正在跟随');
    await page.getByRole('button', { name: '回到第一个事件' }).click();
    const position = await page.getByLabel('已应用事件位置').textContent();
    await expect(page.locator('.run-header')).toContainText('排队中');
    await page.request.post(`http://127.0.0.1:8000/__test__/runs/${id}/release`);
    await expect(page.locator('.playback-heading')).toContainText('实际运行：执行成功');
    await expect(page.getByLabel('已应用事件位置')).toHaveText(position!);
    await expect(page.locator('.run-header')).toContainText('排队中');
    await expect(page.getByRole('button', { name: /条新事件/ })).toBeVisible();
    await expect(page.locator('.step-row')).toHaveCount(0);
    await page.getByRole('button', { name: /返回最新/ }).click();
    await expect(page.locator('.step-row')).toHaveCount(4);
    await expect(page.locator('.run-header')).toContainText('执行成功');
  } finally {
    await page.request.post(`http://127.0.0.1:8000/__test__/runs/${id}/release`);
  }
});

test('inspects an explicitly imported summary without inventing checkpoints or event playback', async ({
  page,
}) => {
  const { view } = await example(page);
  const imported = structuredClone(view);
  imported.run.mode = 'imported';
  imported.run.capabilities = {
    ...imported.run.capabilities,
    record_playback: false,
    run_from_start: false,
    fork_from_checkpoint: false,
  };
  imported.checkpoints = [];
  await page.route(`**/api/v1/runs/${view.run.run_id}`, (route) =>
    route.fulfill({ json: imported }),
  );
  await page.goto(`/?run=${view.run.run_id}`);
  await expect(page.locator('.run-header')).toContainText('导入记录');
  await expect(page.locator('.record-connection')).toContainText('没有可订阅的完整事件');
  await expect(page.getByRole('button', { name: '播放历史记录' })).toBeDisabled();
  await expect(page.getByLabel('事件时间线')).toHaveCount(0);
  await expect(page.locator('.step-row')).toHaveCount(4);
  await page.getByLabel('执行过程视图').getByRole('button', { name: '执行图' }).click();
  await expect(
    page.getByRole('region', { name: '实际执行图' }).getByRole('button', { name: /^检查步骤/ }),
  ).toHaveCount(4);
  await expect(page.getByText('此记录当前不支持从检查点创建分支。')).toBeVisible();
});
