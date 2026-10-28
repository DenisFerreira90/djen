'use strict';
(()=>{
const C={id:null,date:new Date().toLocaleDateString('sv-SE',{timeZone:'America/Sao_Paulo'})};
const local=v=>new Date(v).toLocaleString('sv-SE',{timeZone:'America/Sao_Paulo'}).slice(0,16).replace(' ','T');
window.Calendario={async render(){
 const {S,api,el,head,card,button,toast}=window.Juridico;
 head('Calendários da equipe','Agendamentos delegados entre pessoas e setores · horário de Brasília.');
 const calendars=await api('calendarios'),people=await api('chat/usuarios');
 if(!calendars.some(c=>c.id===C.id))C.id=calendars.find(c=>c.owner_id===S.user.id)?.id||calendars[0]?.id;
 const chosen=calendars.find(c=>c.id===C.id),top=card(),bar=el('div','toolbar'),select=el('select'),date=el('input');
 for(const c of calendars)select.append(new Option(c.nome+' · '+c.permissao,c.id));select.value=C.id||'';select.onchange=()=>{C.id=Number(select.value);window.Juridico.render();};date.type='date';date.value=C.date;date.onchange=()=>{if(date.value){C.date=date.value;window.Juridico.render();}};
 bar.append(select,date,button('Hoje',()=>{C.date=new Date().toLocaleDateString('sv-SE',{timeZone:'America/Sao_Paulo'});window.Juridico.render();}));top.append(bar);
 if(S.user.role==='administrador')bar.append(button('Criar calendário de setor',async()=>{const name=prompt('Nome do calendário, por exemplo Contratação:');if(!name)return;const r=await api('calendarios',{nome:name});C.id=r.id;window.Juridico.render();}));
 if(!chosen){top.append(el('p','','Nenhuma agenda disponível.'));return;}
 if(chosen.permissao==='gerenciar')bar.append(button('Delegar acesso a pessoas / setores',permissions));
 if(chosen.permissao!=='ver')bar.append(button('Marcar atendimento',()=>edit(), 'primary'));
 top.append(el('p','','Conceda “agendar” ao setor que marca os atendimentos e “ver” a quem acompanha. Quem tem acesso ao calendário vê os compromissos dele. Use agendas separadas para dados restritos de RH.'));
 const start=new Date(C.date+'T00:00:00-03:00'),end=new Date(start.getTime()+7*86400000),data=await api(`calendarios/${C.id}/eventos?de=${encodeURIComponent(start.toISOString())}&ate=${encodeURIComponent(end.toISOString())}`);
 const grid=el('div','calendar-week');document.getElementById('content').append(grid);
 for(let i=0;i<7;i++){const day=new Date(start.getTime()+i*86400000),key=day.toLocaleDateString('sv-SE',{timeZone:'America/Sao_Paulo'}),column=el('section','calendar-day');column.append(el('h2','',day.toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo',weekday:'short',day:'2-digit',month:'2-digit'})));
  const rows=data.itens.filter(e=>local(e.inicio).slice(0,10)<=key&&local(e.fim).slice(0,10)>=key);
  if(!rows.length)column.append(el('p','','Sem compromissos'));
  for(const e of rows){const item=button(`${local(e.inicio).slice(11)}–${local(e.fim).slice(11)} · ${e.titulo}\n${e.responsavel}\n${e.cliente||''}\n${e.status}`,()=>edit(e),'calendar-event'+(e.status==='cancelado'?' cancelled':''));column.append(item);}grid.append(column);
 }
 if(data.limite_atingido)top.append(el('p','callout warn','Mais de mil compromissos no intervalo. Reduza o período da consulta.'));
 async function edit(existing){const dialog=el('dialog','calendar-dialog'),form=el('form','form-grid'),fields={};dialog.append(el('h2','',existing?'Compromisso':'Novo atendimento'),form);const definitions=[['titulo','Título','text'],['inicio','Início','datetime-local'],['fim','Fim','datetime-local'],['responsavel_id','Responsável','select'],['cliente','Cliente','text'],['contato','Contato do cliente','text'],['processo','Processo (opcional)','text'],['local','Local / link da reunião','text'],['observacoes','Observações','textarea'],['status','Situação','status']];
 for(const [key,label,type] of definitions){const l=el('label','',label);let input=el(type==='textarea'?'textarea':type==='select'||type==='status'?'select':'input');if(input.tagName==='INPUT')input.type=type;
 if(type==='select')for(const u of people)input.append(new Option(u.nome,u.id));if(type==='status')for(const state of ['marcado','confirmado','realizado','cancelado'])input.append(new Option(state,state));
 if(existing)input.value=['inicio','fim'].includes(key)?local(existing[key]):existing[key]||'';else if(key==='inicio')input.value=C.date+'T09:00';else if(key==='fim')input.value=C.date+'T10:00';else if(key==='responsavel_id')input.value=chosen.owner_id||S.user.id;
 input.disabled=chosen.permissao==='ver';if(['titulo','inicio','fim','responsavel_id'].includes(key))input.required=true;l.append(input);form.append(l);fields[key]=input;}
 const feedback=el('p','full');form.append(feedback);const close=button('Fechar',()=>{dialog.close();dialog.remove();});form.append(close);
 if(chosen.permissao!=='ver'){const save=el('button','primary','Salvar compromisso');save.type='submit';form.append(save);form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{const body=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.value]));body.inicio+=':00-03:00';body.fim+=':00-03:00';body.responsavel_id=Number(body.responsavel_id);if(existing)body.versao=existing.versao;await api(`calendarios/${C.id}/eventos${existing?'/'+existing.id:''}`,body);dialog.close();dialog.remove();window.Juridico.render();}catch(e){feedback.textContent=e.message;save.disabled=false;}};}
 document.body.append(dialog);dialog.showModal();}
 async function permissions(){const data=await api(`calendarios/${C.id}/permissoes`),dialog=el('dialog','calendar-dialog'),rows=el('div','calendar-grants'),inputs=[];dialog.append(el('h2','','Quem pode usar esta agenda?'),el('p','','Ver permite consultar; agendar permite criar e alterar compromissos; gerenciar permite também delegar acesso. A permissão do setor acompanha os integrantes do grupo.'),rows);
 const principals=[...people.map(u=>({tipo:'usuario',id:u.id,nome:u.nome})),...data.setores.map(g=>({tipo:'setor',id:g.id,nome:'Setor: '+g.titulo}))];
 for(const p of principals){const label=el('label','',p.nome),select=el('select');for(const [v,t] of [['','Sem acesso'],['ver','Ver'],['agendar','Agendar'],['gerenciar','Gerenciar']])select.append(new Option(t,v));select.value=data.permissoes.find(g=>g.tipo===p.tipo&&g.principal_id===p.id)?.papel||'';label.append(select);rows.append(label);inputs.push({p,select});}
 dialog.append(button('Cancelar',()=>{dialog.close();dialog.remove();}),button('Salvar delegações',async()=>{await api(`calendarios/${C.id}/permissoes`,{permissoes:inputs.filter(x=>x.select.value).map(x=>({tipo:x.p.tipo,principal_id:x.p.id,papel:x.select.value}))});dialog.close();dialog.remove();toast('Delegações salvas.');window.Juridico.render();},'primary'));document.body.append(dialog);dialog.showModal();}
}};
})();
