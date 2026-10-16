import { expect, test } from '@playwright/test';
import type { RuntimeEvent } from '../src/protocol';

const frame = (event: RuntimeEvent) =>
  `id: ${event.run_id}:${event.seq}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;

test('reconnects from the applied cursor and follows a native run through completion', async ({
  page,
}) => {
  const started = await page.request.post('http://127.0.0.1:8000/__test__/runs');
  const { run_id: id } = await started.json();
  try {
    const response = await page.request.get(`http://127.0.0.1:8000/__test__/runs/${id}/events`);
    const facts: RuntimeEvent[] = await response.json();
    const after: number[] = [];
    await page.route(`**/api/v1/runs/${id}/events?*`, async (route) => {
      after.push(Number(new URL(route.request().url()).searchParams.get('after_seq')));
      if (after.length === 1) {
        // Actual durable prefix, duplicate delivery, then a real closed connection.
        await route.fulfill({
          contentType: 'text/event-stream',
          body: [facts[0], facts[1], facts[1]].map(frame).join(''),
        });
      } else await route.continue();
    });
    const writes: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/') && request.method() !== 'GET') writes.push(request.url());
    });
    await page.goto(`/?run=${id}`);
    await expect.poll(() => after.length).toBeGreaterThanOrEqual(2);
    expect(after.slice(0, 2)).toEqual([0, 2]);
    await expect(page.locator('.run-header')).toContainText('运行中');
    await page.request.post(`http://127.0.0.1:8000/__test__/runs/${id}/release`);
    await expect(page.locator('.run-header')).toContainText('执行成功');
    await expect(page.locator('.record-connection')).toContainText('事件已核对');
    await expect(page.locator('.step-row')).toHaveCount(4);
    const current = await page.request.get(`/api/v1/runs/${id}`);
    const view = await current.json();
    await expect(page.locator('.record-connection code')).toHaveText(`#${view.last_seq}`);
    expect(writes).toEqual([]);
    expect(view.run.status).toBe('succeeded');
  } finally {
    await page.request.post(`http://127.0.0.1:8000/__test__/runs/${id}/release`);
  }
});

test('switching away disconnects the subscriber without cancelling the underlying run', async ({
  page,
}) => {
  const started = await page.request.post('http://127.0.0.1:8000/__test__/runs');
  const { run_id: id } = await started.json();
  try {
    await page.goto(`/?run=${id}`);
    await expect(page.locator('.record-connection')).toContainText('正在跟随');
    await page
      .getByLabel('选择运行记录')
      .getByRole('button', { name: /基线：首次检索超时/ })
      .click();
    await expect(page.locator('.run-header')).toContainText('基线：首次检索超时');
    const stillRunning = await page.request.get(`/api/v1/runs/${id}`);
    expect((await stillRunning.json()).run.status).toBe('running');
    await page.request.post(`http://127.0.0.1:8000/__test__/runs/${id}/release`);
    await expect
      .poll(async () => (await (await page.request.get(`/api/v1/runs/${id}`)).json()).run.status)
      .toBe('succeeded');
    await expect(page.locator('.run-header')).toContainText('基线：首次检索超时');
  } finally {
    await page.request.post(`http://127.0.0.1:8000/__test__/runs/${id}/release`);
  }
});
