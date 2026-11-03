import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import ManuscriptBlock from './ManuscriptBlock';
import { newBlock } from './manuscript';
it('edits a linear formula preserving its UUID', async () => {
 const block=newBlock('formula'); const change=vi.fn(); render(<ManuscriptBlock block={block} change={change} index={1} />);
 await userEvent.setup().type(screen.getByLabelText('Текст формулы'),'α'); expect(change).toHaveBeenLastCalledWith({...block,text:'α'});
});
it('edits footnote text without changing its anchor or UUID', async () => {
 const block={ id:'n1',type:'footnote' as const,text:'',anchor:{block_id:'p1',start:0,end:1,quote:'А'} }; const change=vi.fn();
 render(<ManuscriptBlock block={block} document={{schema_version:'2',blocks:[{id:'p1',type:'quote',text:'А'},block]}} change={change} index={2} />);
 await userEvent.setup().type(screen.getByLabelText('Текст сноски'),'Б'); expect(change).toHaveBeenLastCalledWith({...block,text:'Б'});
});
import { mergeRectangle } from './MergedTableFields';
import type { MergedTable } from './manuscript';
it('merges a rectangle without dropping IDs or nonempty cell content', () => {
 const table=newBlock('merged_table') as MergedTable; const ids=table.rows.flatMap(r=>r.cells.map(c=>c.id));
 const next=mergeRectangle(table,0,0,1,1); expect(next.rows.flatMap(r=>r.cells.map(c=>c.id))).toEqual(ids); expect(next.rows[1].cells[1].covered_by).toBe(ids[0]);
 table.rows[1].cells[1].text='Не терять'; expect(()=>mergeRectangle(table,0,0,1,1)).toThrow();
});
it('edits the caption of a saved image preserving its bytes and UUID', async () => {
 const block={id:'im1',type:'image' as const,png_base64:'',text:'',alt:'',width_cm:4}; const change=vi.fn();render(<ManuscriptBlock block={block} change={change} index={1}/>);
 await userEvent.setup().type(screen.getByLabelText('Подпись рисунка'),'А');expect(change).toHaveBeenLastCalledWith({...block,text:'А'});
});

it('keeps the latest caption during asynchronous upload and ignores unmounted reads', async () => {
 class Reader { result='data:image/png;base64,AAA'; onload:(()=>void)|null=null; onerror:(()=>void)|null=null; abort=vi.fn(); readAsDataURL(){pending.push(this);} }
 const pending:Reader[]=[];vi.stubGlobal('FileReader',Reader);
 const block={id:'im-upload',type:'image' as const,png_base64:'',text:'',alt:'',width_cm:4};const change=vi.fn();
 const view=render(<ManuscriptBlock block={block} change={change} index={1}/>);
 await userEvent.setup().upload(screen.getByLabelText('Файл PNG'),new File(['abc'],'image.png',{type:'image/png'}));
 view.rerender(<ManuscriptBlock block={{...block,text:'Новая подпись'}} change={change} index={1}/>);
 act(()=>pending[0].onload?.());expect(change).toHaveBeenLastCalledWith({...block,text:'Новая подпись',png_base64:'AAA'});
 change.mockClear();view.unmount();act(()=>pending[0].onload?.());expect(change).not.toHaveBeenCalled();
});
