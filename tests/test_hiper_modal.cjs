const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(require('node:path').join(__dirname,'../templates/reviews.html'),'utf8');
const clean=s=>s.replace(/\{\{[\s\S]*?\}\}/g,'translation');
const code=clean(html.slice(html.indexOf('  async function generateReply('),html.indexOf('  async function generateNewSuggestion(')));
const handler=html.slice(html.indexOf('  if (hiperCheck) {'),html.indexOf('  if (toggleCons) {'));
const elements={};
for(const id of ['current-internal-id','loading-ai','reply-area','btnNewSuggestion','tone','reply_lang','hiper_compreensiva','consideracoes','reply-text'])elements[id]={value:'',style:{},disabled:false,checked:false};
elements['current-internal-id'].value='42';elements['reply-text'].value='Resposta anterior';
let onChange;elements.hiper_compreensiva.addEventListener=(event,fn)=>{assert.equal(event,'change');onChange=fn;};
const calls=[],pending=[],notices=[];
const ctx={document:{getElementById:id=>elements[id]},hiperCheck:elements.hiper_compreensiva,generationSerial:0,generationPending:false,csrfToken:'csrf',carregarContadores(){},toast:msg=>notices.push(msg),fetch:(url,opts)=>{calls.push({url,body:JSON.parse(opts.body)});return new Promise(resolve=>pending.push(resolve));}};
vm.createContext(ctx);vm.runInContext(code+'\n'+handler,ctx);
const done=()=>new Promise(resolve=>setImmediate(resolve));
const response=text=>({ok:true,status:200,json:async()=>({success:true,suggested_reply:text})});
(async()=>{
 elements.hiper_compreensiva.checked=true;onChange();assert.equal(calls[0].body.hiper_compreensiva,true);assert.equal(calls[0].body.review_id,'42');assert.equal(ctx.generationPending,true);
 elements.hiper_compreensiva.checked=false;onChange();pending[1](response('Nova resposta normal'));await done();pending[0](response('Resposta hiper atrasada'));await done();assert.equal(elements['reply-text'].value,'Nova resposta normal');assert.equal(ctx.generationPending,false);
 elements.hiper_compreensiva.checked=true;onChange();pending[2]({ok:false,status:500,json:async()=>({error:'Falha da IA'})});await done();assert.equal(elements['reply-text'].value,'Nova resposta normal');assert.equal(notices[0],'Falha da IA');assert.equal(elements.btnNewSuggestion.disabled,false);
 console.log('Passed: hiper toggle regenerates; stale response ignored; failure preserves text.');
})().catch(e=>{console.error(e);process.exitCode=1;});

