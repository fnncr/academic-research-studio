import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Manuscript from './Manuscript';
import ExportPanel, { type Profile } from './ExportPanel';
const path = '/api/projects/p1/exports';
const profile: Profile = { name: 'Пример A4', paper: 'A4', font: 'Times New Roman', font_size: 14, line_spacing: 1.5, alignment: 'justify', first_line_cm: 1.25, margin_top_cm: 2, margin_bottom_cm: 2, margin_left_cm: 3, margin_right_cm: 1.5, paragraph_after_pt: 0, header: '', footer: '', page_numbers: true, toc: true, number_tables: true };
const report = { can_export: true, preflight_token: 'a'.repeat(64), errors: [] as { code: string; message: string }[], warnings: [{ code: 'unverified', message: 'Локаторы требуют проверки автора.' }], info: [{ code: 'toc', message: 'Обновите поля оглавления в Word.' }], manifest: {} };
const response = (value: unknown, status = 200) => ({ ok: status < 400, status, json: async () => value, blob: async () => new Blob(['docx'], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }) });
function mockServer() {
  const data = { report, downloadError: false };
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === path + '/options') return response({ profiles: [{ id: 'example', description: 'Пользовательский профиль, не стандарт университета.', profile }], citation_styles: [{ id: 'numeric-v1', label: 'Числовой, не ГОСТ' }] });
    if (url === '/api/projects/p1/manuscript/revisions') return response([{ id: 'm2', number: 2, created_at: '2026-11-04T00:00:00Z' }, { id: 'm1', number: 1, created_at: '2026-11-03T00:00:00Z' }]);
    if (url === '/api/projects/p1/research-plan/revisions') return response([{ id: 'plan2', number: 2, manuscript_revision_id: 'm2' }]);
    if (url === path + '/preflight') return response(data.report);
    if (url === path + '/docx') return data.downloadError ? response({ detail: { message: 'Повторите предварительную проверку.' } }, 409) : response(null);
    throw new Error('Unexpected route ' + url);
  });
  vi.stubGlobal('fetch', fetch); Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:test') }); Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() }); vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  return { data, fetch };
}
async function open(unsaved = false) {
  const dirty = vi.fn(); const view = render(<ExportPanel projectId="p1" unsaved={unsaved} onDirty={dirty} />); await screen.findByLabelText('Стиль цитирования'); return { ...view, dirty, user: userEvent.setup() };
}
async function choose(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText('Стиль цитирования'), 'numeric-v1'); await user.selectOptions(screen.getByLabelText('Научный план для экспорта'), 'plan2'); await user.click(screen.getByLabelText('Добавить титульный лист'));
}
describe('Word export screen', () => {
  it('selects saved versions, checks warnings, downloads DOCX and invalidates changed settings', async () => {
    const s = mockServer(); const { user } = await open(); expect(screen.getByLabelText('Версия рукописи для экспорта')).toHaveValue('m2'); expect(screen.getByRole('button', { name: 'Проверить перед экспортом' })).toBeDisabled(); await choose(user);
    await user.click(screen.getByRole('button', { name: 'Проверить перед экспортом' })); await screen.findByText('Локаторы требуют проверки автора.'); await user.click(screen.getByRole('button', { name: 'Создать и скачать DOCX' })); await screen.findByText(/DOCX создан/);
    expect(URL.createObjectURL).toHaveBeenCalled(); const call = s.fetch.mock.calls.find(([url]) => url === path + '/docx')!; const body = JSON.parse(String(call[1]!.body)); expect(body.manuscript_revision_id).toBe('m2'); expect(body.plan_revision_id).toBe('plan2'); expect(body.preflight_token).toBe(report.preflight_token);
    await user.clear(screen.getByLabelText('Верхний колонтитул')); await user.type(screen.getByLabelText('Верхний колонтитул'), 'Новый заголовок'); expect(screen.getByRole('button', { name: 'Создать и скачать DOCX' })).toBeDisabled(); expect(screen.getByText(/Параметры изменились/)).toBeVisible();
  });
  it('shows blocking report and never requests DOCX when references are invalid', async () => {
    const s = mockServer(); s.data.report = { ...report, can_export: false, errors: [{ code: 'stale_plan', message: 'План относится к другой версии.' }] }; const { user } = await open(); await choose(user); await user.click(screen.getByRole('button', { name: 'Проверить перед экспортом' })); await screen.findByText('План относится к другой версии.'); expect(screen.getByRole('button', { name: 'Создать и скачать DOCX' })).toBeDisabled(); expect(s.fetch.mock.calls.some(([url]) => url === path + '/docx')).toBe(false);
  });
  it('requires explicit acknowledgement of unsaved changes without transmitting drafts', async () => {
    const s = mockServer(); const view = await open(true); await choose(view.user); expect(screen.getByRole('button', { name: 'Проверить перед экспортом' })).toBeDisabled(); await view.user.click(screen.getByLabelText('Понимаю: экспортировать только выбранные сохранённые версии')); await view.user.click(screen.getByRole('button', { name: 'Проверить перед экспортом' })); await screen.findByText(/Проверка пройдена/); const call = s.fetch.mock.calls.find(([url]) => url === path + '/preflight')!; expect(JSON.parse(String(call[1]!.body))).not.toHaveProperty('document'); expect(s.fetch.mock.calls.every(([url]) => url.startsWith('/api/projects/p1/'))).toBe(true);
  });
  it('requires an explicit no-plan choice and preserves entered title fields on server failure', async () => {
    const s = mockServer(); const { user, dirty } = await open(); await user.type(screen.getByLabelText('ФИО автора'), 'Тестовый Автор'); await user.selectOptions(screen.getByLabelText('Стиль цитирования'), 'numeric-v1'); await user.click(screen.getByLabelText('Явно экспортировать без научного плана и автоматических ссылок')); await user.click(screen.getByRole('button', { name: 'Проверить перед экспортом' })); await screen.findByText(/Проверка пройдена/); s.data.downloadError = true; await user.click(screen.getByRole('button', { name: 'Создать и скачать DOCX' })); await screen.findByText('Повторите предварительную проверку.'); expect(screen.getByLabelText('ФИО автора')).toHaveValue('Тестовый Автор'); expect(dirty).toHaveBeenLastCalledWith(true); const close = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(close); expect(close.defaultPrevented).toBe(true);
  });
  it('opens inside P2 and warns after an unsaved manuscript edit', async () => {
    const s = mockServer(); const original = s.fetch.getMockImplementation()!;
    s.fetch.mockImplementation((url, options) => url === '/api/projects/p1/manuscript' ? Promise.resolve(response({ id: 'm2', number: 2, document: { schema_version: '1', blocks: [{ id: 'b1', type: 'paragraph', text: 'Сохранённый текст', marks: [], origin: 'manual', page: null }] } })) : original(url, options));
    const user = userEvent.setup(); render(<Manuscript projectId="p1" onDirty={vi.fn()} />);
    await user.click(await screen.findByRole('button', { name: 'Открыть экспорт Word' }));
    await screen.findByLabelText('Стиль цитирования'); await user.type(screen.getByLabelText('Текст блока 1'), ' Черновик');
    expect(screen.getByText('Есть несохранённые изменения рукописи или доказательств. Они не попадут в DOCX.')).toBeVisible();
  });

});
