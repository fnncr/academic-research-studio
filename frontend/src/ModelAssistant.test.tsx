import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import ModelAssistant from './ModelAssistant';
import { restore, persist, storageKey } from './modelAssistant';
const r={id:'r1',number:1,document:{schema_version:'1',blocks:[{id:'h1',type:'heading',level:1,text:'Метод'}]}};
const p={id:'p1',number:1,manuscript_revision_id:'r1',document:{claims:[{id:'c1',statement:'Тезис',section_id:'h1',evidence:[{evidence_id:'e1',relation:'contradicts',rationale:'Контраргумент'}]}],citations:[]}};
const task={request_id:'request-fixed',brief_revision_id:'b1',manuscript_revision_id:'r1',plan_revision_id:'p1',claim_ids:['c1'],title:'Метод',instruction:'Тест',max_output_tokens:2000,provider:'mock' as const,model:'mock-grounded-v1' as const};
function server(){let job:any=null;const mutations:any[]=[];let lost=false;let lostAccept=false;
 const fetch=vi.fn(async(url:string,options?:RequestInit)=>{const body=options?.body?JSON.parse(options.body as string):null;if(body)mutations.push({url,body});let value:any;
 if(url.endsWith('/capabilities'))value={provider:'mock',external_enabled:false};
 else if(url.endsWith('/budget'))value={limit_units:10000,spent_units:0,reserved_units:0,blocked:false};
 else if(url.endsWith('/preview'))value={fingerprint:'fp',input:{task:body,context:{evidence:['RU/EN'],locator:'unverified'},quote:{max_units:100,input_token_bound:200,output_token_cap:2000},disclosure:'mock local'}};
 else if(url.endsWith('/model-jobs')&&body){job={id:'j1',state:'queued',cancel_requested:false,task:body.task};if(lost)throw new Error('lost');value=job;}
 else if(url.includes('/by-request/')){if(!job)return {ok:false,status:404,json:async()=>({})};value=job;}
 else if(url.endsWith('/model-jobs'))value=job?[job]:[];
 else if(url.endsWith('/cancel')){job={...job,state:'cancelled',cancel_requested:true};value=job;}
 else if(url.endsWith('/accept')){if(lostAccept){lostAccept=false;throw new Error('lost response');}job={...job,acceptance:{manuscript_revision_id:'r2'}};value={manuscript_revision_id:'r2'};}
 else if(url.includes('/model-jobs/j1'))value=job;
 else if(url.includes('/research-plan/revisions/'))value=p;
 else if(url.includes('/research-plan/revisions'))value=[p];
 else if(url.endsWith('/research-plan'))value=p;
 else if(url.includes('/manuscript/revisions/'))value=r;
 else if(url.includes('/manuscript/revisions'))value=[r];
 else if(url.endsWith('/manuscript'))value=r;
 else if(url.includes('/evidence/'))value={id:'e1',source_version_id:'v1',source_version:{metadata:{title:'Foreign source'}},content:{original_language:'en',selection:{quote:'Original contradiction'},locator:{label:'12'}}};
 else value={latest_brief:{id:'b1'}};
 return {ok:true,status:200,json:async()=>value};});vi.stubGlobal('fetch',fetch);return {fetch,mutations,lose:()=>{lost=true;},loseAccept:()=>{lostAccept=true;},setJob:(value:any)=>job=value};}
const busy=vi.fn();const accepted=vi.fn(async()=>{});
async function connect(){const user=userEvent.setup();await user.type(screen.getByLabelText('Ключ владельца помощника'),'private-token');await user.click(screen.getByRole('button',{name:'Подключить помощника / восстановить задачи'}));await screen.findByText(/Провайдер: mock/);return user;}
beforeEach(()=>{sessionStorage.clear();vi.clearAllMocks();});
it('leaves manual mode available without a key and never stores the token',()=>{server();render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);expect(screen.getByRole('button',{name:'Подключить помощника / восстановить задачи'})).toBeDisabled();expect(screen.getByText(/Локальная шаблонная композиция/)).toBeVisible();expect(sessionStorage.length).toBe(0);});
it('previews original contradictions and requires specific consent before enqueue',async()=>{const s=server();render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);const user=await connect();await user.selectOptions(screen.getByLabelText('Версия рукописи'),'r1');await screen.findByLabelText('Тезис');await user.click(screen.getByLabelText('Тезис'));await user.type(screen.getByLabelText('Название нового раздела'),'Раздел');expect(screen.getByText(/Противоречит/)).toBeVisible();await user.click(screen.getByRole('button',{name:'Предпросмотр контекста и стоимости'}));await screen.findByText('Точный контекст запроса');expect(screen.getByRole('button',{name:'Создать задание'})).toBeDisabled();await user.click(screen.getByLabelText(/Разрешаю этот конкретный/));await user.click(screen.getByRole('button',{name:'Создать задание'}));await screen.findByText('В очереди');expect(s.mutations.filter(m=>m.url.endsWith('/model-jobs'))).toHaveLength(1);expect(sessionStorage.getItem(storageKey('x'))).not.toContain('private-token');});
it('recovers the same UUID after a lost enqueue response without automatically sending',async()=>{const s=server();persist('x',{task,fingerprint:'fp'});s.setJob({id:'j1',task,state:'ambiguous',cancel_requested:false});render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);await connect();await screen.findByRole('heading',{name:/Исход неизвестен —/});expect(restore('x').task?.request_id).toBe('request-fixed');expect(s.mutations).toHaveLength(0);expect(screen.getByText(/нового запроса автоматически/)).toBeVisible();});
it('blocks acceptance for unsaved changes and renders hostile result as text',async()=>{const s=server();persist('x',{jobId:'j1'});s.setJob({id:'j1',task,state:'succeeded',result:{paragraphs:['<script>alert(1)</script>'],research_gaps:[{explanation:'Нужны данные'}]},cancel_requested:false});render(<ModelAssistant projectId="x" unsaved onBusy={busy} onAccepted={accepted}/>);const user=await connect();await screen.findByText('<script>alert(1)</script>');await user.click(screen.getByLabelText(/Я проверил текст/));expect(screen.getByRole('button',{name:'Принять текст новой версией'})).toBeDisabled();expect(document.querySelector('script')).toBeNull();});
it('cancels with a durable decision UUID and no new generation',async()=>{const s=server();persist('x',{jobId:'j1'});s.setJob({id:'j1',task,state:'queued',cancel_requested:false});render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);const user=await connect();await user.click(await screen.findByRole('button',{name:'Отменить задание / отклонить предложение'}));await waitFor(()=>expect(s.mutations.some(m=>m.url.endsWith('/cancel'))).toBe(true));expect(restore('x').cancel?.request_id).toBeTruthy();expect(s.mutations.filter(m=>m.url.endsWith('/model-jobs'))).toHaveLength(0);});

