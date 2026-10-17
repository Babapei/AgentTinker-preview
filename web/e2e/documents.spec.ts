import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

async function createDocument(page: Page) {
  const response = await page.request.post('/api/v1/scenarios/document-missing/runs', {
    headers: { 'Idempotency-Key': `document-${Date.now()}-${Math.random()}` },
    data: { mode: 'synthetic' },
  });
  expect(response.status()).toBe(201);
  const id = (await response.json()).run.run_id;
  await expect
    .poll(async () => (await (await page.request.get(`/api/v1/runs/${id}`)).json()).run.status)
    .toBe('succeeded');
  await page.goto(`/?run=${id}`);
  await expect(page.getByRole('button', { name: '运行规则评价', exact: true })).toBeEnabled();
  return id;
}

async function evaluate(page: Page) {
  await page.getByRole('button', { name: '运行规则评价', exact: true }).click();
  await expect(page.getByLabel('人工复核表单')).toBeVisible();
}

async function fillReview(page: Page) {
  const form = page.getByLabel('人工复核表单');
  await form.getByLabel('复核者署名（本地填写）').fill('浏览器离线测试');
  await form.getByLabel('Version 2 新增可配置的工具重试。').selectOption('covered');
  await form.getByLabel('Version 2 修复引用缺失问题。').selectOption('missing');
  await form.getByLabel('人工判断').selectOption('justified_insufficiency');
  await form.getByLabel('复核说明').fill('测试意见：回答如实指出缺少引用修复材料。');
}

test('creates the selected document scenario, evaluates A, reviews honestly and forks only top_k', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await page.getByRole('combobox', { name: '实验场景', exact: true }).selectOption('document');
  const composer = page.getByLabel('新建文档实验配置');
  await expect(composer).toContainText('top_k=2');
  await composer.getByLabel('运行模式').selectOption('synthetic');
  await composer.getByRole('button', { name: '开始运行实验', exact: true }).click();
  await expect(page.locator('.record-connection')).toContainText('事件已核对');
  const a = new URL(page.url()).searchParams.get('run')!;
  const original = await (await page.request.get(`/api/v1/runs/${a}`)).json();
  await evaluate(page);
  const panel = page.getByLabel('文档证据与答案评价');
  await expect(panel).toContainText('必需文档是否返回：未满足');
  await expect(panel).toContainText('人工答案评价：未复核');
  await fillReview(page);
  await page.getByRole('button', { name: '保存人工复核', exact: true }).click();
  await expect(panel.locator('.human-review')).toContainText('材料不足，回答如实说明');
  await page.getByRole('button', { name: '检查分支可用性', exact: true }).click();
  await expect(page.getByLabel('只修改一个参数')).toHaveValue('top_k');
  await expect(page.locator('.patch-summary')).toContainText('2 → 3');
  await page.getByRole('button', { name: '创建分支并运行', exact: true }).click();
  await expect(page.locator('.run-header')).toContainText('执行成功');
  const b = new URL(page.url()).searchParams.get('run')!;
  expect(a).not.toBe(b);
  const comparison = page.getByLabel('A/B 运行对比');
  await expect(comparison).toContainText('实际只改一个执行器参数');
  await expect(comparison).not.toContainText('配置或来源不满足单变量对照');
  await expect(comparison).not.toContainText('未触发故障时不纳入超时结论');
  await evaluate(page);
  await expect(page.getByLabel('文档证据与答案评价')).toContainText('必需正文是否读取：通过');
  expect(await (await page.request.get(`/api/v1/runs/${a}`)).json()).toEqual(original);
  expect((await (await page.request.get(`/api/v1/runs/${a}/reviews`)).json()).total).toBe(1);
});

test('retries a lost evaluation response after reload with the same durable identity', async ({
  page,
}) => {
  const id = await createDocument(page);
  await page.route(`**/api/v1/runs/${id}/evaluations`, async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fetch();
    await route.abort('failed');
  });
  await page.getByRole('button', { name: '运行规则评价', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('未能确认操作结果');
  expect((await (await page.request.get(`/api/v1/runs/${id}/evaluations`)).json()).total).toBe(1);
  await page.unroute(`**/api/v1/runs/${id}/evaluations`);
  await page.reload();
  await page.getByRole('button', { name: '重试未确认规则评价', exact: true }).click();
  await expect(page.getByRole('button', { name: '新增一份规则评价', exact: true })).toBeEnabled();
  expect((await (await page.request.get(`/api/v1/runs/${id}/evaluations`)).json()).total).toBe(1);
});

test('restores a lost human review without duplicating or changing its evidence anchor', async ({
  page,
}) => {
  const id = await createDocument(page);
  await evaluate(page);
  await fillReview(page);
  await page.route(`**/api/v1/runs/${id}/reviews`, async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fetch();
    await route.abort('failed');
  });
  await page.getByRole('button', { name: '保存人工复核', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('未能确认操作结果');
  const original = (await (await page.request.get(`/api/v1/runs/${id}/reviews`)).json()).items[0];
  await page.unroute(`**/api/v1/runs/${id}/reviews`);
  await page.reload();
  const form = page.getByLabel('人工复核表单');
  await expect(form.getByLabel('复核者署名（本地填写）')).toHaveValue('浏览器离线测试');
  await expect(form.getByLabel('人工判断')).toHaveValue('justified_insufficiency');
  await form.getByRole('button', { name: '保存人工复核', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '人工意见已保存' })).toBeVisible();
  const stored = await (await page.request.get(`/api/v1/runs/${id}/reviews`)).json();
  expect(stored.total).toBe(1);
  expect(stored.items[0]).toEqual(original);
});

test('hides later assessments during playback and reuses cached reads without execution', async ({
  page,
}) => {
  const id = await createDocument(page);
  await evaluate(page);
  await expect(page.locator('.record-connection')).toContainText('事件已核对');
  await expect(page.getByRole('button', { name: '刷新评价记录' })).toBeEnabled();
  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/')) requests.push(request.url());
  });
  await page.getByRole('button', { name: '回到第一个事件' }).click();
  const panel = page.getByLabel('文档证据与答案评价');
  await expect(panel).toContainText('结束后的评价与人工复核在这里隐藏');
  await expect(panel.locator('.evidence-checks')).toHaveCount(0);
  await page.getByRole('button', { name: /返回最新/ }).click();
  await expect(panel).toContainText('必需文档是否返回：未满足');
  expect(requests).toEqual([]);
  expect((await (await page.request.get(`/api/v1/runs/${id}/evaluations`)).json()).total).toBe(1);
});

