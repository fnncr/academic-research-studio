import { useState, type FormEvent } from 'react';
type Result = { format: string; text: string; pages: number | null; chunks: { text: string; page: number | null }[] };
export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(''); setResult(null);
    if (!file) { setError('Выберите документ.'); return; }
    if (!/\.(docx|pdf)$/i.test(file.name)) { setError('Поддерживаются только DOCX и PDF.'); return; }
    if (file.size === 0 || file.size > 10 * 1024 * 1024) { setError('Выберите непустой файл размером до 10 МиБ.'); return; }
    setBusy(true);
    try {
      const response = await fetch(`/api/documents/extract?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
        signal: AbortSignal.timeout(60000),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Не удалось обработать документ.');
      setResult(payload);
    } catch (e) {
      setError(e instanceof Error && e.name === 'Error' ? e.message : 'Не удалось связаться с сервером. Повторите загрузку.');
    } finally { setBusy(false); }
  }
  return <main>
    <header><span className="eyebrow">Рабочее пространство исследователя</span><h1>Academic Research Studio</h1><p>Загрузите документ, чтобы прочитать извлечённый текст.</p></header>
    <section className="card" aria-labelledby="upload-title"><h2 id="upload-title">Ваш документ</h2>
      <p id="file-help">DOCX или текстовый PDF · до 10 МиБ · PDF до 200 страниц. Сканы пока не поддерживаются.</p>
      <form onSubmit={submit}><label htmlFor="document">Выберите файл</label><input id="document" type="file" accept=".docx,.pdf" aria-describedby="file-help" disabled={busy} onChange={e => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(''); }} />
      <button disabled={busy || !file} type="submit">{busy ? 'Извлекаем текст…' : 'Извлечь текст'}</button></form>
      <p className="privacy">Документ обрабатывается временно и не сохраняется в истории.</p>
      {busy && <p role="status">Обработка документа…</p>}{error && <p role="alert" className="error">{error}</p>}
    </section>
    {result && <section className="card" aria-labelledby="result-title"><h2 id="result-title">Извлечённый текст</h2><p role="status">Готово · {result.text.length.toLocaleString('ru-RU')} символов{result.pages !== null ? ` · страниц: ${result.pages}` : ''}</p>
    <p>Проверьте порядок чтения и полноту текста перед дальнейшей работой.</p><div className="document">{result.chunks.map((chunk, i) => <div key={i}>{chunk.page !== null && <h3>Страница {chunk.page}</h3>}<p className="text">{chunk.text}</p></div>)}</div></section>}
    <footer>Первая версия: загрузка и извлечение текста. Редакторская проверка пока не выполняется.</footer>
  </main>;
}
