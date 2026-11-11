const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class E{constructor(tag,cls='',text=''){this.tagName=tag;this.className=cls;this.textContent=text;this.children=[];this.open=false;}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}setAttribute(k,v){this[k]=v;}scrollIntoView(){}}
const root=new E('main'),tables=[],calls=[];
const el=(t,c,s)=>new E(t,c,s),button=(label,action)=>{const b=el('button','',label);b.onclick=action;return b;};
const all=n=>[n,...n.children.filter(x=>x instanceof E).flatMap(all)];
const response=page=>({escopo:'Escritório inteiro',data:'2026-11-06',contagens:{fatais_hoje:201,mandados_pendentes:1},origens_pendentes:{fatais_hoje:1},limite_lista:100,pagina:page,listas:{fatais_hoje:[{id:page,titulo:'Prazo',prazo_titulo:'Manifestação',vencimento:'2026-11-06',origem:{numero:'5000001-00.2026.8.17.0001',tribunal:'TJPE',sistema:'PJe',grau:'2º grau',comarca:'Recife',orgao:'Órgão informado',processo_id:7,url:'https://pje.cloud.tjpe.jus.br/2g/',tipo_link:'portal'}}]}});
const J={api:async path=>{calls.push(path);return path==='chat/conversas'?[]:response(Number((path.match(/pagina=(\d+)/)||[])[1]||1));},head(){},card:()=>{const c=el('section');root.append(c);return c;},el,button,table:(headers,rows,parent)=>{tables.push({headers,rows});const t=el('table');for(const row of rows){const tr=el('tr');for(const value of row){const td=el('td');td.append(value instanceof E?value:el('span','',value));tr.append(td);}t.append(tr);}parent.append(t);},showDetail(){},userName:()=> 'Responsável',day:v=>v||'—',go(){},isOwner:()=>true};
const context={window:{Juridico:J},document:{getElementById:()=>root},navigator:{clipboard:{writeText:async()=>{}}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../js/painel-operacional.js'),'utf8'),context);
(async()=>{
 await context.window.PainelOperacional.render();
 const disclosure=all(root).find(n=>n.className.includes('dashboard-records'));
 assert.equal(disclosure.open,false);assert.equal(tables.length,0);
 const fatal=all(root).find(n=>n.className==='stat'&&n.children.some(c=>c.textContent==='Fatalíssimo'));
 await fatal.children.find(n=>n.tagName==='button').onclick();
 assert(disclosure.open);assert(calls.includes('painel-operacional?indicador=fatais_hoje&pagina=1'));
 assert(all(disclosure).some(n=>n.textContent==='2º grau'));
 const link=all(disclosure).find(n=>n.tagName==='a');assert.equal(link.href,'https://pje.cloud.tjpe.jus.br/2g/');assert.equal(link.rel,'noopener noreferrer');assert.equal(link.textContent,'Abrir portal correspondente');
 assert(all(disclosure).filter(n=>n.className==='origin-disclosure').every(n=>!n.open));
 await all(disclosure).find(n=>n.tagName==='button'&&n.textContent==='Próxima').onclick();
 assert(calls.includes('painel-operacional?indicador=fatais_hoje&pagina=2'));
 console.log('Dashboard: totais, detalhes inicialmente recolhidos, origem/grau, link de portal e paginação aprovados em DOM simulado.');
})().catch(error=>{console.error(error);process.exit(1);});
