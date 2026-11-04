// Behavior checks in a simulated DOM, not visual browser validation.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
class E{constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.value='';this.attributes={};}append(...nodes){for(const n of nodes){this.children.push(n);if(n&&typeof n==='object')n.parent=this;}}replaceChildren(...nodes){this.children=[];this.append(...nodes);}setAttribute(k,v){this.attributes[k]=v;}scrollIntoView(){}}
const all=e=>[e,...e.children.flatMap(n=>n&&typeof n==='object'?all(n):[])];
const el=(tag,cls,text)=>{const n=new E(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n;};
const option=class extends E{constructor(t,v){super('option');this.textContent=t;this.value=v;}};
const rows=[{id:'TJRS-1',tribunal:'TJRS',nome:'Tribunal de Justiça Rio Grande do Sul',ramo:'Estadual',uf:'RS',grau:'1',sistema:'eproc',url:'https://eproc1g.tjrs.jus.br/eproc/',cor:'verde',manutencoes:[]},{id:'TJRS-2',tribunal:'TJRS',nome:'Tribunal de Justiça Rio Grande do Sul',ramo:'Estadual',uf:'RS',grau:'2',sistema:'eproc',url:'https://eproc2g.tjrs.jus.br/eproc/',cor:'vermelho',manutencoes:[]},{id:'TJSC-1',tribunal:'TJSC',nome:'Tribunal de Justiça Santa Catarina',ramo:'Estadual',uf:'SC',grau:'1',sistema:'eproc',url:null,cor:'cinza',manutencoes:[],ativo:false}];
const courts=[{id:'TJRS',nome:'Rio Grande do Sul',ramo:'Estadual',portal:'https://www.tjrs.jus.br/'},{id:'TJSC',nome:'Santa Catarina',ramo:'Estadual',portal:'https://www.tjsc.jus.br/',ativo:false}];
async function test(role){const root=new E('main'),calls=[],tables=[];
const data={resumo:{verde:1,amarelo:0,vermelho:1,cinza:1,tribunais:2,enderecos:2,instancias:3,pendentes:1},ativo:true,tribunais:courts,itens:rows,alertas:[],comunicados:[],lembretes:[]};
if(role!=='administrador'){data.tribunais=data.tribunais.filter(t=>t.ativo!==false);data.itens=data.itens.filter(t=>t.ativo!==false);}
const api=async(p,body)=>{calls.push([p,body]);if(p==='jusdown')return data;if(p==='jusdown/verificar')return {iniciado:true};throw Error(p);};
const button=(t,fn,cls)=>{const e=el('button',cls,t);e.onclick=fn;return e;};
const window={Juridico:{S:{user:{id:1,role}},api,el,button,head(){},card(){const e=el('section');root.append(e);return e;},table(h,r,parent){const t=el('table');t.headers=h;t.rows=r;parent.append(t);tables.push(t);},render(){}}};
const c={window,console,Option:option};vm.createContext(c);vm.runInContext(fs.readFileSync(require.resolve('../js/jusdown.js'),'utf8'),c);await window.Jusdown.render();
const selects=all(root).filter(e=>e.tagName==='SELECT');const court=selects.find(e=>e.attributes['aria-label']==='Tribunal'),mode=selects.find(e=>e.attributes['aria-label']==='Situação');
const visibleRows=()=>all(root).filter(e=>e.tagName==='TABLE'&&e.headers[0]==='Portal / grau').reduce((n,t)=>n+t.rows.length,0);
assert.equal(visibleRows(),2);mode.value='vermelho';mode.onchange();assert.equal(visibleRows(),1);
mode.value='todos';mode.onchange();court.value='TJSC';court.onchange();assert.equal(visibleRows(),role==='administrador'?1:0);
if(role==='administrador'){const activation=selects.find(e=>e.attributes['aria-label']==='Ativação do tribunal');activation.value='ativos';activation.onchange();}
const search=all(root).find(e=>e.attributes['aria-label']==='Pesquisar tribunal');court.value='';court.onchange();search.value='rio grande';search.oninput();assert.equal(visibleRows(),2);
if(role==='administrador'){
 court.value='TJRS';court.onchange();const b=all(root).find(e=>e.textContent==='Verificar só TJRS');await b.onclick();assert.equal(JSON.stringify(calls.at(-1)),JSON.stringify(['jusdown/verificar',{tribunal:'TJRS'}]));
 assert(all(root).some(e=>e.textContent==='Adicionar portal'));assert(all(root).some(e=>e.textContent==='Inativar e ocultar da equipe'));
}else assert(!all(root).some(e=>e.textContent==='Verificar todos agora'));
}
(async()=>{await test('administrador');await test('leitor');console.log('JUSDOWN: pesquisa, filtros, graus separados, verificação selecionada e controles por perfil aprovados.');})();
