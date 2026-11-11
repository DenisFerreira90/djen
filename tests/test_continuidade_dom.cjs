const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const values=new Map(),timers=[],calls=[];class E{constructor(){this.children=[];}append(...x){this.children.push(...x);}replaceChildren(){this.children=[];}before(x){elements.set(x.id,x);}}
const elements=new Map([['content',new E()]]);const J={S:{user:{id:1}},isOwner:()=>true,el:(t,c,text)=>({textContent:text}),button:(t,fn)=>({textContent:t,onclick:fn}),go:()=>{},request:async(path,body)=>{calls.push([path,body]);return {atual:{estado:'coletando',tribunal:'TJSC',lidos:7,salvos_sistema:5}};}};
const ctx={window:{Juridico:J},document:{getElementById:id=>elements.get(id)},sessionStorage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){}};vm.createContext(ctx);const source=fs.readFileSync(require.resolve('../js/continuidade.js'),'utf8');vm.runInContext(source,ctx);
(async()=>{
 const N=ctx.window.NavigationState;N.save(1,{view:'mandados',tab:'alertas'});assert.equal(N.load(1).view,'mandados');assert.equal(N.tab(1),'alertas');assert.equal(N.tab(2),'monitoramento');
 // Simula F5: novo contexto JS, mesma sessão do navegador.
 const restored={...ctx,window:{Juridico:J}};vm.createContext(restored);vm.runInContext(source,restored);assert.equal(restored.window.NavigationState.load(1).view,'mandados');assert.equal(restored.window.NavigationState.tab(1),'alertas');
 J.el=(t,c,text)=>{const e=new E();e.textContent=text;return e;};ctx.window.CollectionIndicator.start();await new Promise(setImmediate);assert(elements.get('collectionContinuity').children.some(x=>x.textContent?.includes('em andamento')));
 J.S.view='pessoas';await timers.pop()();assert(calls.length>=2);assert(calls.every(([p,b])=>p==='/api/eproc/status'&&b===undefined));assert(!calls.some(([p])=>p.includes('cancelar')));
 J.isOwner=()=>false;const before=calls.length;ctx.window.CollectionIndicator.start();await new Promise(setImmediate);assert.equal(calls.length,before);assert.equal(elements.get('collectionContinuity').hidden,true);
 console.log('Navegação por usuário, restauração após recarga e consulta de progresso sem cancelamento aprovadas.');
})().catch(e=>{console.error(e);process.exit(1);});
