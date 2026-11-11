const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../js/juridico.js'),'utf8');
const action=source.slice(source.indexOf('async function eprocAction('),source.indexOf('async function refreshEproc()'));
function env(request){const nodes={eprocFeedback:{},eproc_iniciar:{},collectTribunal:{value:'TJSC'},collectInvisible:{checked:true},collectAuthenticator:{value:'7'},collectMode:{value:'incremental'}};const scope={S:{},$:id=>nodes[id],request,refreshEproc:async()=>{}};vm.createContext(scope);vm.runInContext(action,scope);return {scope,nodes};}
(async()=>{
 let calls=0,resolve;const response=new Promise(r=>resolve=r);const a=env(async(path,body)=>{calls++;assert.equal(path,'/api/eproc/iniciar');assert.equal(body.opcoes.tribunal,'TJSC');assert.equal(body.opcoes.teste_sc,true);assert.equal(body.opcoes.invisivel,true);assert.equal(body.opcoes.autenticador_id,7);return response;});
 const pending=a.scope.eprocAction('iniciar');assert.equal(a.nodes.eproc_iniciar.disabled,true);await a.scope.eprocAction('iniciar');assert.equal(calls,1);resolve({atual:{id:'real-run',tribunal:'TJSC'}});await pending;assert.match(a.nodes.eprocFeedback.textContent,/Execução criada: real-run/);
 const b=env(async()=>{throw Error('Autenticador inválido');});await b.scope.eprocAction('iniciar');assert.match(b.nodes.eprocFeedback.textContent,/Comando não concluído: Autenticador inválido/);assert.equal(b.nodes.eprocFeedback.hidden,false);assert.equal(b.nodes.eproc_iniciar.disabled,false);
 const c=env(async()=>({}));await c.scope.eprocAction('iniciar');assert.match(c.nodes.eprocFeedback.textContent,/não confirmou/);
 console.log('3 verificações do botão passaram');
})().catch(e=>{console.error(e);process.exitCode=1;});
