'use strict';
(() => {
 function originView(r){
  const {el,button,showDetail,toast}=window.Juridico,o=r.origem||{},wrap=el('div','origin-details');
  const values=[['Processo',o.numero||'Não informado'],['Tribunal',o.tribunal||'Não informado'],['Sistema',o.sistema||'Não informado'],['Grau',o.grau||'Não informado'],['Comarca',o.comarca||'Não informada'],['Vara / órgão',o.orgao||'Não informado'],['Referência',o.fonte||'Não informada']];
  const list=el('dl','origin-facts');for(const [name,value] of values)list.append(el('dt','',name),el('dd','',value));wrap.append(list);
  if(o.origem_pendente)wrap.append(el('p','callout warn','Origem incompleta: '+(o.campos_pendentes||[]).join(', ')+'.'));
  const actions=el('div','toolbar');
  if(o.processo_id)actions.append(button('Abrir cadastro do processo',()=>showDetail(o.processo_id),'link'));
  if(o.numero)actions.append(button('Copiar número CNJ',async()=>{try{await navigator.clipboard.writeText(o.numero);toast?.('Número copiado.');}catch{toast?.('Número do processo: '+o.numero);}},'link'));
  if(o.url&&/^https:\/\//i.test(o.url)){
   const link=el('a','primary',o.tipo_link==='origem'?'Abrir origem':'Abrir portal correspondente');link.href=o.url;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);
  }else actions.append(el('span','muted','Link da origem ainda não identificado'));
  wrap.append(actions,el('small','',o.aviso_link||'Confira os dados na fonte oficial.'));return wrap;
 }
 function tjrsFreshness(node,snapshot,failed=false){
  const stamp=snapshot?.capturado&&new Date(snapshot.capturado).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'});
  node.className=failed||snapshot?.atrasada?'callout warn':'muted';
  node.textContent=stamp?'Última lista conferida do TJRS em '+stamp+
    (failed?' · Sem conexão para verificar a atualização.':snapshot.atrasada?' · Atualização pendente.':'') :
    failed?'Sem conexão para verificar a lista do TJRS.':'TJRS · Aguardando a primeira lista conferida da extensão.';
 }
 window.PainelOperacional={origin:originView,tjrsFreshness,async render(){
  const {S,api,head,card,el,button,table,showDetail,userName,day}=window.Juridico;
  head('Visão geral','Totais do escritório. Abra Detalhes para localizar cada processo e sua origem.');
  const d=await api('painel-operacional'),intro=card();intro.append(el('p','',d.escopo+' · '+day(d.data)));
  const freshness=el('p');tjrsFreshness(freshness,d.tjrs_lista_atual);intro.append(freshness);
  const shortcuts=el('div','toolbar');for(const [label,view] of [['Processos','processos'],['Prazos e agenda','agenda'],['Mandados e busca e apreensão','mandados']])shortcuts.append(button(label,()=>window.Juridico.go(view),'link'));intro.append(shortcuts);
  const note=el('details','dashboard-note');note.append(el('summary','','Como interpretar os indicadores'),el('p','','Fatalíssimo reúne os vencimentos registrados para hoje. Os próximos 7 dias incluem hoje e amanhã: não some os grupos. Datas não são recalculadas. Origens incompletas e prazos sem conferência precisam de revisão. Os números refletem os dados disponíveis, sem comprovar cobertura integral do tribunal.'));intro.append(note);
  const labels={fatais_vencidos:'Fatais vencidos',fatais_hoje:'Fatalíssimo',fatais_amanha:'Fatais de amanhã',fatais_7_dias:'Fatais em 7 dias',prazos_sem_conferencia:'Prazos sem conferência',tarefas_urgentes:'Tarefas urgentes',tarefas_atrasadas:'Tarefas atrasadas',documentos_em_revisao:'Documentos em revisão',processos_sem_responsavel:'Processos sem responsável',processos_sem_checagem:'Sem registro de checagem',processos_desatualizados:'Sem checagem hoje',prazos_sem_data:'Prazos sem data',mandados_pendentes:'Mandados para revisão',mandados_fatais_hoje:'Fatalíssimo · mandados',mandados_fatais_vencidos:'Vencidos · mandados',mandados_fatais_7_dias:'Próximos 7 dias · mandados',falhas_consulta:'Falhas de consulta',financeiro_vencido:'Financeiro vencido'};
  const groups=[['Prazos e conferência',['fatais_vencidos','fatais_hoje','fatais_amanha','fatais_7_dias','prazos_sem_conferencia','prazos_sem_data']],['Mandados e busca e apreensão',['mandados_pendentes','mandados_fatais_hoje','mandados_fatais_vencidos','mandados_fatais_7_dias']],['Trabalho e urgências',['tarefas_urgentes','tarefas_atrasadas','documentos_em_revisao']],['Qualidade dos cadastros e consultas',['processos_sem_responsavel','processos_sem_checagem','processos_desatualizados','falhas_consulta']],['Financeiro',['financeiro_vencido']]];
  if(!window.Juridico.isOwner?.())groups[3][1]=['processos_sem_responsavel'];
  const grids={};for(const [title,keys] of groups){const available=keys.filter(k=>k in d.contagens);if(!available.length)continue;const section=el('details','dashboard-group');section.open=title==='Prazos e conferência';section.append(el('summary','',title));const grid=el('div','stats');section.append(grid);document.getElementById('content').append(section);for(const key of available)grids[key]=grid;}
  const details=el('details','card dashboard-records'),summary=el('summary','','Detalhes dos indicadores');details.append(summary);const body=el('div');details.append(body);document.getElementById('content').append(details);
  let requestId=0,selected=null;
  async function show(key,page=1,quiet=false){
   const version=++requestId;
   if(!quiet){
    selected={key,page};details.open=true;summary.textContent='Detalhes · '+labels[key];
    body.replaceChildren(el('p','','Carregando registros…'));
   }
   try{
    const result=await api('painel-operacional?indicador='+encodeURIComponent(key)+'&pagina='+page);if(version!==requestId)return;
    body.replaceChildren();const total=result.contagens[key],pending=result.origens_pendentes?.[key]||0;
    body.append(el('p','',`${total} registros · ${pending} com origem incompleta · página ${page}.`));
    if(key.startsWith('mandados_'))body.append(el('p','','Os prazos de mandados também estão nos totais gerais. Indícios sem prazo não são transformados automaticamente em Fatalíssimo.'));
    if(!(result.listas[key]||[]).length)body.append(el('p','','Nenhum registro neste indicador.'));
    else table(['Processo / registro','Vencimento','Responsável','Detalhes'],result.listas[key].map(r=>{
     const process=el('div');process.append(button(r.origem?.numero||r.titulo,()=>showDetail(r.origem?.processo_id||r.id),'link'));if(r.prazo_titulo)process.append(el('small','',r.prazo_titulo));
     const extra=el('details','origin-disclosure');extra.append(el('summary','','Origem e direcionamento'),originView(r));return[process,day(r.vencimento),userName(r.responsavel_id),extra];
    }),body);
    const bar=el('div','pager'),previous=button('Anterior',()=>show(key,page-1)),next=button('Próxima',()=>show(key,page+1));previous.disabled=page<=1;next.disabled=page*result.limite_lista>=total;bar.append(previous,el('span','',`${total} registros · página ${page}`),next);body.append(bar);
   }catch(error){if(!quiet&&version===requestId)body.replaceChildren(el('p','callout warn',error.message));}
   if(!quiet)details.scrollIntoView?.({block:'nearest',behavior:'smooth'});
  }
  const counters={};
  for(const [key,value] of Object.entries(d.contagens)){if(!grids[key])continue;const item=el('div','stat'),count=el('strong','',value);counters[key]=count;item.append(el('span','',labels[key]),count,button('Detalhes',()=>show(key),'link'));grids[key].append(item);}
  let snapshot=d.tjrs_lista_atual,dayText=intro.querySelector('p');
  async function refresh(){
   if(!intro.isConnected||S.view!=='painel')return;
   try{
    const update=await api('painel-operacional');
    if(!intro.isConnected)return;
    const changed=snapshot?.capturado!==update.tjrs_lista_atual?.capturado;
    snapshot=update.tjrs_lista_atual;
    tjrsFreshness(freshness,snapshot);dayText.textContent=update.escopo+' · '+day(update.data);
    for(const [key,count] of Object.entries(counters))count.textContent=update.contagens[key];
    if(changed&&details.open&&selected&&!body.contains(document.activeElement)){
     const page=Math.min(selected.page,Math.max(1,Math.ceil(update.contagens[selected.key]/update.limite_lista)));
     await show(selected.key,page,true);
    }
   }catch{tjrsFreshness(freshness,snapshot,true);}
   if(intro.isConnected&&S.view==='painel')S.timer=setTimeout(refresh,30000);
  }
  S.timer=setTimeout(refresh,30000);
  const messages=await api('chat/conversas').catch(()=>null),unread=messages?messages.reduce((n,c)=>n+(c.nao_lidas||0),0):null,communication=card();communication.append(el('h2','',unread===null?'Comunicação interna':`Comunicação · ${unread} mensagens não lidas`),button('Abrir chat interno',()=>window.Juridico.go('chat'),'primary'));
 }};
})();
