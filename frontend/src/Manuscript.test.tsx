import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Manuscript from './Manuscript';
import Projects from './Projects';
import { diffDocuments, documentProblem, emptyDocument, importedBlocks, newBlock, paragraph, sameDocument, type ManuscriptDocument, type Revision } from './manuscript';

const path = '/api/projects/p1/manuscript';
const response = (data: unknown, status = 200) => ({ ok: status < 400, status, json: async () => data });
function revision(doc: ManuscriptDocument, number = 1): Revision {
  return { id: `r${number}`, project_id: 'p1', number, parent_id: number > 1 ? `r${number - 1}` : null, restored_from_id: null, content_hash: 'hash', created_at: '2026-11-03T10:00:00Z', document: doc };
}
function mockServer(initial: Revision | null = null) {
  let latest = initial;
  const revisions: Revision[] = initial ? [initial] : [];
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      const body = JSON.parse(options.body as string);
      if (body.base_revision_id !== (latest?.id ?? null)) return response({ detail: { message: 'Конфликт версии' } }, 409);
      latest = revision(body.document, (latest?.number ?? 0) + 1); latest.restored_from_id = body.restored_from_id;
      revisions.unshift(latest); return response(latest, 201);
    }
    if (url === path) return response(latest);
    if (url.startsWith(`${path}/revisions/`)) return response(revisions.find(r => url.endsWith('/' + r.id)));
    if (url.startsWith(`${path}/revisions`)) return response(revisions.map(({ document, ...summary }) => summary));
    throw new Error(`Unexpected route ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { fetchMock, revisions, getLatest: () => latest, advance: (next: Revision) => { latest = next; revisions.unshift(next); } };
}
async function openEditor() {
  const dirty = vi.fn(); render(<Manuscript projectId="p1" onDirty={dirty} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Добавить: Абзац' })).toBeEnabled());
  return { user: userEvent.setup(), dirty };
}

describe('manual manuscript', () => {
  it('creates a plan, Unicode text, table and citation placeholder without a model', async () => {
    const server = mockServer(); const { user, dirty } = await openEditor();
    await user.click(screen.getByRole('button', { name: 'Добавить: Заголовок' }));
    await user.type(screen.getByLabelText('Текст заголовка'), 'Гипотеза');
    await user.click(screen.getByRole('button', { name: 'Добавить: Абзац' }));
    await user.type(screen.getByLabelText('Текст блока 2'), 'Кириллица ё и 🧪');
    await user.click(screen.getByRole('button', { name: 'Добавить: Таблица' }));
    await user.type(screen.getByLabelText('Строка 1, столбец 1'), 'Показатель');
    await user.type(screen.getByLabelText('Строка 2, столбец 2'), '−1,25');
    await user.click(screen.getByRole('button', { name: 'Добавить: Заготовка ссылки' }));
    await user.type(screen.getByLabelText('Источник или задача поиска'), 'Проверить источник');
    expect(dirty).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole('button', { name: 'Сохранить версию рукописи' }));
    expect(await screen.findByText('Рукопись: версия 1 сохранена.')).toBeVisible();
    const doc = server.getLatest()!.document;
    expect(doc.blocks.map(b => b.type)).toEqual(['heading', 'paragraph', 'table', 'citation_placeholder']);
    expect(JSON.stringify(doc)).toContain('Кириллица ё и 🧪');
    expect(JSON.stringify(doc)).toContain('−1,25');
    expect(screen.getByRole('link', { name: 'Гипотеза' })).toHaveAttribute('href', '#block-' + doc.blocks[0].id);
    expect(dirty).toHaveBeenLastCalledWith(false);
  });

  it('preserves node IDs through move, undo and redo', async () => {
    const a = paragraph('Первый'); const b = paragraph('Второй');
    const server = mockServer(revision({ schema_version: '1', blocks: [a, b] })); const { user } = await openEditor();
    const second = screen.getByRole('region', { name: 'Блок 2: Абзац' });
    await user.click(within(second).getByRole('button', { name: 'Выше' }));
    expect(screen.getByLabelText('Текст блока 1')).toHaveValue('Второй');
    await user.click(screen.getByRole('button', { name: 'Отменить изменение' }));
    expect(screen.getByLabelText('Текст блока 1')).toHaveValue('Первый');
    await user.click(screen.getByRole('button', { name: 'Повторить изменение' }));
    await user.click(screen.getByRole('button', { name: 'Сохранить версию рукописи' }));
    expect(await screen.findByText('Рукопись: версия 2 сохранена.')).toBeVisible();
    expect(server.getLatest()!.document.blocks.map(n => n.id)).toEqual([b.id, a.id]);
  });

  it('requires comparison before saving a conflicting draft and never replaces it silently', async () => {
    const block = paragraph('База'); const doc = { schema_version: '1' as const, blocks: [block] };
    const server = mockServer(revision(doc)); const { user } = await openEditor();
    await user.clear(screen.getByLabelText('Текст блока 1'));
    await user.type(screen.getByLabelText('Текст блока 1'), 'Мой текст');
    server.advance(revision({ ...doc, blocks: [{ ...block, text: 'Другая вкладка' }] }, 2));
    await user.click(screen.getByRole('button', { name: 'Сохранить версию рукописи' }));
    expect(await screen.findByText('Конфликт версии')).toBeVisible();
    expect(screen.getByLabelText('Текст блока 1')).toHaveValue('Мой текст');
    expect(screen.getByRole('button', { name: 'Сохранить версию рукописи' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Проверить актуальную версию' }));
    expect(await screen.findByText(/Другая вкладка/)).toBeVisible();
    expect(screen.getByLabelText('Текст блока 1')).toHaveValue('Мой текст');
    await user.click(screen.getByRole('button', { name: /Сравнение выполнено/ }));
    await user.click(screen.getByRole('button', { name: 'Сохранить версию рукописи' }));
    expect(await screen.findByText('Рукопись: версия 3 сохранена.')).toBeVisible();
    expect(server.getLatest()!.parent_id).toBe('r2');
    expect(server.getLatest()!.document.blocks[0]).toEqual({ ...block, text: 'Мой текст' });
  });

  it('reuses the request ID after an unknown network outcome', async () => {
    const server = mockServer(); const { user } = await openEditor();
    await user.click(screen.getByRole('button', { name: 'Добавить: Абзац' }));
    await user.type(screen.getByLabelText('Текст блока 1'), 'Сохранить');
    server.fetchMock.mockRejectedValueOnce(new TypeError('Network'));
    await user.click(screen.getByRole('button', { name: 'Сохранить версию рукописи' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Соединение прервано');
    expect(screen.getByLabelText('Текст блока 1')).toHaveValue('Сохранить');
    await user.click(screen.getByRole('button', { name: 'Сохранить версию рукописи' }));
    expect(await screen.findByText('Рукопись: версия 1 сохранена.')).toBeVisible();
    const posts = server.fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(posts).toHaveLength(2);
    expect(posts[0][1]!.body).toBe(posts[1][1]!.body);
  });

  it('restores an older snapshot by appending a revision and preserves current history', async () => {
    const first = revision({ schema_version: '1', blocks: [paragraph('Первоначальный текст')] });
    const server = mockServer(first); server.advance(revision({ schema_version: '1', blocks: [paragraph('Новая версия')] }, 2));
    const { user } = await openEditor();
    await user.click(screen.getByRole('button', { name: 'Сравнить версию 1' }));
    await user.click(await screen.findByRole('button', { name: 'Восстановить версию 1 в черновик' }));
    expect(screen.getByLabelText('Текст блока 1')).toHaveValue('Первоначальный текст');
    await user.click(screen.getByRole('button', { name: 'Сохранить версию рукописи' }));
    expect(await screen.findByText('Рукопись: версия 3 сохранена.')).toBeVisible();
    expect(server.getLatest()!.restored_from_id).toBe('r1');
    expect(server.revisions).toHaveLength(3);
    expect(server.revisions[2]).toEqual(first);
  });

  it('imports only explicit plain-text chunks with a persistent formatting warning', async () => {
    const server = mockServer(); const { user } = await openEditor();
    await user.click(screen.getByText('Добавить текст из DOCX/PDF'));
    server.fetchMock.mockResolvedValueOnce(response({ format: 'pdf', chunks: [{ text: 'Текст страницы', page: 3 }] }));
    await user.upload(screen.getByLabelText('Файл для добавления в рукопись'), new File(['fixture'], 'file.pdf', { type: 'application/pdf' }));
    expect(await screen.findByLabelText('Текст блока 1')).toHaveValue('Текст страницы');
    expect(screen.getByRole('note')).toHaveTextContent('таблицы, сноски, ссылки и форматирование автоматически не восстанавливаются');
    await user.click(screen.getByRole('button', { name: 'Сохранить версию рукописи' }));
    expect(await screen.findByText('Рукопись: версия 1 сохранена.')).toBeVisible();
    expect(server.getLatest()!.document.blocks[0]).toMatchObject({ origin: 'pdf_plain_text', page: 3 });
  });

  it('protects a dirty manuscript on project switch and page close', async () => {
    const server = mockServer(); const originalFetch = server.fetchMock.getMockImplementation()!;
    const brief = { id: 'b1', number: 1, requirements: 'Требования', created_at: '2026-11-03T10:00:00Z' };
    const project = { id: 'p1', title: 'Проект один', research_question: 'Вопрос', created_at: brief.created_at, latest_brief: brief };
    server.fetchMock.mockImplementation(async (url, options) => {
      if (url === '/api/projects') return response([project, { ...project, id: 'p2', title: 'Проект два' }]);
      if (url === '/api/projects/p1') return response(project);
      if (url === '/api/projects/p1/brief-revisions') return response([brief]);
      return originalFetch(url, options);
    });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const user = userEvent.setup(); render(<Projects />);
    await user.click(await screen.findByRole('button', { name: 'Проект один' }));
    await user.click(await screen.findByRole('button', { name: 'Открыть рукопись' }));
    await user.click(await screen.findByRole('button', { name: 'Добавить: Абзац' }));
    await user.type(screen.getByLabelText('Текст блока 1'), 'Не терять');
    const close = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(close);
    expect(close.defaultPrevented).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Проект два' }));
    expect(confirm).toHaveBeenCalled();
    expect(screen.getByLabelText('Текст блока 1')).toHaveValue('Не терять');
    expect(server.fetchMock.mock.calls.some(([url]) => url === '/api/projects/p2')).toBe(false);
  });
});

describe('document semantics', () => {
  it('compares text, structure, formatting, insertion and removal with stable IDs', () => {
    const a = paragraph('А'); const b = paragraph('Б');
    const before: ManuscriptDocument = { schema_version: '1', blocks: [a, b] };
    const after: ManuscriptDocument = { schema_version: '1', blocks: [{ ...b, marks: ['bold'] }, newBlock('table')] };
    const diff = diffDocuments(before, after);
    expect(diff.map(d => d.label)).toEqual(['Удалён блок 1', 'Блок 2 → 1: изменён', 'Добавлен блок 2']);
    expect(diff[1].after).toContain('bold');
    const reordered = { blocks: before.blocks, schema_version: '1' as const };
    expect(sameDocument(before, reordered)).toBe(true);
    expect(diffDocuments(before, reordered)).toEqual([]);
  });
  it('preserves Unicode and page provenance and rejects excessive extraction chunks', () => {
    const text = '😀ё e\u0301';
    const blocks = importedBlocks('docx', [{ text, page: null }]);
    expect(blocks[0].text).toBe(text);
    expect(blocks[0].origin).toBe('docx_plain_text');
    expect(documentProblem({ schema_version: '1', blocks })).toBeNull();
    expect(documentProblem({ schema_version: '1', blocks: importedBlocks('pdf', [{ text: 'x'.repeat(20001), page: 1 }]) })).not.toBeNull();
    expect(documentProblem(emptyDocument())).toBeNull();
  });
});
