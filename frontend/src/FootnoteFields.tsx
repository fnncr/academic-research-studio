import { useState } from 'react';
import type { Footnote, ManuscriptDocument } from './manuscript';
import { textNodes } from './evidence';
export default function FootnoteFields({ block, document, change }: { block: Footnote; document?: ManuscriptDocument; change: (b: Footnote) => void }) {
 const [target, setTarget]=useState(block.anchor?.block_id ?? ''); const nodes=document ? textNodes({document}).filter(n=>n.type!=='footnote') : []; const selected=nodes.find(n=>n.id===target);
 const valid=block.anchor && selected?.text.slice(block.anchor.start,block.anchor.end)===block.anchor.quote;
 return <><label>Текст сноски<textarea maxLength={20000} value={block.text} onChange={e=>change({...block,text:e.target.value})} /></label><label>Узел для сноски<select value={target} onChange={e=>setTarget(e.target.value)}><option value="">Выберите текст</option>{nodes.map(n=><option value={n.id} key={n.id}>{n.text.slice(0,100)}</option>)}</select></label>{selected && <label>Выделите опорный текст сноски<textarea readOnly value={selected.text} onSelect={e=>{const t=e.currentTarget; if(t.selectionStart<t.selectionEnd) change({...block,anchor:{block_id:target,start:t.selectionStart,end:t.selectionEnd,quote:t.value.slice(t.selectionStart,t.selectionEnd)}});}} /></label>}<p>Привязка: {block.anchor?.quote ?? 'не выбрана'}</p>{!valid && <p role="alert">Выделите опорный текст заново перед сохранением.</p>}</>;
}
