import { useEffect, useRef, useState, type FormEvent } from 'react';
import { emptyMetadata, kinds, metadataLabels, metadataText, providerMessages, sameMetadata, type Duplicate, type Hit, type Metadata, type Origin, type SearchRun, type Source, type SourceVersion } from './sources';

class ApiError extends Error { constructor(public detail: { message?: string; code?: string; matches?: Duplicate[] }) { super(detail.message ?? 'Не удалось выполнить запрос. Проверьте поля.'); } }
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options); const value = await response.json();
  if (!response.ok) throw new ApiError(value.detail ?? {}); return value;
}
const post = (body: unknown) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export function MetadataView({ value }: { value: Metadata }) {
  return <dl className="source-metadata">{(Object.keys(metadataLabels) as (keyof Metadata)[]).map(key => <div key={key}><dt>{metadataLabels[key]}</dt><dd>{key === 'kind' ? kinds[value.kind] : metadataText(value[key])}</dd></div>)}</dl>;
}
function Comparison({ before, after }: { before: Metadata; after: Metadata }) {
  return <div className="table-scroll"><table className="metadata-comparison"><thead><tr><th>Поле</th><th>Сохранено</th><th>Предлагается</th></tr></thead><tbody>{(Object.keys(metadataLabels) as (keyof Metadata)[]).filter(key => JSON.stringify(before[key]) !== JSON.stringify(after[key])).map(key => <tr key={key}><th>{metadataLabels[key]}</th><td>{metadataText(before[key])}</td><td>{metadataText(after[key])}</td></tr>)}</tbody></table>{sameMetadata(before, after) && <p>Метаданные совпадают.</p>}</div>;
}

