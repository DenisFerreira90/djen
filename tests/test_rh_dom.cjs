// Teste de montagem com DOM simulado; não equivale a conferência visual.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
class E{constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.value='';this.attributes={};}append(...nodes){for(const n of nodes){this.children.push(n);if(n&&typeof n==='object')n.parent=this;}}replaceChildren(...nodes){this.children=[];this.append(...nodes);}setAttribute(k,v){this.attributes[k]=v;}addEventListener(){}showModal(){this.open=true;}close(){this.open=false;}remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}}
const all=e=>[e,...e.children.flatMap(n=>typeof n==='object'?all(n):[])];
async function run(level,owner=false){const root=new E('main'),body=new E('body'),calls=[];const access={proprietario:owner,areas:{notas:level},rotulos:{notas:'Notas e comunicados'}};
const el=(tag,cls,text)=>{const n=new E(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n;};
const button=(text,fn)=>{const n=el('button','',text);n.onclick=fn;return n;};
const api=async(path,data)=>{calls.push(path);if(path==='rh/acesso')return access;if(path.startsWith('rh/notas'))return {itens:[],total:0,pagina:1};if(path==='rh/permissoes')return {owner_id:1,usuarios:[{id:2,nome:'Pessoa',ativo:1,role:'equipe'}],rotulos:access.rotulos,permissoes:[]};throw Error(path);};
const window={Juridico:{S:{user:{id:owner?1:2,role:level==='ver'?'leitor':'equipe'},users:[]},api,el,button,head(){},toast(){},card(){const n=new E('section');root.append(n);return n;},table(){},render(){}}};
const context={window,document:{body,getElementById:()=>root},Option:class extends E{constructor(t,v){super('option');this.textContent=t;this.value=v;}},console};vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../js/rh.js'),'utf8'),context);await window.RH.render();
if(!level){assert.equal(calls.length,1);assert.equal(all(root).filter(n=>n.tagName==='BUTTON').length,0);return;}
const create=all(root).find(n=>n.textContent==='Nova nota / colar comunicado');assert.equal(!!create,level==='editar');
assert.equal(!!all(root).find(n=>n.textContent==='Permissões do RH'),owner);
if(create){await create.onclick();const dialog=all(body).find(n=>n.tagName==='DIALOG');assert(dialog?.open);assert(all(dialog).some(n=>n.tagName==='TEXTAREA'));assert(all(dialog).some(n=>n.textContent==='Salvar registro'));}
if(owner){await all(root).find(n=>n.textContent==='Permissões do RH').onclick();assert(all(body).filter(n=>n.tagName==='DIALOG').length>=1);}
}
(async()=>{await run('');await run('ver');await run('editar');await run('editar',true);console.log('4 cenários de montagem e visibilidade do RH aprovados.');})().catch(e=>{console.error(e);process.exit(1);});
