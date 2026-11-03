import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react';
import ModelAssistant from './ModelAssistant';
import ExportPanel from './ExportPanel';
import EvidenceWorkspace from './EvidenceWorkspace';
import ManuscriptBlock from './ManuscriptBlock';
import { describeBlock, diffDocuments, documentProblem, emptyDocument, importedBlocks, importWarning, labels, newBlock, sameDocument, type Block, type ManuscriptDocument, type Revision, type RevisionSummary } from './manuscript';

class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new ApiError(typeof data.detail?.message === 'string' ? data.detail.message : typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить операцию.', response.status);
  return data;
}

export function ManuscriptDiff({ before, after }: { before: ManuscriptDocument; after: ManuscriptDocument }) {
  const changes = diffDocuments(before, after);
  return <div className="manuscript-diff">{changes.length === 0 ? <p>Изменений нет.</p> : changes.map(change => <section key={change.id}><h4>{change.label}</h4><div className="diff-columns"><div><strong>Было</strong><pre>{change.before || '—'}</pre></div><div><strong>Стало</strong><pre>{change.after || '—'}</pre></div></div></section>)}</div>;
}

export default function Manuscript({ projectId, onDirty }: { projectId: string; onDirty: (dirty: boolean) => void }) {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const reportAssistantBusy = useCallback((value: boolean) => setAssistantBusy(value), []);
  const latestDirty = useRef(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportDirty, setExportDirty] = useState(false);
  const reportExportDirty = useCallback((value: boolean) => setExportDirty(value), []);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceDirty, setEvidenceDirty] = useState(false);
  const reportEvidenceDirty = useCallback((value: boolean) => setEvidenceDirty(value), []);
  const path = `/api/projects/${projectId}/manuscript`;
  const [base, setBase] = useState<Revision | null>(null);
  const [draft, setDraft] = useState<ManuscriptDocument>(emptyDocument);
  const [undo, setUndo] = useState<ManuscriptDocument[]>([]);
  const [redo, setRedo] = useState<ManuscriptDocument[]>([]);
  const [history, setHistory] = useState<RevisionSummary[]>([]);
  const [more, setMore] = useState(false);
  const [compared, setCompared] = useState<Revision | null>(null);
  const [remote, setRemote] = useState<Revision | null | undefined>(undefined);
  const [restoredFrom, setRestoredFrom] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [conflict, setConflict] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const pending = useRef<{ fingerprint: string; requestId: string } | null>(null);
  const dirty = loaded && (!sameDocument(draft, base?.document ?? emptyDocument()) || restoredFrom !== null);
  latestDirty.current = dirty || evidenceDirty;
  const issue = documentProblem(draft);
  useEffect(() => { onDirty(dirty || evidenceDirty || exportDirty || assistantBusy || busy && loaded); }, [dirty, evidenceDirty, exportDirty, assistantBusy, busy, loaded, onDirty]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => { if (dirty || busy && loaded) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty, busy, loaded]);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api<Revision | null>(path, { signal: controller.signal }), api<RevisionSummary[]>(`${path}/revisions`, { signal: controller.signal })])
      .then(([current, revisions]) => { if (!controller.signal.aborted) { setBase(current); setDraft(current?.document ?? emptyDocument()); setHistory(revisions); setMore(revisions.length === 20); setLoaded(true); } })
      .catch(() => { if (!controller.signal.aborted) setError('Рукопись не загружена. Проверьте доступ к хранилищу и повторите.'); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [path]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setStatus('');
    try { await action(); } catch (e) { setError(e instanceof ApiError ? e.message : 'Соединение прервано. Черновик сохранён в этой вкладке. Повторите запрос; результат записи мог уже сохраниться.'); if (e instanceof ApiError && e.status === 409) setConflict(true); }
    finally { setBusy(false); }
  }
  function edit(next: ManuscriptDocument) {
    setUndo(previous => [...previous.slice(-29), draft]); setRedo([]); setDraft(next.blocks.some(b => b.type === 'formula') ? { ...next, schema_version: '2' } : next); setRestoredFrom(null); setStatus('');
  }
  function replace(block: Block) { edit({ ...draft, blocks: draft.blocks.map(old => old.id === block.id ? block : old) }); }
  function move(index: number, direction: number) {
    const blocks = [...draft.blocks]; [blocks[index], blocks[index + direction]] = [blocks[index + direction], blocks[index]]; edit({ ...draft, blocks });
  }
  async function readHistory(append = false) {
    const items = await api<RevisionSummary[]>(`${path}/revisions${append && history.length ? `?before=${history.at(-1)!.number}` : ''}`);
    setHistory(previous => append ? [...previous, ...items] : items); setMore(items.length === 20);
  }
  async function reload() {
    const current = await api<Revision | null>(path);
    if (!loaded) { setBase(current); setDraft(current?.document ?? emptyDocument()); setLoaded(true); }
    else setRemote(current);
    await readHistory();
  }
  async function save() {
    if (issue) { setError(issue); return; }
    const body = { base_revision_id: base?.id ?? null, document: draft, restored_from_id: restoredFrom };
    const fingerprint = JSON.stringify(body);
    if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, requestId: crypto.randomUUID() };
    const saved = await api<Revision>(`${path}/revisions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, request_id: pending.current.requestId }) });
    setBase(saved); setDraft(saved.document); setUndo([]); setRedo([]); setRestoredFrom(null); setRemote(undefined); setConflict(false); pending.current = null;
    setStatus(`Рукопись: версия ${saved.number} сохранена.`);
    await readHistory();
  }
  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file) return;
    await run(async () => {
      if (file.size > 10 * 1024 * 1024) throw new ApiError('Максимальный размер файла — 10 МиБ.', 413);
      const result = await api<{ format: 'docx' | 'pdf'; chunks: { text: string; page: number | null }[] }>(`/api/documents/extract?filename=${encodeURIComponent(file.name)}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      const next = { ...draft, blocks: [...draft.blocks, ...importedBlocks(result.format, result.chunks)] };
      const problem = documentProblem(next); if (problem) throw new ApiError(problem, 422);
      edit(next); setStatus('Текст добавлен в конец черновика. Проверьте структуру и сохраните версию.');
    });
  }
  const hasImports = draft.blocks.some(block => block.type === 'paragraph' && block.origin !== 'manual' || block.type === 'list' && block.items.some(item => item.origin !== 'manual'));
  return <section className="card manuscript"><h2>Рукопись</h2><p>Ручной план и текст. Сохранение создаёт новую версию; модель и внешние сервисы не используются.</p>
    <p>{base ? `Сохранённая версия ${base.number}` : 'Рукопись ещё не сохранена'}{dirty ? ' · Есть несохранённые изменения' : ''}</p>
    {error && <p role="alert" className="error">{error}</p>}{issue && <p role="alert">{issue}</p>}{status && <p role="status">{status}</p>}{busy && <p role="status">Обработка рукописи…</p>}
    <button disabled={busy || assistantBusy} onClick={() => run(reload)}>{loaded ? 'Проверить актуальную версию' : 'Повторить загрузку рукописи'}</button>
    {conflict && <p role="alert">Черновик не заменён. Загрузите актуальную версию и сравните изменения. Автоматического объединения нет.</p>}
    {remote !== undefined && <section className="conflict"><h3>Актуальная версия {remote?.number ?? 'отсутствует'} и ваш черновик</h3><ManuscriptDiff before={remote?.document ?? emptyDocument()} after={draft} />
      <p>При сохранении черновик станет новой полной версией. Перенесите нужные изменения из актуального текста перед продолжением.</p>
      <button disabled={busy || assistantBusy} onClick={() => { setBase(remote); setRemote(undefined); setConflict(false); pending.current = null; }}>Сравнение выполнено: сохранить мой черновик поверх актуальной версии</button>
      <p className="privacy">Это действие выбирает основу; запись выполняется отдельной кнопкой сохранения.</p>
      <button disabled={busy || assistantBusy} onClick={() => { edit(remote?.document ?? emptyDocument()); setBase(remote); setRemote(undefined); setConflict(false); }}>Взять актуальный текст в редактор</button></section>}
    {loaded && <><fieldset disabled={busy || assistantBusy}><div className="editor-actions"><button type="button" disabled={(!dirty && base !== null) || !!issue || conflict} onClick={() => run(save)}>Сохранить версию рукописи</button>
      <button type="button" disabled={!undo.length} onClick={() => { setRedo([...redo, draft]); setDraft(undo.at(-1)!); setUndo(undo.slice(0, -1)); setRestoredFrom(null); }}>Отменить изменение</button>
      <button type="button" disabled={!redo.length} onClick={() => { setUndo([...undo, draft]); setDraft(redo.at(-1)!); setRedo(redo.slice(0, -1)); setRestoredFrom(null); }}>Повторить изменение</button>
      <button type="button" onClick={() => setShowDiff(!showDiff)}>Сравнить с сохранённой версией</button></div>
      <aside className="outline"><h3>План рукописи</h3>{draft.blocks.filter((b): b is Extract<Block, { type: 'heading' }> => b.type === 'heading').map(b => <p key={b.id} style={{ marginLeft: (b.level - 1) * 16 }}><a href={`#block-${b.id}`}>{b.text || '(Без названия)'}</a></p>)}</aside>
      <div className="editor-actions" aria-label="Добавить блок">{(Object.keys(labels) as Block['type'][]).map(type => <button type="button" key={type} disabled={draft.blocks.length >= 1000} onClick={() => edit({ ...draft, blocks: [...draft.blocks, newBlock(type)] })}>Добавить: {labels[type]}</button>)}</div>
      {!draft.blocks.length && <p>Добавьте заголовки для плана и абзацы для текста.</p>}
      {draft.blocks.map((block, index) => <section key={block.id} id={`block-${block.id}`} className="editor-block" aria-label={`Блок ${index + 1}: ${labels[block.type]}`}><h3>{index + 1}. {labels[block.type]}</h3>
        <ManuscriptBlock block={block} index={index + 1} change={replace} /><div className="editor-actions"><button type="button" disabled={index === 0} onClick={() => move(index, -1)}>Выше</button><button type="button" disabled={index === draft.blocks.length - 1} onClick={() => move(index, 1)}>Ниже</button><button type="button" onClick={() => edit({ ...draft, blocks: draft.blocks.filter(b => b.id !== block.id) })}>Удалить блок</button></div></section>)}
      <details><summary>Добавить текст из DOCX/PDF</summary><p>{importWarning}</p><label>Файл для добавления в рукопись<input type="file" accept=".docx,.pdf" onChange={importFile} /></label></details>
    </fieldset>{hasImports && <p role="note">{importWarning}</p>}
    {showDiff && <section><h3>Изменения относительно сохранённой версии</h3><ManuscriptDiff before={base?.document ?? emptyDocument()} after={draft} /></section>}
    <details><summary>Предпросмотр текста</summary>{draft.blocks.map(block => <pre key={block.id}>{describeBlock(block)}</pre>)}</details>
    <section><h3>История рукописи</h3><ol>{history.map(revision => <li key={revision.id}><button disabled={busy || assistantBusy} onClick={() => run(async () => setCompared(await api<Revision>(`${path}/revisions/${revision.id}`)))}>Сравнить версию {revision.number}</button> · {new Date(revision.created_at).toLocaleString('ru-RU')}{revision.restored_from_id && ' · восстановление'}</li>)}</ol>
      {more && <button disabled={busy || assistantBusy} onClick={() => run(() => readHistory(true))}>Ещё версии рукописи</button>}
      {compared && <section><h3>Версия {compared.number} → текущий черновик</h3><ManuscriptDiff before={compared.document} after={draft} /><button disabled={busy || assistantBusy} onClick={() => { edit(compared.document); setRestoredFrom(compared.id); setStatus(`Версия ${compared.number} загружена в черновик. Сохраните её новой версией, чтобы завершить восстановление.`); }}>Восстановить версию {compared.number} в черновик</button></section>}
    </section></>}
    {base && <><button disabled={busy || assistantBusy} onClick={() => setEvidenceOpen(true)}>Открыть научные доказательства</button>{evidenceOpen && <EvidenceWorkspace projectId={projectId} manuscript={base} manuscriptDirty={dirty} onDirty={reportEvidenceDirty} />}</>}
    <button disabled={busy || assistantBusy} onClick={() => setAssistantOpen(true)}>Открыть AI Research Assistant</button>{assistantOpen && <ModelAssistant projectId={projectId} savedId={base?.id} unsaved={dirty || evidenceDirty || busy} onBusy={reportAssistantBusy} onAccepted={async () => {
      const current = await api<Revision>(path);
      if (latestDirty.current) { setRemote(current); setConflict(true); return; }
      setBase(current); setDraft(current.document); setUndo([]); setRedo([]); setRestoredFrom(null); setEvidenceOpen(false); setEvidenceDirty(false); await readHistory();
    }} />}
    <button disabled={busy || assistantBusy} onClick={() => setExportOpen(true)}>Открыть экспорт Word</button>{exportOpen && <ExportPanel projectId={projectId} unsaved={dirty || evidenceDirty} onDirty={reportExportDirty} />}
    <p className="privacy">Несохранённый текст хранится только в этой вкладке. Перед закрытием сохраните версию. Автоматических резервных копий пока нет.</p>
  </section>;
}
