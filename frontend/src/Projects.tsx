import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import Manuscript from './Manuscript';
import Sources from './Sources';
type Summary = { id: string; title: string; research_question: string; created_at: string };
type Brief = { id: string; number: number; requirements: string; created_at: string };
type Project = Summary & { latest_brief: Brief };
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail?.message === 'string' ? data.detail.message : 'Не удалось выполнить операцию. Проверьте заполнение полей.');
  return data;
}
const post = (body: unknown) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export default function Projects() {
  const [editorOpen, setEditorOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const manuscriptDirty = useRef(false);
  const libraryDirty = useRef(false);
  const reportDirty = useCallback((value: boolean) => { manuscriptDirty.current = value; }, []);
  const reportLibraryDirty = useCallback((value: boolean) => { libraryDirty.current = value; }, []);
  function canLeave() { return !(manuscriptDirty.current || libraryDirty.current) || window.confirm('В рукописи или библиотеке есть несохранённые изменения или незавершённый запрос. Перейти в другой проект и закрыть черновики?'); }
  const [projects, setProjects] = useState<Summary[]>([]);
  const [selected, setSelected] = useState<Project | null>(null);
  const [history, setHistory] = useState<Brief[]>([]);
  const [moreProjects, setMoreProjects] = useState(false);
  const [moreHistory, setMoreHistory] = useState(false);
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [initial, setInitial] = useState('');
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    api<Summary[]>('/api/projects', { signal: controller.signal }).then(items => {
      setProjects(items); setMoreProjects(items.length === 20);
    }).catch(() => { if (!controller.signal.aborted) setError('Хранилище проектов недоступно. Извлечение текста доступно в соседнем разделе.'); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, []);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setStatus('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : 'Ошибка соединения.'); }
    finally { setBusy(false); }
  }
  async function list(append = false) {
    const items = await api<Summary[]>(`/api/projects?offset=${append ? projects.length : 0}`);
    setProjects(append ? [...projects, ...items] : items); setMoreProjects(items.length === 20);
  }
  async function open(id: string, preserveDraft = false) {
    if (id !== selected?.id && !canLeave()) return;
    const [project, briefs] = await Promise.all([api<Project>(`/api/projects/${id}`), api<Brief[]>(`/api/projects/${id}/brief-revisions`)]);
    setSelected(project); setHistory(briefs); setMoreHistory(briefs.length === 20);
    if (id !== selected?.id) { setEditorOpen(false); setLibraryOpen(false); manuscriptDirty.current = false; libraryDirty.current = false; }
    if (!preserveDraft) setDraft(project.latest_brief.requirements);
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    if (!canLeave()) return;
    await run(async () => {
      const project = await api<Project>('/api/projects', post({ title, research_question: question, requirements: initial }));
      setSelected(project); setHistory([project.latest_brief]); setMoreHistory(false); setDraft(project.latest_brief.requirements);
      setEditorOpen(false); setLibraryOpen(false); manuscriptDirty.current = false; libraryDirty.current = false;
      setTitle(''); setQuestion(''); setInitial(''); setStatus('Проект сохранён.');
      await list();
    });
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!selected) return;
    await run(async () => {
      const brief = await api<Brief>(`/api/projects/${selected.id}/brief-revisions`, post({ base_revision_id: selected.latest_brief.id, requirements: draft }));
      setSelected({ ...selected, latest_brief: brief }); setHistory([brief, ...history]);
      setStatus(`Версия ${brief.number} сохранена.`);
    });
  }
  return <main><header><h1>Исследовательские проекты</h1><p>Сохраняйте вопрос исследования и историю требований преподавателя.</p></header>
    {error && <p role="alert" className="error">{error}</p>}{status && <p role="status">{status}</p>}{busy && <p role="status">Загрузка…</p>}
    <section className="card"><h2>Новый проект</h2><form onSubmit={create}><fieldset disabled={busy}>
      <label htmlFor="project-title">Название</label><input id="project-title" required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} />
      <label htmlFor="question">Исследовательский вопрос</label><textarea id="question" required maxLength={4000} value={question} onChange={e => setQuestion(e.target.value)} />
      <label htmlFor="initial-brief">Требования преподавателя</label><textarea id="initial-brief" required maxLength={20000} value={initial} onChange={e => setInitial(e.target.value)} />
      <button>Создать проект</button></fieldset></form><p className="privacy">Проекты и требования сохраняются. Загруженные DOCX/PDF к проектам пока не прикрепляются.</p></section>
    <section className="card"><h2>Мои проекты</h2><button disabled={busy} onClick={() => run(() => list())}>Обновить список</button>
      {!busy && projects.length === 0 && <p>Сохранённых проектов пока нет.</p>}
      <ul>{projects.map(p => <li key={p.id}><button disabled={busy} onClick={() => run(() => open(p.id))}>{p.title}</button></li>)}</ul>
      {moreProjects && <button disabled={busy} onClick={() => run(() => list(true))}>Ещё проекты</button>}</section>
    {selected && <section className="card"><h2>{selected.title}</h2><p>{selected.research_question}</p><h3>Актуальные требования · версия {selected.latest_brief.number}</h3><p className="text">{selected.latest_brief.requirements}</p>
      <button disabled={busy} onClick={() => run(() => open(selected.id, true))}>Загрузить актуальную версию, сохранив черновик</button>
      <form onSubmit={save}><fieldset disabled={busy}><label htmlFor="brief-draft">Новая версия требований</label><textarea id="brief-draft" required maxLength={20000} value={draft} onChange={e => setDraft(e.target.value)} /><button>Сохранить новую версию</button></fieldset></form>
      <h3>История требований</h3><ol>{history.map(b => <li key={b.id}><details><summary>Версия {b.number} · {new Date(b.created_at).toLocaleString('ru-RU')}</summary><p className="text">{b.requirements}</p></details></li>)}</ol>
      {moreHistory && <button disabled={busy} onClick={() => run(async () => { const items = await api<Brief[]>(`/api/projects/${selected.id}/brief-revisions?offset=${history.length}`); setHistory([...history, ...items]); setMoreHistory(items.length === 20); })}>Предыдущие версии</button>}
    </section>}
    {selected && <><button disabled={busy} onClick={() => setEditorOpen(true)}>Открыть рукопись</button>{editorOpen && <Manuscript key={selected.id} projectId={selected.id} onDirty={reportDirty} />}</>}
    {selected && <><button disabled={busy} onClick={() => setLibraryOpen(true)}>Открыть библиотеку источников</button>{libraryOpen && <Sources key={selected.id} projectId={selected.id} onDirty={reportLibraryDirty} />}</>}
  </main>;
}
