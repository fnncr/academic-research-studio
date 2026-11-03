import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import Projects from './Projects';
import App from './App';
const brief = { id: 'b1', number: 1, requirements: 'Требования 1', created_at: '2026-11-03T10:00:00Z' };
const project = { id: 'p1', title: 'Курсовая', research_question: 'Вопрос', created_at: brief.created_at, latest_brief: brief };
const response = (data: unknown, ok = true) => ({ ok, json: async () => data });

describe('projects', () => {
  it('creates a project and appends a requirements revision', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response([])).mockResolvedValueOnce(response(project))
      .mockResolvedValueOnce(response([project])).mockResolvedValueOnce(response({ ...brief, id: 'b2', number: 2, requirements: 'Требования 2' }));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup(); render(<Projects />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Создать проект' })).toBeEnabled());
    await user.type(screen.getByLabelText('Название'), 'Курсовая');
    await user.type(screen.getByLabelText('Исследовательский вопрос'), 'Вопрос');
    await user.type(screen.getByLabelText('Требования преподавателя'), 'Требования 1');
    await user.click(screen.getByRole('button', { name: 'Создать проект' }));
    expect(await screen.findByText('Проект сохранён.')).toBeVisible();
    await user.clear(screen.getByLabelText('Новая версия требований'));
    await user.type(screen.getByLabelText('Новая версия требований'), 'Требования 2');
    await user.click(screen.getByRole('button', { name: 'Сохранить новую версию' }));
    expect(await screen.findByText('Версия 2 сохранена.')).toBeVisible();
    expect(fetchMock).toHaveBeenLastCalledWith('/api/projects/p1/brief-revisions', expect.objectContaining({ body: JSON.stringify({ base_revision_id: 'b1', requirements: 'Требования 2' }) }));
    expect(screen.getByText(/Версия 1 ·/)).toBeVisible();
  });
  it('preserves draft on conflict and loads latest without replacing it', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response([project])).mockResolvedValueOnce(response(project)).mockResolvedValueOnce(response([brief]))
      .mockResolvedValueOnce(response({ detail: { message: 'Конфликт версии' } }, false))
      .mockResolvedValueOnce(response({ ...project, latest_brief: { ...brief, id: 'b2', number: 2 } })).mockResolvedValueOnce(response([brief]));
    vi.stubGlobal('fetch', fetchMock); const user = userEvent.setup(); render(<Projects />);
    await user.click(await screen.findByRole('button', { name: 'Курсовая' }));
    await user.clear(await screen.findByLabelText('Новая версия требований'));
    await user.type(screen.getByLabelText('Новая версия требований'), 'Мой черновик');
    await user.click(screen.getByRole('button', { name: 'Сохранить новую версию' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Конфликт версии');
    expect(screen.getByLabelText('Новая версия требований')).toHaveValue('Мой черновик');
    await user.click(screen.getByRole('button', { name: /Загрузить актуальную/ }));
    expect(await screen.findByText('Актуальные требования · версия 2')).toBeVisible();
    expect(screen.getByLabelText('Новая версия требований')).toHaveValue('Мой черновик');
  });
  it('keeps upload available when project storage fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Network error')));
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole('button', { name: 'Проекты' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Хранилище проектов недоступно');
    await user.click(screen.getByRole('button', { name: 'Извлечение текста' }));
    expect(screen.getByLabelText('Выберите файл')).toBeVisible();
  });
});
