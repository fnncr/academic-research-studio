import { useState } from 'react';
import type { Block, MergedTable } from './manuscript';
export function mergeRectangle(block: MergedTable, r: number, c: number, endRow: number, endCol: number): MergedTable {
 if (r<0||c<0||endRow<r||endCol<c||endRow>=block.rows.length||endCol>=block.rows[0].cells.length) throw new Error('Выберите прямоугольник внутри таблицы.');
 const next=structuredClone(block); const owner=next.rows[r].cells[c];
 for(let rr=r;rr<=endRow;rr++) for(let cc=c;cc<=endCol;cc++) { const cell=next.rows[rr].cells[cc]; if(cell.covered_by||cell.row_span!==1||cell.col_span!==1) throw new Error('Сначала разделите существующее объединение.'); if((rr!==r||cc!==c)&&cell.text) throw new Error('Перенесите текст в верхнюю левую ячейку перед объединением.'); }
 owner.row_span=endRow-r+1;owner.col_span=endCol-c+1;
 for(let rr=r;rr<=endRow;rr++) for(let cc=c;cc<=endCol;cc++) if(rr!==r||cc!==c) next.rows[rr].cells[cc].covered_by=owner.id;
 return next;
}
export default function MergedTableFields({block,change}:{block:MergedTable;change:(value:Block)=>void}) {
 const [rect,setRect]=useState([1,1,1,2]);const [error,setError]=useState('');
 function split(id:string) {change({...block,rows:block.rows.map(r=>({...r,cells:r.cells.map(c=>c.id===id||c.covered_by===id?{...c,row_span:1,col_span:1,covered_by:null}:c)}))});}
 return <>{error&&<p role="alert">{error}</p>}<div className="table-scroll"><table><tbody>{block.rows.map((row,r)=><tr key={row.id}>{row.cells.map((c,col)=>c.covered_by?null:<td key={c.id} rowSpan={c.row_span} colSpan={c.col_span}><textarea aria-label={`Объединяемая строка ${r+1}, столбец ${col+1}`} value={c.text} maxLength={20000} onChange={e=>change({...block,rows:block.rows.map(old=>({...old,cells:old.cells.map(cell=>cell.id===c.id?{...cell,text:e.target.value}:cell)}))})}/>{(c.row_span>1||c.col_span>1)&&<button type="button" onClick={()=>split(c.id)}>Разделить ячейку {r+1},{col+1}</button>}</td>)}</tr>)}</tbody></table></div>{['Начальная строка','Начальный столбец','Конечная строка','Конечный столбец'].map((label,i)=><label key={label}>{label}<input type="number" min={1} value={rect[i]} onChange={e=>setRect(rect.map((v,j)=>j===i?Number(e.target.value):v))}/></label>)}<button type="button" onClick={()=>{try{change(mergeRectangle(block,rect[0]-1,rect[1]-1,rect[2]-1,rect[3]-1));setError('');}catch(e){setError((e as Error).message);}}}>Объединить прямоугольник</button><p>Текст покрываемых ячеек должен быть пустым; UUID всех ячеек сохраняются. Для изменения размеров разделите ячейки и вернитесь к обычной таблице.</p><button type="button" disabled={block.rows.some(r=>r.cells.some(c=>c.covered_by||c.row_span!==1||c.col_span!==1))} onClick={()=>change({...block,type:'table',rows:block.rows.map(r=>({...r,cells:r.cells.map(c=>({id:c.id,text:c.text}))}))})}>Вернуть обычную таблицу</button></>;
}
