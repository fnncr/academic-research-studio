export type Paragraph = { id: string; type: 'paragraph'; text: string; marks: ('bold' | 'italic')[]; origin: 'manual' | 'docx_plain_text' | 'pdf_plain_text'; page: number | null };
export type Heading = { id: string; type: 'heading'; text: string; level: number };
export type Quote = { id: string; type: 'quote'; text: string };
export type ListBlock = { id: string; type: 'list'; ordered: boolean; items: Paragraph[] };
export type Cell = { id: string; text: string };
export type Table = { id: string; type: 'table'; rows: { id: string; cells: Cell[] }[] };
export type Citation = { id: string; type: 'citation_placeholder'; label: string; locator: string };
export type ImageBlock = { id: string; type: 'image'; png_base64: string; text: string; alt: string; width_cm: number };
export type MergeCell = Cell & { row_span: number; col_span: number; covered_by: string | null };
export type MergedTable = { id: string; type: 'merged_table'; rows: { id: string; cells: MergeCell[] }[] };
export type Footnote = { id: string; type: 'footnote'; text: string; anchor: { block_id: string; start: number; end: number; quote: string } | null };
export type Formula = { id: string; type: 'formula'; text: string };
export type Block = Paragraph | Heading | Quote | ListBlock | Table | Citation | Formula | Footnote | MergedTable | ImageBlock;
export type ManuscriptDocument = { schema_version: '1' | '2'; blocks: Block[] };
export type RevisionSummary = { id: string; project_id: string; number: number; parent_id: string | null; restored_from_id: string | null; content_hash: string; created_at: string };
export type Revision = RevisionSummary & { document: ManuscriptDocument };
export const emptyDocument = (): ManuscriptDocument => ({ schema_version: '1', blocks: [] });
export const paragraph = (text = ''): Paragraph => ({ id: crypto.randomUUID(), type: 'paragraph', text, marks: [], origin: 'manual', page: null });
export const cell = (): Cell => ({ id: crypto.randomUUID(), text: '' });
export function newBlock(type: Block['type']): Block {
  const id = crypto.randomUUID();
  switch (type) {
    case 'image': return { id, type, png_base64: '', text: '', alt: '', width_cm: 12 };
    case 'merged_table': return { id, type, rows: [0,1].map(() => ({ id: crypto.randomUUID(), cells: [0,1].map(() => ({ ...cell(), row_span: 1, col_span: 1, covered_by: null })) })) };
    case 'footnote': return { id, type, text: '', anchor: null };
    case 'formula': return { id, type, text: '' };
    case 'paragraph': return paragraph();
    case 'heading': return { id, type, text: '', level: 1 };
    case 'quote': return { id, type, text: '' };
    case 'list': return { id, type, ordered: false, items: [paragraph()] };
    case 'table': return { id, type, rows: [0, 1].map(() => ({ id: crypto.randomUUID(), cells: [cell(), cell()] })) };
    case 'citation_placeholder': return { id, type, label: '', locator: '' };
  }
}
export const labels: Record<Block['type'], string> = { image: 'Изображение PNG', merged_table: 'Таблица с объединением', footnote: 'Сноска', formula: 'Формула', heading: 'Заголовок', paragraph: 'Абзац', quote: 'Цитата', list: 'Список', table: 'Таблица', citation_placeholder: 'Заготовка ссылки' };
export const importWarning = 'Импортирован только текст: заголовки, списки, таблицы, сноски, ссылки и форматирование автоматически не восстанавливаются. Проверьте порядок фрагментов; структуру создайте вручную. Оригинал файла не сохраняется.';
export function importedBlocks(format: 'docx' | 'pdf', chunks: { text: string; page: number | null }[]): Paragraph[] {
  // Keep extraction chunks intact; do not guess headings, table cells or citations.
  return chunks.map(chunk => ({ ...paragraph(chunk.text), origin: `${format}_plain_text`, page: chunk.page }));
}
export function documentProblem(document: ManuscriptDocument): string | null {
  const images=document.blocks.filter((b):b is ImageBlock=>b.type==='image');
  if(images.some(b=>!b.png_base64)||images.reduce((sum,b)=>sum+b.png_base64.length,0)>1500000) return 'Добавьте PNG; общий размер данных изображений — до 1,5 млн символов base64.';
  let nodes = 0; let chars = 0; let longText = false;
  const visit = (value: unknown) => {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === 'object') {
      for (const [key, item] of Object.entries(value)) {
        if (key === 'id') nodes++;
        if (typeof item === 'string' && ['text', 'label', 'locator'].includes(key)) {
          chars += [...item].length;
          if ([...item].length > (key === 'text' ? 20000 : 500) || item.includes('\0')) longText = true;
        }
        if (typeof item === 'object') visit(item);
      }
    }
  };
  visit(document);
  if (longText || document.blocks.length > 1000 || nodes > 2000 || chars > 250000) return 'Лимит рукописи: 1000 блоков, 2000 узлов, 250 000 символов; до 20 000 символов в текстовом поле и 500 в ссылке. Разделите слишком длинные фрагменты.';
  return null;
}
export function describeBlock(block: Block): string {
  switch (block.type) {
    case 'footnote': return `Сноска к «${block.anchor?.quote ?? 'не выбрано'}»\n${block.text}`;
    case 'formula': return `Формула (линейная запись Word)\n${block.text}`;
    case 'heading': return `Заголовок ${block.level}\n${block.text}`;
    case 'paragraph': return `Абзац · ${block.marks.join(', ') || 'обычный'} · ${block.origin}${block.page ? ` · стр. ${block.page}` : ''}\n${block.text}`;
    case 'quote': return `Цитата (источник требует проверки)\n${block.text}`;
    case 'list': return block.items.map((item, i) => `${block.ordered ? `${i + 1}.` : '•'} ${describeBlock(item)}`).join('\n');
    case 'image': return `Рисунок: ${block.text}\n${block.alt} · ${block.width_cm} см · ${block.png_base64.length} символов данных`;
    case 'merged_table': return `Таблица с объединением\n${block.rows.map(row=>row.cells.filter(c=>!c.covered_by).map(c=>`${c.text} (${c.row_span}×${c.col_span})`).join(' | ')).join('\n')}`;
    case 'table': return `Таблица ${block.rows.length} × ${block.rows[0].cells.length}\n${block.rows.map(row => row.cells.map(c => c.text).join(' | ')).join('\n')}`;
    case 'citation_placeholder': return `Непроверенная ссылка: ${block.label}\nЛокатор: ${block.locator}`;
  }
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
  return JSON.stringify(value);
}
export const sameDocument = (a: ManuscriptDocument, b: ManuscriptDocument) => canonical(a) === canonical(b);
export function diffDocuments(before: ManuscriptDocument, after: ManuscriptDocument) {
  const old = new Map(before.blocks.map((block, index) => [block.id, { block, index }]));
  const next = new Set(after.blocks.map(block => block.id));
  const changes: { id: string; label: string; before: string; after: string }[] = [];
  for (const [id, { block, index }] of old) if (!next.has(id)) changes.push({ id, label: `Удалён блок ${index + 1}`, before: describeBlock(block), after: '' });
  after.blocks.forEach((block, index) => {
    const previous = old.get(block.id);
    if (!previous) changes.push({ id: block.id, label: `Добавлен блок ${index + 1}`, before: '', after: describeBlock(block) });
    else if (canonical(previous.block) !== canonical(block) || previous.index !== index) changes.push({ id: block.id, label: `Блок ${previous.index + 1} → ${index + 1}: ${canonical(previous.block) !== canonical(block) ? 'изменён' : 'перемещён'}`, before: describeBlock(previous.block), after: describeBlock(block) });
  });
  return changes;
}
