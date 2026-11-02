import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import App from './App';

describe('document upload', () => {
  it('uploads a file and displays extracted content as text', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ format: 'pdf', text: '<script>alert(1)</script>', pages: 1, chunks: [{ text: '<script>alert(1)</script>', page: 1 }] }) });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    const { container } = render(<App />);
    const file = new File(['%PDF-test'], 'research.pdf');
    await user.upload(screen.getByLabelText('Выберите файл'), file);
    await user.click(screen.getByRole('button', { name: 'Извлечь текст' }));
    expect(await screen.findByText('<script>alert(1)</script>')).toBeVisible();
    expect(container.querySelector('script')).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith('/api/documents/extract?filename=research.pdf', expect.objectContaining({ method: 'POST', body: file }));
    expect(screen.getByText('Страница 1')).toBeVisible();
  });
  it('shows backend errors and permits retry', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: 'Текст не найден.' }) }));
    const user = userEvent.setup(); render(<App />);
    await user.upload(screen.getByLabelText('Выберите файл'), new File(['pdf'], 'a.pdf'));
    await user.click(screen.getByRole('button'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Текст не найден.');
    expect(screen.getByRole('button')).toBeEnabled();
  });
  it('rejects empty files without uploading', async () => {
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup(); render(<App />);
    await user.upload(screen.getByLabelText('Выберите файл'), new File([], 'empty.docx'));
    await user.click(screen.getByRole('button'));
    expect(await screen.findByRole('alert')).toHaveTextContent('непустой файл');
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it('shows a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const user = userEvent.setup(); render(<App />);
    await user.upload(screen.getByLabelText('Выберите файл'), new File(['doc'], 'a.docx'));
    await user.click(screen.getByRole('button'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось связаться');
  });
});
