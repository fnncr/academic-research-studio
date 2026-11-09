import { useEffect, useState } from 'react';

type Finding = { criterion_id: string; block_id: string; start: number; quote: string; explanation: string };
type Coverage = { criterion_id: string; title: string; status: string };
type Report = { revision_id: string; findings: Finding[]; coverage: Coverage[]; disclaimer: string };

export default function EditorialReview({ projectId, revisionId, unsaved }:
  { projectId: string; revisionId: string; unsaved: boolean }) {
  const [key, setKey] = useState('');
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => { setReport(null); setError(''); }, [projectId, revisionId]);
  async function run() {
    setReport(null); setError(''); setLoading(true);
    try {
      const response = await fetch(
        '/api/projects/' + projectId + '/editorial/revisions/' + revisionId + '/preview',
        { headers: { Authorization: 'Bearer ' + key }, cache: 'no-store' }
      );
      if (!response.ok) throw new Error('Не удалось выполнить проверку (' + response.status + ').');
      const data = await response.json() as Report;
      if (data.revision_id !== revisionId) throw new Error('Версия отчёта не совпала с выбранной.');
      setReport(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка получения отчёта.');
    } finally { setLoading(false); }
  }
  return <section className="card" aria-label="Редакторская проверка">
    <h3>Редакторская проверка — экспериментальная версия</h3>
    <p>Локальный поиск похожих формулировок (критерии 35 и 42). Остальные 12 предложенных правил ещё не реализованы. Это не проверка ИИ-авторства и не процент «Антиплагиата».</p>
    <p>Проверяется только сохранённая версия рукописи; текст не отправляется внешним сервисам.</p>
    {unsaved && <p role="status">Есть несохранённые изменения. Результат относится только к сохранённой версии.</p>}
    <label>Ключ владельца редакторской проверки
      <input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} />
    </label>
    <button type="button" disabled={!key.trim() || loading} onClick={run}>
      {loading ? 'Проверка…' : 'Проверить сохранённую версию'}
    </button>
    {error && <p role="alert">{error}</p>}
    {report && <section aria-label="Результаты редакторской проверки">
      <p role="status">Кандидатов на повтор: {report.findings.length}.</p>
      <p>{report.disclaimer}</p>
      <h4>Замечания</h4>
      {report.findings.length === 0 ? <p>В исследованной части текста совпадений не найдено. Это не означает отсутствие иных проблем.</p> :
        <ol>{report.findings.map((finding, i) =>
          <li key={finding.block_id + '-' + finding.start + '-' + i}>
            <strong>Правило {finding.criterion_id}</strong>:
            <a href={'#block-' + finding.block_id}> Найти абзац</a>
            <blockquote>{finding.quote}</blockquote>
            <p>{finding.explanation}</p>
          </li>)}</ol>}
      <details><summary>Покрытие 14 предлагаемых критериев</summary>
        <ul>{report.coverage.map(c => <li key={c.criterion_id}>
          {c.criterion_id}. {c.title} — {c.status === 'insufficient_data' ? 'не проверено' :
            c.status === 'candidate' ? 'найдены кандидаты' : 'совпадений в охваченной части не найдено'}
        </li>)}</ul>
      </details>
    </section>}
  </section>;
