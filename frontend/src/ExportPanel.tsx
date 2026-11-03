import { useEffect, useRef, useState } from 'react';
import { api, post, type Plan } from './evidence';
import type { RevisionSummary } from './manuscript';
export type Profile = { name: string; paper: 'A4'; font: string; font_size: number; line_spacing: number; alignment: string; first_line_cm: number; margin_top_cm: number; margin_bottom_cm: number; margin_left_cm: number; margin_right_cm: number; paragraph_after_pt: number; header: string; footer: string; page_numbers: boolean; toc: boolean; number_tables: boolean };
type Title = { enabled: boolean; university: string; department: string; discipline: string; topic: string; author: string; group: string; teacher: string; city: string; year: number | null };
type Notice = { code: string; message: string; field?: string; source_version_id?: string; source_title?: string; block_id?: string; claim_id?: string };
type Report = { errors: Notice[]; warnings: Notice[]; info: Notice[]; can_export: boolean; preflight_token: string; manifest: unknown };
type Options = { profiles: { id: string; description: string; profile: Profile }[]; citation_styles: { id: string; label: string }[] };
const emptyTitle = (): Title => ({ enabled: true, university: '', department: '', discipline: '', topic: '', author: '', group: '', teacher: '', city: '', year: null });
const titleLabels = { university: 'Университет', department: 'Факультет или кафедра', discipline: 'Дисциплина', topic: 'Тема работы', author: 'ФИО автора', group: 'Группа', teacher: 'ФИО и должность преподавателя', city: 'Город' };
const noticeLabels: Record<string, string> = { ...titleLabels, year: 'Год', authors: 'Авторы источника', title: 'Название источника', container: 'Журнал', publisher: 'Издатель' };
const profileLabels = { font_size: 'Размер шрифта, пт', line_spacing: 'Межстрочный интервал', first_line_cm: 'Отступ первой строки, см', margin_top_cm: 'Верхнее поле, см', margin_bottom_cm: 'Нижнее поле, см', margin_left_cm: 'Левое поле, см', margin_right_cm: 'Правое поле, см', paragraph_after_pt: 'Интервал после абзаца, пт' };
export default function ExportPanel({ projectId, unsaved, onDirty }: { projectId: string; unsaved: boolean; onDirty: (value: boolean) => void }) {
  const path = `/api/projects/${projectId}`;
  const [options, setOptions] = useState<Options | null>(null); const [profile, setProfile] = useState<Profile | null>(null); const [preset, setPreset] = useState('');
  const [revisions, setRevisions] = useState<RevisionSummary[]>([]); const [moreRevisions, setMoreRevisions] = useState(false); const [revisionId, setRevisionId] = useState('');
  const [plans, setPlans] = useState<Plan[]>([]); const [morePlans, setMorePlans] = useState(false); const [planId, setPlanId] = useState(''); const [withoutPlan, setWithoutPlan] = useState(false);
  const [title, setTitle] = useState<Title>(emptyTitle); const [style, setStyle] = useState(''); const [acknowledge, setAcknowledge] = useState(false);
  const [checked, setChecked] = useState<{ signature: string; report: Report } | null>(null); const [busy, setBusy] = useState(true); const [error, setError] = useState(''); const [status, setStatus] = useState(''); const [touched, setTouched] = useState(false);
  const downloadUrl = useRef<string | null>(null);
  const settings = { manuscript_revision_id: revisionId, plan_revision_id: planId || null, without_plan: withoutPlan, profile, title_page: title, citation_style: style };
  const signature = JSON.stringify(settings); const current = checked?.signature === signature;
  useEffect(() => { onDirty(touched || busy); }, [touched, busy, onDirty]);
  useEffect(() => { setAcknowledge(false); }, [unsaved]);
  useEffect(() => { const guard = (event: BeforeUnloadEvent) => { if (touched || busy) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard); }, [touched, busy]);
  useEffect(() => () => { if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current); }, []);
  async function run(action: () => Promise<void>) { setBusy(true); setError(''); setStatus(''); try { await action(); } catch (e) { setError(e instanceof Error ? e.message : 'Не удалось создать экспорт.'); } finally { setBusy(false); } }
  async function load() {
    const [config, saved, history] = await Promise.all([api<Options>(`${path}/exports/options`), api<RevisionSummary[]>(`${path}/manuscript/revisions`), api<Plan[]>(`${path}/research-plan/revisions`)]);
    setOptions(config); setProfile(config.profiles[0]?.profile ?? null); setPreset(config.profiles[0]?.id ?? ''); setRevisions(saved); setMoreRevisions(saved.length === 20); setRevisionId(saved[0]?.id ?? ''); setPlans(history); setMorePlans(history.length === 20);
  }
  useEffect(() => { void run(load); }, [path]);
  function download(blob: Blob, name: string) {
    if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    downloadUrl.current = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = downloadUrl.current; link.download = name; document.body.appendChild(link); link.click(); link.remove();
  }
  async function preflight() { const report = await api<Report>(`${path}/exports/preflight`, post(settings)); setChecked({ signature, report }); setStatus(report.can_export ? 'Проверка пройдена. Просмотрите предупреждения перед скачиванием.' : 'Экспорт заблокирован. Исправьте ошибки.'); }
  async function createDocx() {
    if (!current || !checked?.report.can_export || unsaved && !acknowledge) return;
    const response = await fetch(`${path}/exports/docx`, post({ ...settings, preflight_token: checked.report.preflight_token }));
    if (!response.ok) { const data = await response.json(); if (data.detail?.report) setChecked({ signature, report: data.detail.report }); throw new Error(data.detail?.message ?? 'Экспорт не выполнен. Повторите проверку.'); }
    download(await response.blob(), `research-${revisionId}.docx`); setTouched(false); setStatus('DOCX создан и передан браузеру для скачивания. Обновите поля и оглавление в Word (Ctrl+A, F9).');
  }
  const ready = !!revisionId && !!profile && !!style && (unsaved ? acknowledge : true);
  return <section className="card export-panel"><h2>Экспорт в Microsoft Word</h2><p>Экспортируются выбранные сохранённые версии. Текущий черновик рукописи или научного плана в файл не включается.</p>
    {busy && <p role="status">Подготовка экспорта…</p>}{error && <p role="alert">{error}</p>}{status && <p role="status">{status}</p>}
    {!options && <button disabled={busy} onClick={() => run(load)}>Повторить загрузку экспорта</button>}
    {options && profile && <><fieldset disabled={busy} onChange={() => { setTouched(true); setStatus(''); }}>
      <legend>Сохранённые данные</legend><button onClick={() => run(async () => { const [saved, history] = await Promise.all([api<RevisionSummary[]>(`${path}/manuscript/revisions`), api<Plan[]>(`${path}/research-plan/revisions`)]); setRevisions(saved); setMoreRevisions(saved.length === 20); setPlans(history); setMorePlans(history.length === 20); })}>Обновить сохранённые версии для экспорта</button><label>Версия рукописи для экспорта<select value={revisionId} onChange={e => { setRevisionId(e.target.value); setPlanId(''); }}><option value="">Выберите версию</option>{revisions.map(r => <option value={r.id} key={r.id}>Версия {r.number} · {new Date(r.created_at).toLocaleString('ru-RU')}</option>)}</select></label>
      {!revisions.length && <p>Сначала сохраните рукопись в редакторе P2.</p>}
      {moreRevisions && <button onClick={() => run(async () => { const page = await api<RevisionSummary[]>(`${path}/manuscript/revisions?before=${revisions.at(-1)!.number}`); setRevisions([...revisions, ...page]); setMoreRevisions(page.length === 20); })}>Ещё версии для экспорта</button>}
      <label>Научный план для экспорта<select value={planId} onChange={e => { setPlanId(e.target.value); setWithoutPlan(false); }}><option value="">План не выбран</option>{plans.map(p => <option key={p.id} value={p.id}>План {p.number}{p.manuscript_revision_id === revisionId ? ' · та же рукопись' : ' · другая версия рукописи'}</option>)}</select></label>
      {morePlans && <button onClick={() => run(async () => { const page = await api<Plan[]>(`${path}/research-plan/revisions?before=${plans.at(-1)!.number}`); setPlans([...plans, ...page]); setMorePlans(page.length === 20); })}>Ещё научные планы для экспорта</button>}
      <label><input type="checkbox" checked={withoutPlan} onChange={e => { setWithoutPlan(e.target.checked); if (e.target.checked) setPlanId(''); }} />Явно экспортировать без научного плана и автоматических ссылок</label>
      <label>Стиль цитирования<select value={style} onChange={e => setStyle(e.target.value)}><option value="">Выберите стиль</option>{options.citation_styles.map(s => <option value={s.id} key={s.id}>{s.label}</option>)}</select></label>
      <legend>Оформление</legend><label>Профиль оформления<select value={preset} onChange={e => { const selected = options.profiles.find(p => p.id === e.target.value); if (selected) { setProfile(selected.profile); setPreset(selected.id); } }} >{options.profiles.map(p => <option key={p.id} value={p.id}>{p.profile.name}</option>)}</select></label><p>{options.profiles.find(p => p.id === preset)?.description} Изменения ниже применяются к текущему экспорту.</p>
      <label>Название профиля<input maxLength={100} value={profile.name} onChange={e => setProfile({ ...profile, name: e.target.value })} /></label>
      <p>Формат страницы: A4.</p><label>Шрифт<select value={profile.font} onChange={e => setProfile({ ...profile, font: e.target.value })}>{['Times New Roman', 'Arial', 'Calibri'].map(f => <option key={f}>{f}</option>)}</select></label>
      <label>Выравнивание текста<select value={profile.alignment} onChange={e => setProfile({ ...profile, alignment: e.target.value })}><option value="justify">По ширине</option><option value="left">По левому краю</option></select></label>
      {Object.entries(profileLabels).map(([key, label]) => <label key={key}>{label}<input type="number" step="0.05" value={profile[key as keyof Profile] as number} onChange={e => setProfile({ ...profile, [key]: Number(e.target.value) })} /></label>)}
      <label>Верхний колонтитул<input maxLength={500} value={profile.header} onChange={e => setProfile({ ...profile, header: e.target.value })} /></label><label>Текст нижнего колонтитула<input maxLength={500} value={profile.footer} onChange={e => setProfile({ ...profile, footer: e.target.value })} /></label>
      {([['page_numbers', 'Номера страниц по центру снизу'], ['toc', 'Поле оглавления (обновляется в Word)'], ['number_tables', 'Сквозные номера таблиц']] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={profile[key]} onChange={e => setProfile({ ...profile, [key]: e.target.checked })} />{label}</label>)}
      <legend>Титульный лист</legend><label><input type="checkbox" checked={title.enabled} onChange={e => setTitle({ ...title, enabled: e.target.checked })} />Добавить титульный лист</label>
      {title.enabled && <><p>Для точного университетского шаблона нужен предоставленный образец. Все поля заполняет пользователь.</p>{Object.entries(titleLabels).map(([key, label]) => <label key={key}>{label}<input maxLength={500} value={title[key as keyof typeof titleLabels]} onChange={e => setTitle({ ...title, [key]: e.target.value })} /></label>)}<label>Год<input type="number" min={1000} max={2200} value={title.year ?? ''} onChange={e => setTitle({ ...title, year: e.target.value ? Number(e.target.value) : null })} /></label></>}
    </fieldset>
    {unsaved && <section role="alert"><p>Есть несохранённые изменения рукописи или доказательств. Они не попадут в DOCX.</p><label><input type="checkbox" checked={acknowledge} onChange={e => setAcknowledge(e.target.checked)} />Понимаю: экспортировать только выбранные сохранённые версии</label></section>}
    <button disabled={busy || !ready} onClick={() => run(preflight)}>Проверить перед экспортом</button>
    {checked && <section><h3>Предварительный отчёт</h3>{!current && <p role="alert">Параметры изменились. Повторите проверку.</p>}{(['errors', 'warnings', 'info'] as const).map((key, index) => <section key={key}><h4>{['Ошибки', 'Предупреждения', 'Информация'][index]} ({checked.report[key].length})</h4><ul>{checked.report[key].map((item, i) => <li key={i}>{item.message}{item.field && ` Поле: ${noticeLabels[item.field] ?? item.field}`}{item.source_title && ` Источник: ${item.source_title}.`}{item.source_version_id && ` Версия источника: ${item.source_version_id}`}</li>)}</ul></section>)}<button disabled={busy} onClick={() => download(new Blob([JSON.stringify(checked.report, null, 2)], { type: 'application/json' }), 'export-report.json')}>Скачать отчёт проверки</button></section>}
    <button disabled={busy || !ready || !current || !checked?.report.can_export} onClick={() => run(createDocx)}>Создать и скачать DOCX</button><p className="privacy">Настройки входят в манифест DOCX. Титульные данные и отчёт содержат личные сведения — файл сохраняется только по вашему действию скачивания. Настройки экрана живут в памяти вкладки.</p></>}
  </section>;
}
