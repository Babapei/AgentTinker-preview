import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

async function configure(page: Page, task: string) {
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await page.getByRole('textbox', { name: '任务', exact: true }).fill(task);
  await page.getByRole('combobox', { name: '运行模式', exact: true }).selectOption('synthetic');
}

test('starts an explicitly configured native synthetic experiment through the actual API', async ({
  page,
}) => {
  const writes: string[] = [];
  page.on('request', (r) => {
    if (r.url().endsWith('/api/v1/runs') && r.method() === 'POST') writes.push(r.url());
  });
  await page.goto('/');
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await expect(page.getByRole('button', { name: '开始运行实验' })).toBeDisabled();
  const task = `表单基线 ${Date.now()}`;
  await page.getByRole('textbox', { name: '任务', exact: true }).fill(task);
  await page.getByRole('combobox', { name: '运行模式', exact: true }).selectOption('synthetic');
  await page.getByRole('button', { name: '开始运行实验' }).click({ clickCount: 2 });
  await expect(page.locator('.run-header')).toContainText(task);
  await expect(page.locator('.run-header')).toContainText('执行失败');
  await expect(page.locator('.record-connection')).toContainText('事件已核对');
  await expect(page.locator('.step-row')).toHaveCount(2);
  const id = new URL(page.url()).searchParams.get('run');
  const view = await (await page.request.get(`/api/v1/runs/${id}`)).json();
  expect(view.run.config.tool_policy).toEqual({ tool_retry_limit: 0, top_k: 2 });
  expect(view.run.config.fault_parameters.inject_timeout).toBe(true);
  expect(writes).toHaveLength(1);
  await page.reload();
  await expect(page.locator('.run-header')).toContainText(task);
});

test('cancels the actual task while an in-flight model result is preserved', async ({ page }) => {
  const task = `表单取消 ${Date.now()}`;
  await page.request.post('http://127.0.0.1:8000/__test__/prepare', { data: { task } });
  await page.goto('/');
  await configure(page, task);
  await page.getByRole('button', { name: '开始运行实验' }).click();
  await expect(page.locator('.run-header')).toContainText(task);
  const id = new URL(page.url()).searchParams.get('run');
  try {
    await expect(page.getByLabel('实际运行控制')).toContainText('运行中');
    await page.getByRole('button', { name: '取消实际运行', exact: true }).click();
    await expect(page.getByLabel('实际运行控制')).toContainText('正在取消');
    await expect(page.getByRole('button', { name: '等待取消完成' })).toBeDisabled();
  } finally {
    await page.request.post(`http://127.0.0.1:8000/__test__/runs/${id}/release`);
  }
  await expect(page.locator('.run-header')).toContainText('已取消');
  const view = await (await page.request.get(`/api/v1/runs/${id}`)).json();
  expect(view.spans).toHaveLength(1);
  expect(view.spans[0].status).toBe('succeeded');
  expect(view.spans[0].output.message.tool_calls).toHaveLength(1);
});

test('retries a lost creation response after reload with the same key and run', async ({
  page,
}) => {
  const keys: string[] = [];
  let created = '';
  await page.route('**/api/v1/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    keys.push(route.request().headers()['idempotency-key']);
    const response = await route.fetch();
    created = (await response.json()).run.run_id;
    if (keys.length === 1) await route.abort('failed');
    else await route.fulfill({ response });
  });
  const task = `丢失响应 ${Date.now()}`;
  await page.goto('/');
  await configure(page, task);
  await page.getByRole('button', { name: '开始运行实验' }).click();
  await expect(page.getByRole('alert')).toContainText('未能确认操作结果');
  await page.reload();
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '任务', exact: true })).toHaveValue(task);
  await page.getByRole('button', { name: '开始运行实验' }).click();
  await expect(page).toHaveURL(new RegExp(created));
  await expect(page.locator('.run-header')).toContainText(task);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  const history = await (await page.request.get('/api/v1/runs')).json();
  expect(
    history.items.filter((run: { config: { task: string } }) => run.config.task === task),
  ).toHaveLength(1);
});

test('reports an explicitly unconfigured live provider without falling back to simulation', async ({
  page,
}) => {
  const modes: string[] = [];
  await page.route('**/api/v1/runs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    modes.push(route.request().postDataJSON().mode);
    await route.fulfill({ status: 503, json: { detail: 'provider_not_configured' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await page.getByRole('combobox', { name: '运行模式', exact: true }).selectOption('live');
  await expect(page.getByLabel('新建实验配置')).toContainText('可能产生提供商费用');
  await page.getByRole('button', { name: '开始运行实验' }).click();
  await expect(page.getByRole('alert')).toContainText('真实模型尚未配置');
  expect(modes).toEqual(['live']);
});

test('does not claim an injected failure when the model protocol never reaches the tool', async ({
  page,
}) => {
  const task = `协议未到工具 ${Date.now()}`;
  await page.request.post('http://127.0.0.1:8000/__test__/prepare', {
    data: { task, reject_protocol: true },
  });
  await page.goto('/');
  await configure(page, task);
  await page.getByRole('button', { name: '开始运行实验' }).click();
  await expect(page.locator('.run-header')).toContainText('执行失败');
  await expect(
    page.getByText('本次未到达目标工具，故障条件未触发；不纳入超时对比。', { exact: true }),
  ).toBeVisible();
  await expect(page.locator('.step-row')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '检查分支可用性', exact: true })).toHaveCount(0);
});

test('keeps the experiment form keyboard accessible and usable on narrow screens', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await configure(page, `窄屏实验 ${Date.now()}`);
  const form = page.getByLabel('新建实验配置');
  expect(
    (
      await new AxeBuilder({ page })
        .include('.experiment-panel')
        .withTags(['wcag2a', 'wcag2aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await form.getByRole('button', { name: '开始运行实验' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.run-header')).toContainText('窄屏实验');
});
