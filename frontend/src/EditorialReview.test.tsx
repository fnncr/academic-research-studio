import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import EditorialReview from './EditorialReview';

beforeEach(() => vi.restoreAllMocks());

it('requires a key and accurately labels non-implemented criteria', async () => {
  const fetcher = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      revision_id: 'rev-1',
      findings: [{ criterion_id: '35', block_id: 'block-1', start: 0,
        quote: '<script>source</script>', explanation: 'Рассмотрите повтор.' }],
      coverage: [
        { criterion_id: '35', title: 'Повтор', status: 'candidate' },
        { criterion_id: '43', title: 'Проверка источника', status: 'insufficient_data' },
      ],
      disclaimer: 'Лексический сигнал, не процент ИИ.',
    }),
  }));
  vi.stubGlobal('fetch', fetcher);
  render(<EditorialReview projectId="project-1" revisionId="rev-1" unsaved />);
  const user = userEvent.setup();
  expect(screen.getByRole('button', { name: 'Проверить сохранённую версию' })).toBeDisabled();
  expect(screen.getByText(/Есть несохранённые изменения/)).toBeVisible();
  await user.type(screen.getByLabelText('Ключ владельца редакторской проверки'), 'local-secret');
  await user.click(screen.getByRole('button', { name: 'Проверить сохранённую версию' }));
  await screen.findByText(/Кандидатов на повтор: 1/);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toContain('rev-1/preview');
  expect(screen.getByText('<script>source</script>')).toBeVisible();
  expect(document.querySelector('script')).toBeNull();
  await user.click(screen.getByText('Покрытие 14 предлагаемых критериев'));
  expect(screen.getByText(/Проверка источника — не проверено/)).toBeVisible();
});

it('reports authorization problems without attributing AI provenance', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401 })));
  render(<EditorialReview projectId="x" revisionId="r" unsaved={false} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Ключ владельца редакторской проверки'), 'wrong-key');
  await user.click(screen.getByRole('button', { name: 'Проверить сохранённую версию' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('401');
  expect(screen.queryByText(/Кандидатов на повтор:/)).not.toBeInTheDocument();
});
