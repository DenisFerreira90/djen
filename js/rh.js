'use strict';
(()=>{
const R={area:null,pagina:1,q:'',dia:new Date().toLocaleDateString('sv-SE',{timeZone:'America/Sao_Paulo'}),periodo:'semana'};
const date=v=>v?new Date(v).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'Sem data';
const local=v=>v?v.slice(0,16):'';
const dayAfter=(day,n)=>new Date(new Date(day+'T12:00:00-03:00').getTime()+n*86400000).toLocaleDateString('sv-SE',{timeZone:'America/Sao_Paulo'});
window.RH={async render(){
 const {S,api,el,head,card,button,table,toast}=window.Juridico;
 head('Recursos humanos','Área restrita · registros, demandas e cronograma · horário de Brasília');
 const access=await api('rh/acesso');S.rh=access;
 const allowed=Object.keys(access.areas).filter(k=>access.areas[k]);
 if(!allowed.length){card().append(el('p','callout warn','Seu usuário não tem acesso ao RH. Solicite autorização ao proprietário.'));return;}
 if(!allowed.includes(R.area))R.area=allowed[0];
 const top=card(),tabs=el('div','toolbar');top.append(tabs);
 for(const area of allowed)tabs.append(button(access.rotulos[area],()=>{R.area=area;R.pagina=1;R.q='';window.Juridico.render();},R.area===area?'primary':''));
 top.append(el('p','','Cada área tem autorização própria. Os registros do RH não aparecem nos processos, no financeiro ou nas agendas gerais.'));
 if(access.proprietario){const tools=el('div','toolbar');tools.append(button('Permissões do RH',permissions),button('Auditoria do RH',audit));const a=el('a','','Baixar backup exclusivo do RH');a.href='/api/juridico/rh/backup';tools.append(a);top.append(tools);}
 const bar=el('div','toolbar'),input=el('input');input.placeholder='Buscar nesta área';input.value=R.q;input.setAttribute('aria-label','Buscar registros de RH');bar.append(input,button('Buscar',()=>{R.q=input.value;R.pagina=1;window.Juridico.render();}));input.onkeydown=e=>{if(e.key==='Enter'){R.q=input.value;R.pagina=1;window.Juridico.render();}};
 if(access.areas[R.area]==='editar'&&S.user.role!=='leitor')bar.append(button(R.area==='notas'?'Nova nota / colar comunicado':'Novo registro',()=>edit(), 'primary'));
 top.append(el('h2','',access.rotulos[R.area]),bar);
 let query='?pagina='+R.pagina+'&q='+encodeURIComponent(R.q);
 if(R.area==='agenda'){
  const controls=el('div','toolbar'),day=el('input'),period=el('select');day.type='date';day.value=R.dia;day.setAttribute('aria-label','Data do cronograma');period.append(new Option('Diário','dia'),new Option('Semanal','semana'));period.value=R.periodo;
  day.onchange=()=>{if(day.value){R.dia=day.value;R.pagina=1;window.Juridico.render();}};period.onchange=()=>{R.periodo=period.value;R.pagina=1;window.Juridico.render();};controls.append(day,period);top.append(controls);
  query+='&de='+R.dia+'&ate='+dayAfter(R.dia,R.periodo==='semana'?6:0);
 }
 const data=await api('rh/'+R.area+query),list=card();
 list.append(el('p','',data.total+' registro(s) · página '+R.pagina));
 if(!data.itens.length)list.append(el('p','','Nenhum registro neste filtro.'));
 if(R.area==='agenda'){
  const grid=el('div',R.periodo==='semana'?'rh-week':'rh-day');list.append(grid);
  for(let i=0;i<(R.periodo==='semana'?7:1);i++){
   const key=dayAfter(R.dia,i),column=el('section','rh-day');column.append(el('h3','',new Date(key+'T12:00:00-03:00').toLocaleDateString('pt-BR',{weekday:'short',day:'2-digit',month:'2-digit',timeZone:'America/Sao_Paulo'})));
   for(const item of data.itens.filter(r=>r.dados.inicio?.slice(0,10)<=key&&(r.dados.fim||r.dados.inicio)?.slice(0,10)>=key))column.append(button((item.dados.inicio?.slice(11,16)||'')+' · '+item.dados.titulo+'\n'+(item.dados.pessoa||'')+'\n'+item.dados.status,()=>edit(item),'rh-event'));
   grid.append(column);
  }
 }else if(data.itens.length)table(['Título / pessoa','Situação','Data / período','Responsável',''],data.itens.map(r=>[r.dados.titulo+(r.dados.pessoa?' · '+r.dados.pessoa:''),r.dados.status||'aberto',date(r.dados.inicio)+(r.dados.fim?' até '+date(r.dados.fim):''),S.users.find(u=>u.id===r.dados.responsavel_id)?.nome||'Sem responsável',button('Abrir',()=>edit(r),'link')]),list);
 const pager=el('div','toolbar');if(R.pagina>1)pager.append(button('Anterior',()=>{R.pagina--;window.Juridico.render();}));if(R.pagina*50<data.total)pager.append(button('Próxima',()=>{R.pagina++;window.Juridico.render();}));list.append(pager);
 if(R.area==='agenda')list.append(el('small','','São exibidos até 50 compromissos por página. O cronograma usa registros datados; repetições precisam ser cadastradas. Não há lembrete automático nem sincronização com Google Agenda.'));
 if(R.area==='notas')list.append(el('p','','Cole aqui comunicados do Geral ou notas da rotina. A cópia fica restrita aos autorizados nesta área e permanece mesmo que a mensagem original deixe de estar disponível. Não envie de volta ao Geral informações confidenciais do RH.'));
 if(R.area==='desligamentos')list.append(el('p','','Controle interno de etapas e conferências. Não calcula verbas rescisórias nem transmite informações ao eSocial.'));
 async function edit(existing){
  const editable=access.areas[R.area]==='editar'&&S.user.role!=='leitor',dialog=el('dialog','rh-dialog'),form=el('form','form-grid'),fields={};dialog.append(el('h2','',(existing?'Registro: ':'Novo: ')+access.rotulos[R.area]),form);
  const defs=[['titulo','Título / nome do registro','text'],['pessoa',R.area==='entrevistas'?'Candidato':'Pessoa / colaborador','text'],['tipo','Tipo (ex.: férias, ausência, admissão, reunião)','text'],['setor','Setor','text'],['unidade','Unidade','unit'],['responsavel_id','Responsável pelo acompanhamento','person'],['inicio','Início / data e hora','datetime-local'],['fim','Fim (opcional)','datetime-local'],['status','Situação','state'],['prioridade','Prioridade','priority'],['observacoes',R.area==='notas'?'Mensagem / conteúdo da nota':'Observações / checklist (uma etapa por linha)','textarea']];
  for(const [key,label,type]of defs){const wrap=el('label',type==='textarea'?'full':'',label),node=el(['unit','person','state','priority'].includes(type)?'select':type==='textarea'?'textarea':'input');if(node.tagName==='INPUT')node.type=type;
   if(type==='unit')for(const v of ['','Principal · 805','Casa 2 · 787'])node.append(new Option(v||'Não informado',v));
   if(type==='person'){node.append(new Option('Sem responsável',''));for(const u of S.users.filter(u=>u.ativo!==0))node.append(new Option(u.nome,u.id));}
   if(type==='state')for(const v of ['aberto','em_andamento','concluido','cancelado','ativo','inativo','agendado','realizado','justificada','nao_justificada','em_analise'])node.append(new Option(v.replaceAll('_',' '),v));
   if(type==='priority')for(const v of ['normal','baixa','alta','urgente'])node.append(new Option(v,v));
   node.value=existing?(type==='datetime-local'?local(existing.dados[key]):existing.dados[key]??''):key==='prioridade'?'normal':key==='status'?'aberto':'';
   if(key==='titulo'){node.required=true;node.maxLength=240;}if(type==='textarea'){node.rows=8;node.maxLength=12000;}node.disabled=!editable;wrap.append(node);form.append(wrap);fields[key]=node;
  }
  if(R.area==='agenda')fields.inicio.required=true;
  const feedback=el('p','full');form.append(feedback);const close=button('Fechar',()=>{dialog.close();dialog.remove();});close.type='button';form.append(close);
  if(editable){const save=el('button','primary','Salvar registro');save.type='submit';form.append(save);form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const dados=Object.fromEntries(Object.entries(fields).map(([k,n])=>[k,k==='responsavel_id'?(n.value?Number(n.value):null):['inicio','fim'].includes(k)&&n.value?n.value+':00-03:00':n.value]));await api('rh/'+R.area+(existing?'/'+existing.id:''),{dados,...(existing?{versao:existing.versao}:{})});dialog.close();dialog.remove();toast('Registro do RH salvo.');window.Juridico.render();}catch(err){feedback.textContent=err.message;save.disabled=false;}};}
  dialog.addEventListener('close',()=>dialog.remove(),{once:true});document.body.append(dialog);dialog.showModal();
 }
 async function permissions(){
  const data=await api('rh/permissoes'),dialog=el('dialog','rh-dialog');dialog.append(el('h2','','Permissões por área do RH'),el('p','','Somente o proprietário altera acessos. Administrador do sistema não recebe acesso ao RH automaticamente.'));
  const who=el('select');for(const u of data.usuarios.filter(u=>u.ativo&&u.id!==data.owner_id))who.append(new Option(u.nome+' · '+u.role,u.id));dialog.append(who);const matrix=el('div','form-grid');dialog.append(matrix);const fields={};
  function draw(){matrix.replaceChildren();const user=data.usuarios.find(u=>u.id===Number(who.value));for(const [key,title]of Object.entries(data.rotulos)){const label=el('label','',title),node=el('select');node.append(new Option('Sem acesso',''),new Option('Leitura','ver'));if(user?.role!=='leitor')node.append(new Option('Leitura e edição','editar'));node.value=data.permissoes.find(g=>g.user_id===Number(who.value)&&g.scope===key)?.level||'';label.append(node);matrix.append(label);fields[key]=node;}}
  who.onchange=draw;draw();const feedback=el('p');dialog.append(feedback,button('Salvar permissões',async()=>{try{await api('rh/permissoes',{usuario_id:Number(who.value),areas:Object.fromEntries(Object.entries(fields).map(([k,n])=>[k,n.value]))});dialog.close();dialog.remove();toast('Permissões atualizadas.');}catch(err){feedback.textContent=err.message;}},'primary'),button('Fechar',()=>{dialog.close();dialog.remove();}));document.body.append(dialog);dialog.showModal();
 }
 async function audit(){const data=await api('rh/auditoria'),dialog=el('dialog','rh-dialog');dialog.append(el('h2','','Últimos 200 eventos do RH'));for(const row of data){const details=el('details');details.append(el('summary','',date(row.created)+' · '+row.actor_name+' · '+row.action),el('pre','pre',JSON.stringify({antes:row.before?JSON.parse(row.before):null,depois:row.after?JSON.parse(row.after):null},null,2)));dialog.append(details);}dialog.append(button('Fechar',()=>{dialog.close();dialog.remove();}));document.body.append(dialog);dialog.showModal();}
}};
})();
