import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Sources from './Sources';
import { emptyMetadata, type Metadata, type Source, type SearchRun } from './sources';

// Synthetic bibliography only; these fixtures do not represent publications.
const metadata: Metadata = { ...emptyMetadata(), title: 'Синтетическая тестовая запись', authors: ['Тестовый Автор'], year: 2020, doi: '10.5555/synthetic-fixture', language: 'ru', kind: 'article' };
const source: Source = { id: 's1', project_id: 'p1', created_at: '2026-11-03T10:00:00Z', latest_version: { id: 'v1', source_id: 's1', number: 1, metadata, provenance: { kind: 'manual' }, created_at: '2026-11-03T10:00:00Z', verification: 'unverified' } };
const response = (data: unknown, status = 200) => ({ ok: status < 400, status, json: async () => data });
async function mount(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock); render(<Sources projectId="p1" onDirty={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить карточку источника' })).toBeEnabled());
  return userEvent.setup();
}

describe('source library', () => {
  it('creates a manual source without network transfer and appends a metadata version', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response([])).mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response(source, 201)).mockResolvedValueOnce(response([source]))
      .mockResolvedValueOnce(response({ ...source.latest_version, id: 'v2', number: 2, metadata: { ...metadata, year: 2021 } }, 201)).mockResolvedValueOnce(response([source]));
    const user = await mount(fetchMock);
    await user.type(screen.getByLabelText('Название публикации'), metadata.title);
    await user.type(screen.getByLabelText('Авторы (по одному в строке)'), 'Тестовый Автор{enter}');
    await user.type(screen.getByLabelText('DOI', { exact: true }), metadata.doi!);
    await user.click(screen.getByRole('button', { name: 'Сохранить карточку источника' }));
    expect(await screen.findByText(/Источник сохранён: версия 1/)).toBeVisible();
    const firstBody = JSON.parse(fetchMock.mock.calls[2][1].body);
    expect(firstBody.metadata.authors).toEqual(['Тестовый Автор']);
    expect(firstBody.origin).toBeNull();
    await user.clear(screen.getByLabelText('Год', { exact: true })); await user.type(screen.getByLabelText('Год', { exact: true }), '2021');
    await user.click(screen.getByRole('button', { name: 'Сохранить новую версию карточки' }));
    expect(await screen.findByText(/Источник сохранён: версия 2/)).toBeVisible();
    expect(JSON.parse(fetchMock.mock.calls[4][1].body).base_version_id).toBe('v1');
    expect(fetchMock.mock.calls.every(([url]) => !url.endsWith('/search-runs') || url === '/api/projects/p1/search-runs' && fetchMock.mock.calls[1][1].method === undefined)).toBe(true);
  });

  it('shows conflicting duplicate metadata and preserves proposed fields for explicit correction', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response([source])).mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(response({ detail: { code: 'duplicate_source', message: 'DOI уже сохранён', matches: [{ source_id: 's1', version_id: 'v1', metadata, differences: ['title'] }] } }, 409))
      .mockResolvedValueOnce(response(source));
    const user = await mount(fetchMock);
    await user.type(screen.getByLabelText('Название публикации'), 'Другая синтетическая запись');
    await user.type(screen.getByLabelText('DOI', { exact: true }), metadata.doi!);
    await user.click(screen.getByRole('button', { name: 'Сохранить карточку источника' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('DOI уже сохранён');
    expect(screen.getByText('Автоматического объединения и перезаписи нет.')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Сравнить и исправить найденную карточку' }));
    expect(await screen.findByRole('button', { name: 'Сохранить новую версию карточки' })).toBeVisible();
    expect(screen.getByLabelText('Название публикации')).toHaveValue('Другая синтетическая запись');
  });

  it('requires explicit search consent and retains denied-provider results as unverified', async () => {
    const denied: SearchRun = { id: 'run1', status: 'completed', source_version_id: null, created_at: source.created_at,
      request: { query: 'synthetic query', mode: 'search', providers: ['crossref', 'openalex'], limit: 5, year_from: null, year_to: null },
      results: [{ provider: 'crossref', status: 'unavailable', code: 'access_denied', checked_at: source.created_at, hits: [], skipped_records: 0 }, { provider: 'openalex', status: 'unavailable', code: 'network_unavailable', checked_at: source.created_at, hits: [], skipped_records: 0 }] };
    const fetchMock = vi.fn().mockResolvedValueOnce(response([])).mockResolvedValueOnce(response([])).mockResolvedValueOnce(response(denied, 201));
    const user = await mount(fetchMock);
    await user.type(screen.getByLabelText('Поисковый запрос'), 'synthetic query');
    expect(screen.getByRole('button', { name: 'Найти публикации' })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await user.click(screen.getByLabelText('Разрешаю отправить этот запрос и фильтры выбранным каталогам'));
    await user.click(screen.getByRole('button', { name: 'Найти публикации' }));
    expect(await screen.findByText(/Доступ запрещён провайдером/)).toBeVisible();
    expect(screen.getByText(/Источник не объявляется вымышленным/)).toBeVisible();
    const body = JSON.parse(fetchMock.mock.calls[2][1].body);
    expect(body.consent).toBe(true); expect(body.query).toBe('synthetic query'); expect(body.document).toBeUndefined();
    await user.type(screen.getByLabelText('Поисковый запрос'), ' changed');
    expect(screen.getByRole('button', { name: 'Найти публикации' })).toBeDisabled();
  });

  it('imports a search snapshot with provenance only after the user chooses and saves it', async () => {
    const searchRun: SearchRun = { id: 'run1', status: 'completed', created_at: source.created_at, source_version_id: null,
      request: { query: 'synthetic', mode: 'search', providers: ['crossref'], limit: 5, year_from: null, year_to: null },
      results: [{ provider: 'crossref', status: 'completed', code: 'ok', checked_at: source.created_at, skipped_records: 0, hits: [{ id: 'crossref:1', rank: 1, metadata }] }] };
    const fetchMock = vi.fn().mockResolvedValueOnce(response([])).mockResolvedValueOnce(response([searchRun]))
      .mockResolvedValueOnce(response(source, 201)).mockResolvedValueOnce(response([source]));
    const user = await mount(fetchMock);
    await user.click(screen.getByText('1. ' + metadata.title));
    await user.click(screen.getByRole('button', { name: 'Перенести результат в карточку' }));
    expect(screen.getByLabelText('Название публикации')).toHaveValue(metadata.title);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: 'Сохранить карточку источника' }));
    expect(await screen.findByText(/Источник сохранён/)).toBeVisible();
    expect(JSON.parse(fetchMock.mock.calls[2][1].body).origin).toEqual({ search_run_id: 'run1', hit_id: 'crossref:1' });
  });

  it('reuses a creation request after a lost network response', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response([])).mockResolvedValueOnce(response([]))
      .mockRejectedValueOnce(new TypeError('network')).mockResolvedValueOnce(response(source, 201)).mockResolvedValueOnce(response([source]));
    const user = await mount(fetchMock);
    await user.type(screen.getByLabelText('Название публикации'), metadata.title);
    await user.click(screen.getByRole('button', { name: 'Сохранить карточку источника' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Соединение прервано');
    expect(screen.getByLabelText('Название публикации')).toHaveValue(metadata.title);
    await user.click(screen.getByRole('button', { name: 'Сохранить карточку источника' }));
    expect(await screen.findByText(/Источник сохранён/)).toBeVisible();
    expect(fetchMock.mock.calls[2][1].body).toBe(fetchMock.mock.calls[3][1].body);
  });

  it('does not overwrite a stale card and preserves draft until explicit comparison', async () => {
    const newer = { ...source, latest_version: { ...source.latest_version, id: 'v2', number: 2, metadata: { ...metadata, year: 2022 } } };
    const fetchMock = vi.fn().mockResolvedValueOnce(response([source])).mockResolvedValueOnce(response([])).mockResolvedValueOnce(response(source))
      .mockResolvedValueOnce(response({ detail: { code: 'version_conflict', message: 'Карточка изменилась' } }, 409)).mockResolvedValueOnce(response(newer));
    const user = await mount(fetchMock);
    await user.click(screen.getByRole('button', { name: metadata.title }));
    await user.clear(await screen.findByLabelText('Год', { exact: true })); await user.type(screen.getByLabelText('Год', { exact: true }), '2021');
    await user.click(screen.getByRole('button', { name: 'Сохранить новую версию карточки' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Карточка изменилась');
    expect(screen.getByRole('button', { name: 'Сохранить новую версию карточки' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Загрузить актуальную карточку для сравнения' }));
    await user.click(await screen.findByRole('button', { name: 'Сравнение выполнено: сохранить мои поля новой версией' }));
    expect(screen.getByLabelText('Год', { exact: true })).toHaveValue(2021);
    expect(screen.getByRole('button', { name: 'Сохранить новую версию карточки' })).toBeEnabled();
  });
});
