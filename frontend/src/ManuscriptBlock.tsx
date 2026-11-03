import { cell, paragraph, type Block, type Paragraph } from './manuscript';

function ParagraphFields({ block, change, label }: { block: Paragraph; change: (value: Paragraph) => void; label: string }) {
  return <><label>{label}<textarea maxLength={20000} value={block.text} onChange={e => change({ ...block, text: e.target.value })} /></label>
    <div className="editor-actions">{(['bold', 'italic'] as const).map(mark => <label key={mark}><input type="checkbox" checked={block.marks.includes(mark)} onChange={e => change({ ...block, marks: e.target.checked ? [...block.marks, mark] : block.marks.filter(m => m !== mark) })} />{mark === 'bold' ? 'Полужирный абзац' : 'Курсивный абзац'}</label>)}</div>
    {block.origin !== 'manual' && <p className="privacy">Импортированный текст{block.page ? ` · страница ${block.page}` : ''}. Исходное форматирование неизвестно.</p>}</>;
}

export default function ManuscriptBlock({ block, change, index }: { block: Block; change: (value: Block) => void; index: number }) {
  switch (block.type) {
    case 'formula': return <><p>Линейная запись Unicode, не LaTeX. В Word экспортируется редактируемая формула.</p><label>Текст формулы<textarea maxLength={20000} value={block.text} onChange={e => change({ ...block, text: e.target.value })} /></label><div aria-label="Предпросмотр формулы">{block.text}</div></>;
    case 'paragraph': return <ParagraphFields block={block} change={change} label={`Текст блока ${index}`} />;
    case 'heading': return <><label>Уровень заголовка<select value={block.level} onChange={e => change({ ...block, level: Number(e.target.value) })}>{[1, 2, 3, 4, 5, 6].map(n => <option key={n}>{n}</option>)}</select></label><label>Текст заголовка<input maxLength={20000} value={block.text} onChange={e => change({ ...block, text: e.target.value })} /></label></>;
    case 'quote': return <label>Текст цитаты (ссылку добавьте отдельно)<textarea maxLength={20000} value={block.text} onChange={e => change({ ...block, text: e.target.value })} /></label>;
    case 'citation_placeholder': return <><p className="privacy">Это заготовка, а не проверенная библиографическая ссылка.</p><label>Источник или задача поиска<input maxLength={500} value={block.label} onChange={e => change({ ...block, label: e.target.value })} /></label><label>Страница или раздел источника<input maxLength={500} value={block.locator} onChange={e => change({ ...block, locator: e.target.value })} /></label></>;
    case 'list': return <><label><input type="checkbox" checked={block.ordered} onChange={e => change({ ...block, ordered: e.target.checked })} />Нумерованный список</label>
      {block.items.map((item, i) => <div className="list-item" key={item.id}><ParagraphFields block={item} label={`Пункт ${i + 1}`} change={next => change({ ...block, items: block.items.map(old => old.id === next.id ? next : old) })} />
        <button type="button" disabled={block.items.length === 1} onClick={() => change({ ...block, items: block.items.filter(old => old.id !== item.id) })}>Удалить пункт {i + 1}</button></div>)}
      <button type="button" disabled={block.items.length >= 200} onClick={() => change({ ...block, items: [...block.items, paragraph()] })}>Добавить пункт</button></>;
    case 'table': return <><div className="table-scroll"><table><tbody>{block.rows.map((row, r) => <tr key={row.id}>{row.cells.map((c, col) => <td key={c.id}><textarea aria-label={`Строка ${r + 1}, столбец ${col + 1}`} maxLength={20000} value={c.text} onChange={e => change({ ...block, rows: block.rows.map(oldRow => oldRow.id === row.id ? { ...row, cells: row.cells.map(old => old.id === c.id ? { ...c, text: e.target.value } : old) } : oldRow) })} /></td>)}</tr>)}</tbody></table></div>
      <div className="editor-actions"><button type="button" disabled={block.rows.length >= 100} onClick={() => change({ ...block, rows: [...block.rows, { id: crypto.randomUUID(), cells: block.rows[0].cells.map(() => cell()) }] })}>Добавить строку</button>
        <button type="button" disabled={block.rows[0].cells.length >= 20} onClick={() => change({ ...block, rows: block.rows.map(row => ({ ...row, cells: [...row.cells, cell()] })) })}>Добавить столбец</button>
        <button type="button" disabled={block.rows.length === 1} onClick={() => change({ ...block, rows: block.rows.slice(0, -1) })}>Удалить последнюю строку</button>
        <button type="button" disabled={block.rows[0].cells.length === 1} onClick={() => change({ ...block, rows: block.rows.map(row => ({ ...row, cells: row.cells.slice(0, -1) })) })}>Удалить последний столбец</button></div></>;
  }
}