test('keeps the document form and assessment controls accessible on narrow screens', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await page.getByRole('combobox', { name: '实验场景', exact: true }).selectOption('document');
  await expect(page.getByLabel('新建文档实验配置')).toContainText('任务：');
  expect(
    (
      await new AxeBuilder({ page })
        .include('.scenario-picker')
        .include('[aria-label="新建文档实验配置"]')
        .analyze()
    ).violations,
  ).toEqual([]);
  await createDocument(page);
  await evaluate(page);
  expect((await new AxeBuilder({ page }).include('main').analyze()).violations).toEqual([]);
  await page.screenshot({
    path: '../artifacts/m4-document-evaluation-desktop.png',
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByLabel('人工判断')).toBeVisible();
  await page.screenshot({ path: '../artifacts/m4-document-evaluation-mobile.png', fullPage: true });
});

test('restores a lost document creation request in its scenario after reload', async ({ page }) => {
  let createdId = '';
  const routePattern = '**/api/v1/scenarios/document-missing/runs';
  await page.route(routePattern, async (route) => {
    const response = await route.fetch();
    createdId = (await response.json()).run.run_id;
    await route.abort('failed');
  });
  await page.goto('/');
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await page.getByRole('combobox', { name: '实验场景', exact: true }).selectOption('document');
  await page.getByLabel('新建文档实验配置').getByLabel('运行模式').selectOption('synthetic');
  await page.getByRole('button', { name: '开始运行实验', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('未能确认操作结果');
  await page.unroute(routePattern);
  await page.reload();
  await page.getByRole('button', { name: '新建实验', exact: true }).click();
  await expect(page.getByRole('combobox', { name: '实验场景', exact: true })).toHaveValue(
    'document',
  );
  await expect(page.getByLabel('新建文档实验配置')).toContainText('已恢复未确认的文档请求');
  await page.getByRole('button', { name: '开始运行实验', exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('run')).toBe(createdId);
  const history = await (await page.request.get('/api/v1/runs')).json();
  expect(history.items.filter((run: { run_id: string }) => run.run_id === createdId)).toHaveLength(
    1,
  );
});

test('does not claim a selected answer is unreviewed before all opinion pages are read', async ({
  page,
}) => {
  const id = await createDocument(page);
  const route = `/api/v1/runs/${id}`;
  const evaluation = async (key: string) =>
    await (
      await page.request.post(`${route}/evaluations`, {
        headers: { 'Idempotency-Key': key },
        data: {},
      })
    ).json();
  const a = await evaluation(`pagination-a-${id}`),
    b = await evaluation(`pagination-b-${id}`);
  for (let i = 0; i < 52; i++) {
    const anchor = i === 0 ? a : b;
    const response = await page.request.post(`${route}/reviews`, {
      headers: { 'Idempotency-Key': `pagination-review-${id}-${i}` },
      data: {
        evaluation_id: anchor.evaluation_id,
        input_hash: anchor.input_hash,
        reviewer: '分页离线测试',
        judgement: 'uncertain',
        fact_coverage: { 'configurable-retries': 'uncertain', 'citation-fix': 'uncertain' },
        explanation: `分页测试意见 ${i}`,
      },
    });
    expect(response.status()).toBe(201);
  }
  await page.reload();
  const panel = page.getByLabel('文档证据与答案评价');
  await panel.getByLabel('查看规则评价').selectOption(a.evaluation_id);
  await expect(panel).toContainText('人工意见尚未读齐');
  await expect(panel).toContainText('已载入 50 / 52');
  await panel.getByRole('button', { name: '加载更多人工意见' }).click();
  await expect(panel).toContainText('已载入 52 / 52');
  await expect(panel).toContainText('已有人工意见，见下方独立记录');
});
