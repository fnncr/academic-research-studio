import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import EvidenceWorkspace from './EvidenceWorkspace';
import Manuscript from './Manuscript';
import { paragraph, type Revision } from './manuscript';
import { emptyMetadata, type SourceVersion } from './sources';
import { emptyPlan, type Evidence, type Plan } from './evidence';
const path = '/api/projects/p1';
const manuscript: Revision = { id: 'm1', project_id: 'p1', number: 1, parent_id: null, restored_from_id: null, content_hash: 'hash', created_at: '2026-11-03T10:00:00Z', document: { schema_version: '1', blocks: [{ id: 'h1', type: 'heading', level: 1, text: 'Обзор исследований' }, { ...paragraph('А🧪Б'), id: 'b1' }] } };
const version: SourceVersion = { id: 'v1', source_id: 's1', number: 1, metadata: { ...emptyMetadata(), title: 'Русская публикация', language: 'ru' }, verification: 'unverified', provenance: { kind: 'manual' }, created_at: manuscript.created_at };
const evidence = (id = 'e1', ver = version): Evidence => ({ id, source_version_id: ver.id, source_version: ver, content: { excerpt: 'А🧪Б', selection: { start: 1, end: 3, quote: '🧪' }, locator: { kind: 'page', label: '12' }, material: 'full_text_excerpt', note: '', rights_confirmed: true, original_language: ver.metadata.language }, verification: 'user_supplied_excerpt', locator_verification: 'unverified', full_text_verified: false });
const response = (value: unknown, status = 200) => ({ ok: status < 400, status, json: async () => value });
function server(initial: Evidence[] = [], initialPlan: Plan | null = null) {
  const data = { items: initial, plan: initialPlan, manuscript, history: initialPlan ? [initialPlan] : [], failPlan: false, loseEvidence: false, losePlan: false };
  const evidenceRequests = new Map<string, Evidence>(); const planRequests = new Map<string, Plan>();
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    const body = options?.body ? JSON.parse(String(options.body)) : null;
    if (options?.method === 'POST' && url === path + '/evidence') {
      let saved = evidenceRequests.get(body.request_id);
      if (!saved) { saved = { ...evidence('e' + (data.items.length + 1)), content: body, source_version_id: body.source_version_id }; data.items.unshift(saved); evidenceRequests.set(body.request_id, saved); }
      if (data.loseEvidence) { data.loseEvidence = false; throw new TypeError('Lost response'); } return response(saved, 201);
    }
    if (options?.method === 'POST' && url === path + '/research-plan/revisions') {
      const previous = planRequests.get(body.request_id); if (previous) return response(previous, 201);
      if (data.failPlan || body.base_revision_id !== (data.plan?.id ?? null)) return response({ detail: { message: 'План изменился в другой вкладке' } }, 409);
      const saved = { id: 'p' + (data.history.length + 1), number: data.history.length + 1, manuscript_revision_id: body.manuscript_revision_id, document: body.document, created_at: manuscript.created_at };
      data.plan = saved; data.history.unshift(saved); planRequests.set(body.request_id, saved);
      if (data.losePlan) { data.losePlan = false; throw new TypeError('Lost response'); } return response(saved, 201);
    }
    if (url === path + '/sources') return response([{ id: 's1', latest_version: version }]);
    if (url.startsWith(path + '/sources/s1/versions')) return response([{ ...version, id: 'v2', number: 2 }, version]);
    if (url === path + '/evidence') return response(data.items.map(({ source_version, ...item }) => item));
    if (url.startsWith(path + '/evidence/')) return response(data.items.find(i => url.endsWith('/' + i.id)));
    if (url === path + '/research-plan') return response(data.plan);
    if (url === path + '/research-plan/revisions') return response(data.history.map(({ document, ...p }) => p));
    if (url.startsWith(path + '/research-plan/revisions/')) return response(data.history.find(p => url.endsWith('/' + p.id)));
    if (url === path + '/manuscript') return response(data.manuscript);
    if (url === path + '/manuscript/revisions') return response([manuscript]);
    if (url.startsWith(path + '/manuscript/revisions/')) return response(manuscript);
    throw new Error('Unexpected request ' + url);
  });
  vi.stubGlobal('fetch', fetch); return { data, fetch };
}
async function open() { const dirty = vi.fn(); const view = render(<EvidenceWorkspace projectId="p1" manuscript={manuscript} manuscriptDirty={false} onDirty={dirty} />); await waitFor(() => expect(screen.getByRole('button', { name: 'Добавить научный тезис' })).toBeEnabled()); return { ...view, dirty, user: userEvent.setup() }; }
function selectText(label: string, start = 1, end = 3) { const field = screen.getByLabelText(label) as HTMLTextAreaElement; field.focus(); field.setSelectionRange(start, end); fireEvent.select(field); }
async function fillEvidence(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText('Источник доказательства'), 's1'); await waitFor(() => expect(screen.getByLabelText('Версия источника')).toHaveValue('v2')); await user.selectOptions(screen.getByLabelText('Версия источника'), 'v1');
  await user.clear(screen.getByLabelText('Язык оригинального фрагмента')); await user.type(screen.getByLabelText('Язык оригинального фрагмента'), 'ru'); await user.type(screen.getByLabelText('Оригинальный фрагмент'), 'А🧪Б'); selectText('Оригинальный фрагмент'); await user.type(screen.getByLabelText('Локатор'), '12'); await user.click(screen.getByLabelText('Имею право сохранить этот фрагмент'));
}
async function addClaim(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Добавить научный тезис' })); await user.type(screen.getByLabelText('Формулировка тезиса 1'), 'Сопоставление подходов'); await user.selectOptions(screen.getByLabelText('Раздел тезиса 1'), 'h1'); await user.selectOptions(screen.getByLabelText('Добавить доказательство к тезису 1'), 'e1');
}
async function addCitation(user: ReturnType<typeof userEvent.setup>) {
  const select = screen.getByLabelText('Тезис для цитирования') as HTMLSelectElement; await user.selectOptions(select, select.options[1].value); await user.selectOptions(screen.getByLabelText('Доказательство для цитирования'), 'e1'); await user.selectOptions(screen.getByLabelText('Фрагмент рукописи'), 'b1'); selectText('Выделите цитируемый текст рукописи'); await user.click(screen.getByRole('button', { name: 'Связать выделенный текст с доказательством' }));
}
describe('P4b scientific evidence', () => {
  it('source → evidence → claim → citation → save → reload → restore with stable IDs', async () => {
    const s = server(); let view = await open(); await fillEvidence(view.user); await view.user.click(screen.getByRole('button', { name: 'Сохранить доказательство' })); await screen.findByText(/Доказательство сохранено/);
    expect(s.data.items[0].source_version_id).toBe('v1'); expect(s.data.items[0].content.original_language).toBe('ru'); expect(s.data.items[0].content.selection).toEqual({ start: 1, end: 3, quote: '🧪' });
    await addClaim(view.user); await view.user.selectOptions(screen.getByLabelText('Отношение доказательства'), 'contradicts'); await addCitation(view.user); await view.user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' })); await screen.findByText('План: версия 1 сохранена.'); const first = structuredClone(s.data.plan!);
    view.unmount(); view = await open(); expect(screen.getByLabelText('Формулировка тезиса 1')).toHaveValue('Сопоставление подходов'); expect(screen.getByRole('heading', { name: 'Прямая цитата · рукопись 1' })).toBeVisible();
    await view.user.clear(screen.getByLabelText('Формулировка тезиса 1')); await view.user.type(screen.getByLabelText('Формулировка тезиса 1'), 'Уточнение'); await view.user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' })); await screen.findByText('План: версия 2 сохранена.');
    await view.user.click(screen.getByRole('button', { name: 'Просмотреть план 1' })); await view.user.click(await screen.findByRole('button', { name: 'Восстановить план 1 в черновик' })); await view.user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' })); await screen.findByText('План: версия 3 сохранена.'); expect(s.data.plan!.document).toEqual(first.document); expect(s.data.history[2]).toEqual(first); expect(s.fetch.mock.calls.every(([url]) => url.startsWith(path))).toBe(true);
  });
  it('retries evidence and plan after lost acknowledgement with the same UUID', async () => {
    const s = server(); const { user } = await open(); await fillEvidence(user); s.data.loseEvidence = true; await user.click(screen.getByRole('button', { name: 'Сохранить доказательство' })); await screen.findByRole('alert'); expect(screen.getByLabelText('Оригинальный фрагмент')).toHaveValue('А🧪Б'); await user.click(screen.getByRole('button', { name: 'Сохранить доказательство' })); await screen.findByText(/Доказательство сохранено/); expect(s.data.items).toHaveLength(1);
    await addClaim(user); s.data.losePlan = true; await user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' })); await screen.findByRole('alert'); await user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' })); await screen.findByText('План: версия 1 сохранена.'); expect(s.data.history).toHaveLength(1);
    for (const route of ['/evidence', '/research-plan/revisions']) { const calls = s.fetch.mock.calls.filter(([url, options]) => url === path + route && options?.method === 'POST'); expect(calls[0][1]!.body).toBe(calls[1][1]!.body); }
  });
  it('blocks stale manuscript ranges and explicitly clears anchors without altering history', async () => {
    const e = evidence(); const p: Plan = { id: 'p1', number: 1, manuscript_revision_id: 'm1', document: { ...emptyPlan(), claims: [{ id: 'c1', statement: 'Тезис', section_id: 'h1', evidence: [{ evidence_id: e.id, relation: 'supports', rationale: '' }] }], citations: [{ id: 'ct1', claim_id: 'c1', evidence_id: e.id, block_id: 'b1', selection: e.content.selection, kind: 'quotation' }] }, created_at: manuscript.created_at };
    const s = server([e], p); const view = await open(); vi.spyOn(window, 'confirm').mockReturnValue(true); const next = { ...manuscript, id: 'm2', number: 2 }; s.data.manuscript = next; view.rerender(<EvidenceWorkspace projectId="p1" manuscript={next} manuscriptDirty={false} onDirty={view.dirty} />);
    expect(screen.getByRole('button', { name: 'Сохранить версию научного плана' })).toBeDisabled(); await view.user.click(screen.getByRole('button', { name: 'Проверить привязки на новой версии' })); expect(screen.queryByRole('heading', { name: 'Прямая цитата · рукопись 1' })).toBeNull(); expect(screen.getByLabelText('Раздел тезиса 1')).toHaveValue(''); expect(p.document.citations).toHaveLength(1);
    await view.user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' })); await screen.findByText('План: версия 2 сохранена.'); expect(s.data.plan!.manuscript_revision_id).toBe('m2'); expect(s.data.history[1]).toEqual(p);
  });
  it('preserves the draft on conflict and requires comparison', async () => {
    const s = server([evidence()]); const { user } = await open(); await addClaim(user); s.data.failPlan = true; await user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' })); await screen.findByText(/Конфликт версий плана/); expect(screen.getByLabelText('Формулировка тезиса 1')).toHaveValue('Сопоставление подходов'); expect(screen.getByRole('button', { name: 'Сохранить версию научного плана' })).toBeDisabled(); await user.click(screen.getByRole('button', { name: 'Проверить актуальный научный план' })); await user.click(await screen.findByRole('button', { name: 'Сравнение выполнено: сохранить мой план новой версией' })); s.data.failPlan = false; await user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' })); await screen.findByText('План: версия 1 сохранена.');
  });
  it('supports Russian/foreign evidence and refuses a mismatching direct quote', async () => {
    const foreign = evidence('e2', { ...version, id: 'foreign', metadata: { ...version.metadata, title: 'Foreign study', language: 'en' } }); server([evidence(), foreign]); const { user, dirty } = await open(); await addClaim(user); await user.selectOptions(screen.getByLabelText('Отношение доказательства'), 'limits'); await user.selectOptions(screen.getByLabelText('Добавить доказательство к тезису 1'), 'e2'); expect(screen.getAllByLabelText('Отношение доказательства')).toHaveLength(2); await addCitation(user); selectText('Выделите цитируемый текст рукописи', 0, 1); expect(screen.getByRole('button', { name: 'Связать выделенный текст с доказательством' })).toBeDisabled(); await user.selectOptions(screen.getByLabelText('Тип цитирования'), 'paraphrase'); expect(screen.getByRole('button', { name: 'Связать выделенный текст с доказательством' })).toBeEnabled(); expect(dirty).toHaveBeenLastCalledWith(true); const close = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(close); expect(close.defaultPrevented).toBe(true);
  });
  it('opens from P2 and blocks editing when the manuscript has unsaved changes', async () => {
    server(); const user = userEvent.setup(); render(<Manuscript projectId="p1" onDirty={vi.fn()} />); await user.click(await screen.findByRole('button', { name: 'Открыть научные доказательства' })); await screen.findByLabelText('Источник доказательства'); await user.type(screen.getByLabelText('Текст блока 2'), 'Правка'); expect(screen.getByRole('button', { name: 'Добавить научный тезис' })).toBeDisabled();
  });
  it('detects a manuscript changed in another tab before any plan write', async () => {
    const s = server([evidence()]); const { user } = await open(); await addClaim(user);
    s.data.manuscript = { ...manuscript, id: 'm2', number: 2 };
    await user.click(screen.getByRole('button', { name: 'Сохранить версию научного плана' }));
    await screen.findByText(/Загрузите актуальный текст в редакторе P2/);
    expect(s.fetch.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Сохранить версию научного плана' })).toBeDisabled();
  });
  it('loads evidence referenced by a plan even when it is outside the first library page', async () => {
    const e = evidence(); const p: Plan = { id: 'p1', number: 1, manuscript_revision_id: 'm1', document: { ...emptyPlan(), claims: [{ id: 'c1', statement: 'Старое доказательство', section_id: null, evidence: [{ evidence_id: e.id, relation: 'limits', rationale: '' }] }] }, created_at: manuscript.created_at };
    const s = server([e], p); const original = s.fetch.getMockImplementation()!;
    s.fetch.mockImplementation((url, options) => url === path + '/evidence' && !options ? Promise.resolve(response([])) : original(url, options));
    await open(); expect(screen.getByLabelText('Формулировка тезиса 1')).toHaveValue('Старое доказательство');
    expect(s.fetch.mock.calls.some(([url]) => url === path + '/evidence/e1')).toBe(true);
  });
  it('offers retry after initial storage failure without enabling an empty plan', async () => {
    const s = server(); s.fetch.mockRejectedValueOnce(new TypeError('Offline'));
    const user = userEvent.setup(); render(<EvidenceWorkspace projectId="p1" manuscript={manuscript} manuscriptDirty={false} onDirty={vi.fn()} />);
    await screen.findByRole('alert'); expect(screen.queryByRole('button', { name: 'Сохранить версию научного плана' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Повторить загрузку доказательств' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Добавить научный тезис' })).toBeEnabled());
  });

});
