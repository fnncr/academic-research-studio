// Real Chromium + real local API/PostgreSQL. No mocked browser routes.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const output = process.argv[2];
const seed = JSON.parse(fs.readFileSync(path.join(output, 'seed.json')));
const token = 'test-owner-token-for-task-a-only-123456789'; // public, disposable fixture only
const base = 'http://127.0.0.1:5173';

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [], external = [], enqueues = [];
  page.on('pageerror', e => errors.push(e.message));
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) { external.push(url.origin); return route.abort(); }
    if (route.request().method() === 'POST' && url.pathname.endsWith('/model-jobs')) enqueues.push(route.request().postDataJSON());
    return route.continue();
  });
  async function api(suffix, data, method = 'GET') {
    const response = await page.request.fetch(base + seed.path + suffix, {
      method, headers: { Authorization: 'Bearer ' + token }, ...(data ? { data } : {}),
    });
    assert(response.ok(), `${suffix}: HTTP ${response.status()}`);
    return response.json();
  }
  async function openAssistant() {
    await page.getByRole('button', { name: 'Проекты', exact: true }).click();
    await page.getByRole('button', { name: 'Курсовая', exact: true }).click();
    await page.getByRole('button', { name: 'Открыть рукопись', exact: true }).click();
    await page.getByRole('button', { name: 'Открыть AI Research Assistant', exact: true }).click();
    await page.getByLabel('Ключ владельца помощника').fill(token);
    await page.getByRole('button', { name: 'Подключить помощника / восстановить задачи' }).click();
    await page.getByLabel('Провайдер и модель').waitFor();
  }
  try {
    await api('/model-jobs/budget', { request_id: crypto.randomUUID(), evidence_ref: 'Synthetic browser audit', acknowledged: true, limit_units: 100000 }, 'PUT');
    await page.goto(base);
    await openAssistant();
    const assistant = page.locator('.model-assistant');
    await assistant.getByLabel(/^Версия рукописи/).selectOption(seed.manuscript.id);
    await assistant.getByLabel('Тестовый тезис', { exact: true }).check();
    await assistant.getByLabel('Название нового раздела').fill('Аудит — synthetic section');
    await assistant.getByRole('button', { name: 'Предпросмотр контекста и стоимости' }).click();
    const send = assistant.getByRole('button', { name: 'Создать задание', exact: true });
    await send.waitFor();
    assert(await send.isDisabled(), 'Consent must be explicit');
    await assistant.getByRole('checkbox', { name: 'Разрешаю этот конкретный запрос', exact: false }).focus();
    await page.keyboard.press('Space'); // keyboard activation of native consent
    await send.click();
    await assistant.getByRole('heading', { name: 'Предложение: смысловая проверка', exact: false }).waitFor();
    assert.equal(enqueues.length, 1);
    const request = enqueues[0].task.request_id;
    let job = await api('/model-jobs/by-request/' + request);
    job = await api('/model-jobs/' + job.id + '/result');
    assert.equal(job.state, 'succeeded');
    await page.reload();
    await openAssistant();
    await page.getByRole('heading', { name: 'Предложение: смысловая проверка', exact: false }).waitFor();
    assert.equal(enqueues.length, 1, 'Reload must only recover by UUID/read');
    const stored = await page.evaluate(() => Object.values(sessionStorage).join('\n'));
    assert(stored.includes(request) && !stored.includes(token));
    assert(await assistant.getByText(/Противоречит/).count() > 0);
    // Review creation is API-only today. Record this UI gap, do not pretend a UI button exists.
    const reviewTask = { ...job.task, request_id: crypto.randomUUID(), kind: 'semantic_review',
      max_output_tokens: 8000, review_job_id: job.id,
      review_result_hash: require('node:crypto').createHash('sha256').update(canonical(job.result)).digest('hex') };
    const preview = await api('/model-jobs/preview', reviewTask, 'POST');
    const review = await api('/model-jobs', { task: reviewTask, consent: { fingerprint: preview.fingerprint, approved: true } }, 'POST');
    let reviewed;
    for (let i = 0; i < 40; i++) {
      reviewed = await api('/model-jobs/' + review.id + '/result');
      if (reviewed.state === 'succeeded') break;
      await new Promise(r => setTimeout(r, 250));
    }
    assert.equal(reviewed.result.status, 'uncertain');
    await assistant.getByRole('checkbox', { name: 'Я проверил текст, Evidence, противоречия и ограничения' }).check();
    await assistant.getByRole('button', { name: 'Принять текст новой версией' }).click();
    await assistant.getByText('Уже принято:', { exact: false }).waitFor();
    const accepted = await api('/manuscript');
    assert.notEqual(accepted.id, seed.manuscript.id);
    assert.deepEqual(accepted.document.blocks.slice(0, seed.manuscript.document.blocks.length), seed.manuscript.document.blocks);
    const plan = await api('/research-plan');
    await assistant.screenshot({ path: path.join(output, 'assistant-desktop.png') });
    await page.getByRole('button', { name: 'Открыть экспорт Word', exact: true }).click();
    await page.getByLabel('Научный план для экспорта').selectOption(plan.id);
    await page.getByLabel('Стиль цитирования').selectOption('numeric-v1');
    await page.getByLabel('Добавить титульный лист').uncheck();
    await page.getByRole('button', { name: 'Проверить перед экспортом' }).click();
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Создать и скачать DOCX' }).click();
    await (await downloadEvent).saveAs(path.join(output, 'browser-accepted.docx'));
    await page.getByRole('button', { name: 'Сравнить версию 2', exact: true }).click();
    await page.getByRole('button', { name: 'Восстановить версию 2 в черновик', exact: true }).click();
    await assistant.getByText('Есть несохранённые изменения рукописи или плана.', { exact: false }).waitFor();
    const savedResponse = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/manuscript/revisions'));
    await page.getByRole('button', { name: 'Сохранить версию рукописи', exact: true }).click();
    assert.equal((await savedResponse).status(), 201);
    const restored = await api('/manuscript');
    assert.deepEqual(restored.document, seed.manuscript.document);
    assert.equal(restored.restored_from_id, seed.manuscript.id);
    assert.deepEqual(await api('/manuscript/revisions/' + accepted.id), accepted);
    assert.equal((await api('/research-plan')).manuscript_revision_id, accepted.id, 'No automatic citation rebase on restoration');
    await page.setViewportSize({ width: 390, height: 844 });
    await assistant.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'assistant-mobile.png') });
    const overflow = await assistant.evaluate(e => e.scrollWidth > e.clientWidth + 2);
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    const result = { browser: await browser.version(), mock_only: true, request_uuid_restored: request,
      browser_enqueues: enqueues.length, semantic_review: reviewed.result.status, review_creation: 'API only; UI control absent',
      manuscript_before: seed.manuscript.id, manuscript_after: accepted.id,
      original_blocks_preserved: true, docx_downloaded: true, restored_as_new_revision: restored.id,
      accepted_archive_unchanged: true, old_citations_not_rebased: true, mobile_assistant_overflow: overflow,
      page_errors: errors, external_browser_requests: external };
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    fs.writeFileSync(path.join(output, 'failure.txt'), await page.locator('body').innerText());
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