it('resets consent when manuscript state changes',async()=>{server();persist('x',{task});const view=render(<ModelAssistant projectId="x" savedId="r1" unsaved={false} onBusy={busy} onAccepted={accepted}/>);const user=await connect();await user.click(screen.getByRole('button',{name:'Предпросмотр контекста и стоимости'}));await user.click(await screen.findByLabelText(/Разрешаю этот конкретный/));view.rerender(<ModelAssistant projectId="x" savedId="r2" unsaved={false} onBusy={busy} onAccepted={accepted}/>);expect(screen.queryByRole('button',{name:'Создать задание'})).not.toBeInTheDocument();});
it('refuses stale heads before acceptance and never sends an apply request',async()=>{const s=server();persist('x',{jobId:'j1'});s.setJob({id:'j1',task:{...task,manuscript_revision_id:'r-old'},state:'succeeded',result:{paragraphs:['Proposal']},cancel_requested:false});render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);const user=await connect();await screen.findByText('Proposal');await user.click(screen.getByLabelText(/Я проверил текст/));await user.click(screen.getByRole('button',{name:'Принять текст новой версией'}));await screen.findByText(/Конфликт версий/);expect(s.mutations.some(m=>m.url.endsWith('/accept'))).toBe(false);});
it('shows API failure without creating a task',async()=>{vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:503,json:async()=>({})})));render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);const user=userEvent.setup();await user.type(screen.getByLabelText('Ключ владельца помощника'),'not-stored');await user.click(screen.getByRole('button',{name:'Подключить помощника / восстановить задачи'}));await screen.findByRole('alert');expect(restore('x')).toEqual({});});

it('reuses acceptance UUID after a lost response and restores the immutable receipt',async()=>{
 vi.stubGlobal('crypto',{randomUUID:()=>`uuid-${Math.random()}`,subtle:{digest:async()=>new Uint8Array(32).buffer}});const s=server();persist('x',{jobId:'j1'});s.setJob({id:'j1',task,state:'succeeded',result:{paragraphs:['Accepted proposal']},cancel_requested:false});s.loseAccept();
 render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);const user=await connect();await screen.findByText('Accepted proposal');await user.click(screen.getByLabelText(/Я проверил текст/));await user.click(screen.getByRole('button',{name:'Принять текст новой версией'}));await screen.findByRole('alert');const first=restore('x').accept?.request_id;expect(first).toBeTruthy();await user.click(screen.getByRole('button',{name:'Принять текст новой версией'}));await screen.findByText(/Текст принят новой версией/);const calls=s.mutations.filter(m=>m.url.endsWith('/accept'));expect(calls).toHaveLength(2);expect(calls[0].body).toEqual(calls[1].body);expect(calls[0].body.request_id).toBe(first);
});

it('offers disabled real provider transparently and retains request-specific consent',async()=>{
 const s=server();const original=s.fetch.getMockImplementation()!;
 s.fetch.mockImplementation(async(url:string,options?:RequestInit)=>url.endsWith('/capabilities')?{ok:true,status:200,json:async()=>({provider:'mock',external_enabled:false,providers:[{id:'mock',model:'mock-grounded-v1',ready:true},{id:'openai',model:'gpt-4.1-mini-2025-04-14',ready:false,disclosure:'External retention policy'}]})}:original(url,options));
 render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);const user=await connect();
 await user.selectOptions(screen.getByLabelText('Провайдер и модель'),'openai');
 expect(screen.getByText(/Реальная LLM OpenAI/)).toBeVisible();expect(screen.getByText(/External retention policy/)).toBeVisible();
 expect(s.mutations).toHaveLength(0);expect(screen.queryByRole('button',{name:'Создать задание'})).not.toBeInTheDocument();
});


it('explains billing drift without resending the task',async()=>{
 const s=server();persist('x',{jobId:'j1'});s.setJob({id:'j1',task,state:'ambiguous',cancel_requested:false,report:{code:'unconfirmed_billing'}});
 render(<ModelAssistant projectId="x" unsaved={false} onBusy={busy} onAccepted={accepted}/>);await connect();
 expect(await screen.findByText(/Тарификация ответа провайдера не подтверждена/)).toBeVisible();expect(s.mutations).toHaveLength(0);
});