export default function Sources({ projectId, onDirty }: { projectId: string; onDirty: (value: boolean) => void }) {
  const path = `/api/projects/${projectId}`;
  const [sources, setSources] = useState<Source[]>([]);
  const [runs, setRuns] = useState<SearchRun[]>([]);
  const [moreSources, setMoreSources] = useState(false); const [moreRuns, setMoreRuns] = useState(false);
  const [selected, setSelected] = useState<Source | null>(null);
  const [form, setForm] = useState<Metadata>(emptyMetadata);
  const [origin, setOrigin] = useState<Origin | null>(null);
  const [duplicates, setDuplicates] = useState<Duplicate[]>([]);
  const [history, setHistory] = useState<SourceVersion[]>([]); const [moreHistory, setMoreHistory] = useState(false);
  const [remote, setRemote] = useState<Source | null>(null); const [conflict, setConflict] = useState(false);
  const [query, setQuery] = useState(''); const [yearFrom, setYearFrom] = useState(''); const [yearTo, setYearTo] = useState('');
  const [providers, setProviders] = useState<string[]>(['crossref', 'openalex']);
  const [consent, setConsent] = useState(false); const [doiConsent, setDoiConsent] = useState(false);
  const [busy, setBusy] = useState(true); const [error, setError] = useState(''); const [status, setStatus] = useState('');
  const sourceRequest = useRef<{ fingerprint: string; request_id: string } | null>(null);
  const searchRequest = useRef<{ fingerprint: string; request_id: string } | null>(null);
  const dirty = !sameMetadata(form, selected?.latest_version.metadata ?? emptyMetadata());
  useEffect(() => { onDirty(dirty || busy); }, [dirty, busy, onDirty]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard);
  }, [dirty, busy]);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api<Source[]>(`${path}/sources`, { signal: controller.signal }), api<SearchRun[]>(`${path}/search-runs`, { signal: controller.signal })])
      .then(([items, journal]) => { if (!controller.signal.aborted) { setSources(items); setRuns(journal); setMoreSources(items.length === 20); setMoreRuns(journal.length === 10); } })
      .catch(() => { if (!controller.signal.aborted) setError('Библиотека недоступна. Проверьте хранилище и миграции.'); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [path]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setStatus('');
    try { await action(); } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Соединение прервано. Данные формы сохранены в этой вкладке; повтор запроса не создаст дубликат.');
      if (e instanceof ApiError) { setDuplicates(e.detail.matches ?? []); if (e.detail.code === 'version_conflict') setConflict(true); }
    } finally { setBusy(false); }
  }
  function edit<K extends keyof Metadata>(key: K, value: Metadata[K]) { setForm({ ...form, [key]: value }); setOrigin(null); }
  function canDiscard() { return !dirty || window.confirm('Закрыть несохранённые изменения карточки источника?'); }
  function reset() { setSelected(null); setForm(emptyMetadata()); setOrigin(null); setDuplicates([]); setHistory([]); setMoreHistory(false); setRemote(null); setConflict(false); sourceRequest.current = null; }
  async function refresh(append = false) {
    const items = await api<Source[]>(`${path}/sources?offset=${append ? sources.length : 0}`);
    setSources(append ? [...sources, ...items] : items); setMoreSources(items.length === 20);
  }
  async function journal(append = false) {
    const items = await api<SearchRun[]>(`${path}/search-runs?offset=${append ? runs.length : 0}`);
    setRuns(append ? [...runs, ...items] : items); setMoreRuns(items.length === 10);
  }
  async function open(id: string, keepForm = false) {
    const record = await api<Source>(`${path}/sources/${id}`);
    setSelected(record); setHistory([]); setMoreHistory(false); setDuplicates([]); setRemote(null); setConflict(false); setDoiConsent(false);
    if (!keepForm) { setForm(record.latest_version.metadata); setOrigin(null); }
    sourceRequest.current = null;
  }
  async function save() {
    const body = { base_version_id: selected?.latest_version.id ?? null, metadata: { ...form, authors: form.authors.map(author => author.trim()).filter(Boolean) }, origin };
    const fingerprint = JSON.stringify({ source: selected?.id ?? null, ...body });
    if (sourceRequest.current?.fingerprint !== fingerprint) sourceRequest.current = { fingerprint, request_id: crypto.randomUUID() };
    const result = await api<Source | SourceVersion>(selected ? `${path}/sources/${selected.id}/versions` : `${path}/sources`, post({ ...body, request_id: sourceRequest.current.request_id }));
    const record = selected ? { ...selected, latest_version: result as SourceVersion } : result as Source;
    setSelected(record); setForm(record.latest_version.metadata); setOrigin(null); setDuplicates([]); setHistory([]); setRemote(null); setConflict(false); sourceRequest.current = null;
    setStatus(`Источник сохранён: версия ${record.latest_version.number}. Метаданные не подтверждают содержание публикации.`); await refresh();
  }
  function selectHit(run: SearchRun, hit: Hit) {
    if (!canDiscard()) return;
    reset(); setForm(hit.metadata); setOrigin({ search_run_id: run.id, hit_id: hit.id }); setStatus('Результат перенесён в форму. Сравните поля и сохраните карточку.');
  }
  async function search(doi = false) {
    const body = { query: doi ? selected!.latest_version.metadata.doi : query, mode: doi ? 'doi' : 'search', providers,
      source_version_id: doi ? selected!.latest_version.id : null, year_from: doi || !yearFrom ? null : Number(yearFrom), year_to: doi || !yearTo ? null : Number(yearTo), limit: 5, consent: doi ? doiConsent : consent };
    const fingerprint = JSON.stringify(body);
    if (searchRequest.current?.fingerprint !== fingerprint) searchRequest.current = { fingerprint, request_id: crypto.randomUUID() };
    const result = await api<SearchRun>(`${path}/search-runs`, post({ ...body, request_id: searchRequest.current.request_id }));
    setRuns(previous => [result, ...previous.filter(item => item.id !== result.id)]); searchRequest.current = null;
    setStatus(result.status === 'pending' ? 'Запрос записан, но завершённого результата пока нет. Обновите журнал. После прерванного процесса запустите новый поиск.' : 'Результаты и ошибки провайдеров сохранены в журнале.');
  }
  async function sourceHistory(append = false) {
    const items = await api<SourceVersion[]>(`${path}/sources/${selected!.id}/versions${append && history.length ? `?before=${history.at(-1)!.number}` : ''}`);
    setHistory(append ? [...history, ...items] : items); setMoreHistory(items.length === 20);
  }
  function submit(event: FormEvent) { event.preventDefault(); void run(save); }
  return <section className="card source-library"><h2>Научная библиотека</h2><p>Сохраняйте библиографические данные и происхождение записей. Наличие DOI, ISBN или записи в каталоге не подтверждает качество и содержание исследования.</p>
    {error && <p role="alert" className="error">{error}</p>}{status && <p role="status">{status}</p>}{busy && <p role="status">Обработка библиотеки…</p>}
    <div className="editor-actions"><button disabled={busy} onClick={() => run(() => refresh())}>Обновить библиотеку</button><button disabled={busy} onClick={() => { if (canDiscard()) reset(); }}>Новая карточка источника</button></div>
    <ul>{sources.map(source => <li key={source.id}><button disabled={busy} onClick={() => { if (canDiscard()) void run(() => open(source.id)); }}>{source.latest_version.metadata.title}</button> · {source.latest_version.metadata.year ?? 'год не указан'} · {source.latest_version.metadata.language} · непроверенные метаданные</li>)}</ul>
    {moreSources && <button disabled={busy} onClick={() => run(() => refresh(true))}>Ещё источники</button>}
    <h3>{selected ? `Карточка · версия ${selected.latest_version.number}` : 'Добавить источник'}</h3>
    {origin && <p>Происхождение: выбранный результат поиска. Изменение полей сохранится как ручная редакция.</p>}
    <form onSubmit={submit}><fieldset disabled={busy}><label>Название публикации<input required maxLength={1000} value={form.title} onChange={e => edit('title', e.target.value)} /></label>
      <label>Авторы (по одному в строке)<textarea value={form.authors.join('\n')} onChange={e => edit('authors', e.target.value.split('\n'))} /></label>
      <label>Год<input type="number" min={1000} max={2200} value={form.year ?? ''} onChange={e => edit('year', e.target.value ? Number(e.target.value) : null)} /></label>
      <label>Тип публикации<select value={form.kind} onChange={e => edit('kind', e.target.value as Metadata['kind'])}>{Object.entries(kinds).map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select></label>
      <label>Код языка (ru, en, und)<input required maxLength={6} value={form.language} onChange={e => edit('language', e.target.value)} /></label>
      {(['container', 'publisher', 'doi', 'isbn', 'url'] as const).map(key => <label key={key}>{metadataLabels[key]}<input maxLength={key === 'url' ? 2048 : key === 'isbn' ? 32 : key === 'doi' ? 400 : 500} value={form[key] ?? ''} onChange={e => edit(key, e.target.value || (key === 'container' || key === 'publisher' ? '' : null))} /></label>)}
      <p className="privacy">ISBN проверяется по контрольной сумме; DOI — по формату. URL сохраняется без автоматического открытия и загрузки.</p>
      <button disabled={conflict}>{selected ? 'Сохранить новую версию карточки' : 'Сохранить карточку источника'}</button></fieldset></form>
    {selected && <><h3>Изменения карточки</h3><Comparison before={selected.latest_version.metadata} after={form} />
      <button disabled={busy} onClick={() => run(async () => setRemote(await api<Source>(`${path}/sources/${selected.id}`)))}>Загрузить актуальную карточку для сравнения</button>
      {remote && <section className="conflict"><Comparison before={remote.latest_version.metadata} after={form} /><button disabled={busy} onClick={() => { setSelected(remote); setRemote(null); setConflict(false); sourceRequest.current = null; }}>Сравнение выполнено: сохранить мои поля новой версией</button></section>}
      <button disabled={busy} onClick={() => run(() => sourceHistory())}>История карточки</button>
      {history.map(version => <details key={version.id}><summary>Версия источника {version.number} · {new Date(version.created_at).toLocaleString('ru-RU')}</summary><p>{version.provenance.kind === 'manual' ? 'Введено вручную' : `Метаданные ${version.provenance.provider}`}; содержание не проверено.</p><MetadataView value={version.metadata} /></details>)}
      {moreHistory && <button disabled={busy} onClick={() => run(() => sourceHistory(true))}>Ещё версии источника</button>}
      {selected.latest_version.metadata.doi && <><label><input type="checkbox" checked={doiConsent} onChange={e => setDoiConsent(e.target.checked)} />Разрешаю отправить DOI выбранным каталогам для сверки метаданных</label><button disabled={busy || !doiConsent || !providers.length} onClick={() => run(() => search(true))}>Сверить DOI сохранённой версии</button></>}</>}
    {duplicates.map(duplicate => <section key={duplicate.source_id} className="conflict"><h3>Найден существующий DOI / ISBN</h3><Comparison before={duplicate.metadata} after={form} /><p>Автоматического объединения и перезаписи нет.</p><button disabled={busy} onClick={() => run(() => open(duplicate.source_id, true))}>Сравнить и исправить найденную карточку</button></section>)}
    <section><h3>Поиск Crossref / OpenAlex</h3><form onSubmit={event => { event.preventDefault(); void run(() => search()); }}><fieldset disabled={busy}>
      <label>Поисковый запрос<input required minLength={2} maxLength={300} value={query} onChange={e => { setQuery(e.target.value); setConsent(false); }} /></label>
      <div className="editor-actions">{['crossref', 'openalex'].map(provider => <label key={provider}><input type="checkbox" checked={providers.includes(provider)} onChange={e => { setProviders(e.target.checked ? [...providers, provider] : providers.filter(p => p !== provider)); setConsent(false); setDoiConsent(false); }} />{provider}</label>)}</div>
      <label>Год от<input type="number" min={1000} max={2200} value={yearFrom} onChange={e => setYearFrom(e.target.value)} /></label><label>Год до<input type="number" min={1000} max={2200} value={yearTo} onChange={e => setYearTo(e.target.value)} /></label>
      <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />Разрешаю отправить этот запрос и фильтры выбранным каталогам</label>
      <p className="privacy">Передаются только введённый запрос и фильтры. Рукопись и требования проекта не отправляются. До 5 результатов на каталог; порядок каталога не является оценкой научной достоверности.</p>
      <button disabled={!consent || !providers.length}>Найти публикации</button></fieldset></form></section>
    <section><h3>Журнал поиска и сверок</h3><button disabled={busy} onClick={() => run(() => journal())}>Обновить журнал поиска</button>
      {runs.map(searchRun => <details key={searchRun.id} open><summary>{searchRun.request.mode === 'doi' ? 'Сверка DOI' : 'Поиск'}: {searchRun.request.query} · {new Date(searchRun.created_at).toLocaleString('ru-RU')}</summary>
        <p>Годы: {searchRun.request.year_from ?? 'без нижней границы'} — {searchRun.request.year_to ?? 'без верхней границы'}. Каталоги: {searchRun.request.providers.join(', ')}. Лимит: {searchRun.request.limit}.</p>
        {searchRun.source_version_id && <p className="privacy">Сверка относится к зафиксированной версии карточки. Последующие правки не перепроверяются автоматически.</p>}
        {searchRun.status === 'pending' && <p>Есть запись запуска, завершённого результата нет. Обновите журнал; после прерывания процесса запустите новый поиск.</p>}
        {searchRun.results.map(result => <section key={result.provider}><h4>{result.provider}</h4><p>{providerMessages[result.code] ?? 'Проверка не завершена.'}</p>{result.skipped_records > 0 && <p>Пропущено записей: {result.skipped_records}.</p>}
          {result.hits.map(hit => <details key={hit.id}><summary>{hit.rank}. {hit.metadata.title}</summary><MetadataView value={hit.metadata} />
            {hit.related_hits?.map(related => <p key={related.id}>Тот же идентификатор: {related.id}. {related.differences.length ? `Расхождения: ${related.differences.map(f => metadataLabels[f as keyof Metadata] ?? f).join(', ')}` : 'Сопоставимые заполненные поля совпали.'}</p>)}
            {hit.comparison && <p role="note">{hit.comparison.status === 'conflict' ? `Расхождения с карточкой: ${hit.comparison.differences.map(f => metadataLabels[f as keyof Metadata] ?? f).join(', ')}` : hit.comparison.status === 'metadata_match' ? 'Сопоставимые метаданные совпали; это не подтверждение текста или научных выводов.' : 'Недостаточно метаданных для сверки.'}</p>}
            <button disabled={busy} onClick={() => selectHit(searchRun, hit)}>Перенести результат в карточку</button></details>)}
        </section>)}
      </details>)}{moreRuns && <button disabled={busy} onClick={() => run(() => journal(true))}>Предыдущие поиски</button>}
    </section><p className="privacy">Полные тексты, переводы и проверка утверждений относятся к следующим этапам. Несохранённая карточка хранится только в этой вкладке.</p>
  </section>;
}
