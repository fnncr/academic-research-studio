import { render, screen } from '@testing-library/react';
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
