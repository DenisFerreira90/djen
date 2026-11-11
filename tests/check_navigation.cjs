const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
class E{constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[];this.hidden=false;this.classList={};}append(...x){this.children.push(...x)}prepend(...x){this.children.unshift(...x)}setAttribute(){}replaceChildren(...x){this.children=x}}
(async()=>{for(const view of ['mandados','coletas','avisos']){
 const content=new E('main'),calls=[];let heads=[];
 const data={pendentes:0,itens:[],resumos:[],estado:{},numeros:[],sem_cadastro:[],cobertura:'Teste'};
 const J={S:{user:{id:1,role:'administrador'},view},api:async p=>{calls.push(p);if(p==='mandados')return data;if(p==='email')return {historico:[]};if(p==='email/resumos')return {itens:[]};throw Error(p)},head:(...x)=>heads=x,card:()=>{const e=new E('section');content.append(e);return e},el:(tag,cls,text)=>new E(tag,text),button:t=>new E('button',t),table:()=>{},writable:()=>true,isOwner:()=>true,showDetail:()=>{}};
 const ctx={window:{Juridico:J,Monitoramento:{render:async()=>calls.push('monitoramento')}},document:{getElementById:()=>content},setInterval:()=>{},setTimeout:()=>{},clearTimeout:()=>{}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../js/mandados.js'),'utf8'),ctx);await ctx.window.Mandados.render();
 assert.ok(heads[0]);assert.equal(calls.includes('monitoramento'),view==='coletas');assert.equal(calls.includes('email'),view==='avisos');
 const visible=content.children.filter(e=>e.tag==='section'&&!e.hidden);assert.equal(visible.length,1,view+' must expose one main panel');
 console.log(view+': navigation and API isolation OK');
}})().catch(e=>{console.error(e);process.exitCode=1});
