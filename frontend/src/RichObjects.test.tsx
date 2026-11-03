import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import ManuscriptBlock from './ManuscriptBlock';
import { newBlock } from './manuscript';
it('edits a linear formula preserving its UUID', async () => {
 const block=newBlock('formula'); const change=vi.fn(); render(<ManuscriptBlock block={block} change={change} index={1} />);
 await userEvent.setup().type(screen.getByLabelText('Текст формулы'),'α'); expect(change).toHaveBeenLastCalledWith({...block,text:'α'});
});
