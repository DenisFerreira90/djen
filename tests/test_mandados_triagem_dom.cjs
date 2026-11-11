const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
class Element{
 constructor(tag,css='',text=''){Object.assign(this,{tag,css,text,children:[]});}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(){}
}
const root=new Element('main'), tables=[], queries=[];
const detailTitle=new Element('h2'),detailBody=new Element('div');
const detail=Object.assign(new Element('dialog'),{showModal(){this.open=true;}});
const cnj='5001234-12.2025.8.21.0001', cpf='111.111.111-11';
const el=(...args)=>new Element(...args);
const walk=node=>[node,...node.children.filter(x=>x instanceof Element).flatMap(walk)];
const item={numero:cnj,case_id:1,classe:'Busca e Apreensão',
 partes:[{nome:'Cliente',papel:'reu',representacao:'com_advogado',advogados:[{nome:'Advogada',uf:'RS',oab:'12345'}]}],
 origem:{tribunal:'TJRS'}};
const app={
 S:{view:'mandados',user:{id:1,role:'leitor'}},el,head(){},writable:()=>false,showDetail(){},
 button(text,onclick,css){return Object.assign(el('button',css,text),{onclick});},
 card(){const section=el('section');root.append(section);return section;},
 table(headers,rows,parent){
  tables.push({headers,rows});
  parent.append(...rows.flat().filter(x=>x instanceof Element));
 },
 api:async(path,body)=>{
  if(path==='mandados')return {pendentes:0,estado:{},resumos:[],numeros:[],sem_cadastro:[],itens:[]};
  if(path==='painel-operacional')return {};
  if(path.startsWith('mandados/triagem')){
   if(!body.cpf)return {total:0,itens:[]};
   assert.equal(body.cpf,cpf);return {total:1,limite:25,itens:[item]};
  }
  throw Error(path);
 },
 day:value=>value,
 request:async(path)=>{
  queries.push(path);
  const publication={hash:'publicacao-1',processo:cnj,tribunal:'TJRS',data:'2026-11-06',texto:'Teor de exemplo'};
  return {total:3,tamanho_lote:100,itens:[publication,publication,{...publication,processo:'5005555-12.2025.8.21.0001'}]};
 }
};
const env={window:{Juridico:app},document:{getElementById:id=>({detail,detailTitle,detailBody}[id]||root)},URLSearchParams,clearTimeout(){},setTimeout(){},setInterval(){}};
vm.createContext(env);vm.runInContext(fs.readFileSync(require.resolve('../js/mandados.js'),'utf8'),env);
(async()=>{
 await env.window.Mandados.render();
 const form=walk(root).find(x=>x.tag==='form');
 form.children[0].children[0].value=cnj;
 form.children[1].children[0].value=cpf;
 form.onsubmit({preventDefault(){}});
 await new Promise(resolve=>setImmediate(resolve));
 assert(walk(root).some(x=>x.text==='Com advogado'));
 assert(walk(root).some(x=>x.text==='Advogada · OAB RS 12345'));
 assert(walk(root).some(x=>x.text===cnj));
 assert(walk(root).some(x=>x.text==='Mandados expedidos (0)'));
 assert(!walk(root).some(x=>x.text==='Publicações do DJEN'));
 await walk(root).find(x=>x.tag==='button'&&x.text==='Detalhes').onclick();
 assert(detail.open);
 assert.equal(detailTitle.textContent,cnj);
 assert.equal(queries.length,0);
 const djen=walk(detailBody).find(x=>x.tag==='details'&&x.children[0]?.text==='Publicações do DJEN');
 djen.open=true;await djen.ontoggle();
 assert.equal(queries.length,1);
 assert(queries[0].includes('numeroProcesso='+cnj.replace(/\D/g,'')));
 assert(!queries[0].includes(cpf.replace(/\D/g,'')));
 assert.equal(tables.find(x=>x.headers[0]==='Disponibilização').rows.length,1);
 console.log('Mandados, triagem por CPF e publicações DJEN sem duplicatas aprovados em DOM simulado.');
})().catch(error=>{console.error(error);process.exit(1);});
