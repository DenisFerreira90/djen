'use strict';
const mandateUI={tab:'monitoramento',page:1,query:''};
function djenPublications(cnj, {S,request,el,button,table,day}) {
 const disclosure=el('details','ui-disclosure');
 const results=el('div');
 disclosure.append(el('summary','','Publicações do DJEN'),results);
 let loaded=false;
 async function load(page=1) {
  clearTimeout(S.timer);
  results.replaceChildren(el('p','','Consultando o DJEN…'));
  try{
   const digits=cnj.replace(/\D/g,'');
   const query=new URLSearchParams({numeroProcesso:digits,siglaTribunal:'TJRS',pagina:String(page)});
   const data=await request('/api/buscar?'+query);
   const seen=new Set();
   const items=data.itens.filter(item=>{
    if(String(item.processo||'').replace(/\D/g,'')!==digits||item.tribunal!=='TJRS')return false;
    const keys=[item.id?'id:'+item.id:'',item.hash?'hash:'+item.hash:''].filter(Boolean);
    if(keys.some(key=>seen.has(key)))return false;
    for(const key of keys)seen.add(key);
    return true;
   });
   results.replaceChildren(el('p','','Fonte: DJEN · disponibilizações encontradas nesta consulta.'));
   if(items.length)table(['Disponibilização','Tipo','Publicação'],items.map(item=>{
    const text=el('details');text.append(el('summary','','Ler publicação'),el('p','pre',item.texto||'Teor indisponível.'));
    return [day(item.data),item.tipo||'Não informado',text];
   }),results);
   else results.append(el('p','','Nenhuma publicação do processo retornada nesta página.'));
   const more=data.total===null?data.itens.length>=data.tamanho_lote:page*data.tamanho_lote<data.total;
   if(page>1||more){
    const bar=el('div','toolbar');
    const prev=button('Anterior',()=>load(page-1)),next=button('Próxima',()=>load(page+1));
    prev.disabled=page<=1;next.disabled=!more;bar.append(prev,el('span','','Página '+page),next);results.append(bar);
   }
  }catch(error){
   results.replaceChildren(el('p','callout warn',error.message),button('Tentar novamente',()=>load(page)));
  }
 }
 disclosure.ontoggle=()=>{
  clearTimeout(S.timer);
  if(disclosure.open&&!loaded){loaded=true;return load();}
 };
 return disclosure;
}

async function renderMandateTriage(container, {S,api,el,button,table,showDetail}) {
 const section=el('section','mandate-events');
 section.append(el('h2','','Busca e apreensão · TJRS'),
  el('p','','Veja as partes requeridas da base local. Busque pelo CNJ ou pelo CPF para conferir a representação de uma pessoa específica.'));
 const form=el('form','toolbar');
 const number=el('input');number.type='search';number.maxLength=25;number.placeholder='Número CNJ';
 const cpf=el('input');cpf.type='text';cpf.inputMode='numeric';cpf.maxLength=14;cpf.autocomplete='off';cpf.placeholder='CPF do cliente';
 for(const [label,input] of [['Processo',number],['CPF do cliente',cpf]]){
  const field=el('label','',label);field.append(input);form.append(field);
  input.onfocus=()=>clearTimeout(S.timer);
 }
 const submit=el('button','primary','Consultar');submit.type='submit';form.append(submit);
 const results=el('div','mandate-triage-results');results.setAttribute('aria-live','polite');section.append(form,results);
 container.append(section);
 const labels={com_advogado:'Com advogado',sem_advogado:'Sem advogado · analisar',a_conferir:'Representação a conferir'};
 const roles={reu:'Réu',requerido:'Requerido',executado:'Executado',demandado:'Demandado',embargado:'Embargado',autor:'Autor',requerente:'Requerente',exequente:'Exequente'};
 function partyView(party, full) {
  const row=el('div','mandate-triage-party');
  const heading=el('div','mandate-triage-name');
  heading.append(el('strong','',party.nome||'Nome a conferir'));
  if(roles[party.papel])heading.append(el('small','',roles[party.papel]));
  row.append(heading,el('span',party.representacao==='com_advogado'?'badge':'badge warn',labels[party.representacao]));
  const attorneys=full?party.advogados:party.advogados.slice(0,1);
  for(const attorney of attorneys){
   const registration=attorney.oab?['OAB',attorney.uf,attorney.oab].filter(Boolean).join(' '):attorney.registro;
   row.append(el('div','mandate-source',[attorney.nome,registration].filter(Boolean).join(' · ')));
  }
  if(!full&&party.advogados.length>1)row.append(el('small','mandate-source','+'+(party.advogados.length-1)+' em Detalhes'));
  if(full&&party.importado_em)row.append(el('small','mandate-source','Importado em '+window.Juridico.stamp(party.importado_em)));
  return row;
 }
 function openDetails(item) {
  clearTimeout(S.timer);
  const dialog=document.getElementById('detail');
  document.getElementById('detailTitle').textContent=item.numero;
  const body=document.getElementById('detailBody');
  body.replaceChildren(el('p','',item.classe),el('h3','','Partes e representação'));
  if(item.partes.length)body.append(...item.partes.map(party=>partyView(party,true)));
  else body.append(el('p','mandate-source','Parte requerida a conferir nos autos.'));
  body.append(el('h3','','Origem'));
  body.append(window.PainelOperacional?.origin?window.PainelOperacional.origin(item):el('span','',item.origem.tribunal));
  body.append(djenPublications(item.numero,window.Juridico));
  dialog.showModal();
 }
 async function load(query,page=1) {
  if(submit.disabled)return;
  submit.disabled=true;
  results.replaceChildren(el('p','','Carregando…'));
  try{
   const data=await api('mandados/triagem?pagina='+page,query);
   results.replaceChildren(el('p','',data.total?data.total+' processos na base local.':'Nenhum processo correspondente na base local.'));
   if(!data.itens.length){
    const digits=String(query.numero||'').replace(/\D/g,'');
    if(digits.length===20&&digits.slice(13,16)==='821')results.append(djenPublications(digits,window.Juridico));
    return;
   }
   table(['Processo','Classe','Cliente e representação','Origem','Detalhes'],data.itens.map(item=>{
    const client=el('div');
    if(item.partes.length)client.append(...item.partes.map(party=>partyView(party,false)));
    else client.append(el('span','badge warn','Parte requerida a conferir'));
    const source=el('div','',item.origem.tribunal);
    if(item.origem.origem_pendente)source.append(el('small','mandate-triage-origin','A conferir'));
    const details=button('Detalhes',()=>openDetails(item),'link');
    details.setAttribute('aria-label','Detalhes do processo '+item.numero);
    details.setAttribute('aria-haspopup','dialog');
    return [button(item.numero,()=>{clearTimeout(S.timer);showDetail(item.case_id);},'link'),item.classe,client,source,details];
   }),results);
   if(data.total>data.limite){
    const paging=el('div','toolbar');
    const prev=button('Anterior',()=>{clearTimeout(S.timer);load(query,page-1);});
    const next=button('Próxima',()=>{clearTimeout(S.timer);load(query,page+1);});
    prev.disabled=page<=1;next.disabled=page*data.limite>=data.total;
    paging.append(prev,el('span','','Página '+page),next);results.append(paging);
   }
  }catch(error){results.replaceChildren(el('p','callout warn',error.message));}
  finally{submit.disabled=false;}
 }
 form.onsubmit=event=>{event.preventDefault();clearTimeout(S.timer);load({numero:number.value.trim(),cpf:cpf.value.trim()});};
 await load({});
}

window.Mandados={async render(){
 const {S,api,head,card,el,button,table,writable,showDetail}=window.Juridico;
 const view=S.view;
 const titles={mandados:['Mandados e busca e apreensão','Orientação do Relacionamento, revisão da ordem e acompanhamento por processo.'],coletas:['Consultas e atualizações','Selecione os processos, consulte as fontes disponíveis e acompanhe os resultados.'],avisos:['Notificações','Revise os resumos e escolha quais enviar.']};
 head(...titles[view]);
 if(mandateUI.userId!==S.user.id){mandateUI.tab=window.NavigationState?.tab(S.user.id)||'monitoramento';mandateUI.userId=S.user.id;}
 const data=await api('mandados');
 const nav=el('div','toolbar mandate-tabs');nav.setAttribute('aria-label','Consultas e lista');if(view==='coletas')document.getElementById('content').append(nav);
 const panels={};const panel=(key,title)=>{
  const belongs=key==='alertas'?view==='mandados':key==='canais'?view==='avisos':view==='coletas';
  const node=card();node.hidden=!belongs||(['monitoramento','lista'].includes(key)&&mandateUI.tab!==key);panels[key]=node;
  if(view==='coletas'&&['monitoramento','lista'].includes(key)){
   const b=button(title,()=>{clearTimeout(S.timer);mandateUI.tab=key;window.NavigationState?.save(S.user.id,{tab:key});window.Juridico.render();},mandateUI.tab===key?'primary':'');b.setAttribute('aria-pressed',String(mandateUI.tab===key));nav.append(b);
  }return node;
 };
 if(view==='coletas'&&!['monitoramento','lista'].includes(mandateUI.tab))mandateUI.tab='monitoramento';
 const c=panel('alertas',`Alertas (${data.pendentes})`);
 if(view==='mandados'){
  await renderMandateTriage(c,window.Juridico);
  const totals=await api('painel-operacional').catch(()=>null);
  if(totals?.contagens){
   const focus=el('section','mandate-focus');focus.append(el('h2','','Prioridades do Relacionamento'),el('p','',totals.escopo+' · os prazos abaixo também entram no resumo geral.'));
   if(window.PainelOperacional?.tjrsFreshness){const freshness=el('p');window.PainelOperacional.tjrsFreshness(freshness,totals.tjrs_lista_atual);focus.append(freshness);}
   const priorityDetails=el('details','ui-disclosure'),priorityBody=el('div');priorityDetails.append(el('summary','','Detalhes das prioridades'),priorityBody);priorityDetails.ontoggle=()=>clearTimeout(S.timer);
   async function priorities(key,label,page=1){
    clearTimeout(S.timer);priorityDetails.open=true;priorityBody.replaceChildren(el('p','','Carregando…'));
    try{const report=await api('painel-operacional?indicador='+encodeURIComponent(key)+'&pagina='+page);priorityBody.replaceChildren(el('h3','',label),el('p','',report.contagens[key]+' registros · página '+page));
     table(['Processo','Vencimento','Origem e direcionamento'],(report.listas[key]||[]).map(r=>[button(r.origem?.numero||r.titulo,()=>showDetail(r.origem?.processo_id||r.id),'link'),r.vencimento||'Sem vencimento informado',window.PainelOperacional?.origin?window.PainelOperacional.origin(r):r.origem?.tribunal||'Origem pendente']),priorityBody);
     const bar=el('div','pager'),previous=button('Anterior',()=>priorities(key,label,page-1)),next=button('Próxima',()=>priorities(key,label,page+1));previous.disabled=page<=1;next.disabled=page*report.limite_lista>=report.contagens[key];bar.append(previous,el('span','',String(page)),next);priorityBody.append(bar);
    }catch(error){priorityBody.replaceChildren(el('p','callout warn',error.message));}
   }
   const stats=el('div','stats');for(const [key,label] of [['mandados_fatais_hoje','Fatalíssimo'],['mandados_fatais_vencidos','Prazos vencidos'],['mandados_fatais_7_dias','Próximos 7 dias'],['mandados_pendentes','Alertas para revisão']]){
    const item=el('div','stat');item.append(el('span','',label),el('strong','',totals.contagens[key]||0),button('Detalhes',()=>priorities(key,label),'link'));stats.append(item);
   }
   focus.append(stats,priorityDetails,button('Ver todos os prazos no painel geral',()=>window.Juridico.go('painel'),'link'),el('p','','A expedição é um sinal para revisão. Confira a ordem, os retornos e o documento na origem antes de orientar o cliente. Um indício sem vencimento não vira automaticamente prazo fatal.'));c.append(focus);
  }
 }

 c.append(el('p','callout warn',data.cobertura),el('p','',`${data.pendentes} pendentes · Última varredura local: ${data.estado.ultima_varredura||'aguardando'}`),el('p','','Atualização do tribunal: depende da Coleta eproc. Resumos e canais de envio ficam em Notificações. Esta tela atualiza a cada 30 segundos.'));
 const overview=el('section','mandate-overview');const fullHistory=el('details');fullHistory.ontoggle=()=>clearTimeout(S.timer);const issued=data.resumos.reduce((sum,item)=>sum+(item.mandados?.length||0),0);fullHistory.append(el('summary','','Mandados expedidos ('+issued+')'),overview);c.append(fullHistory);if(view==='mandados'&&window.MandateReports){const reports=el('details','mandate-reports');reports.append(el('summary','','Relatórios por período'));c.append(reports);await window.MandateReports.render(reports);}overview.append(el('h2','','Mandados por processo'));
 const date=v=>v?new Date(v).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'Data não informada';
 function documents(item,event){
  const wrap=el('div','mandate-documents');
  for(const doc of event.documentos||[]){
   const control=button(doc.nome,async()=>{
    const opened=window.open('about:blank','_blank');if(opened)opened.opener=null;
    try{const result=await api('mandados/documento',{numero:item.numero,evento:event.evento,documento:doc.nome});
     if(!opened)throw Error('Permita abrir uma nova aba para visualizar o documento.');opened.location.href=result.url;
    }catch(err){if(opened)opened.close();window.Juridico.toast(err.message);}
   },'link');control.disabled=!doc.disponivel;control.title=doc.disponivel?'Abrir no eproc; pode exigir login':'Endereço não capturado ou expirado. Consulte novamente o processo.';wrap.append(control);
  }
  if(!event.documentos?.length)wrap.append(el('span','','—'));
  if(event.documentos?.some(d=>!d.disponivel))wrap.append(el('small','','Link indisponível nesta coleta. Reconsultar para capturar.'));
  return wrap;
 }
 let expanded=false;
 for(const item of (data.resumos||[]).filter(i=>i.mandados?.length)){
  const box=el('details','mandate-case');box.open=!expanded;expanded=true;box.ontoggle=()=>clearTimeout(S.timer);
  box.append(el('summary','',item.numero+' — '+item.situacao));
  box.append(button('Abrir cadastro',()=>showDetail(item.case_id),'link'));if(item.origem&&window.PainelOperacional?.origin){const source=el('details');source.append(el('summary','','Origem e direcionamento'),window.PainelOperacional.origin(item));box.append(source);}
  const highlight=item.destaque;
  if(highlight){
   const hero=el('section','mandate-current');hero.append(el('small','','Último evento relacionado ao mandado'),el('h3','',highlight.situacao),el('p','','Evento '+highlight.atualizacao.evento+' · '+date(highlight.atualizacao.data)+' · referente à expedição do evento '+highlight.expedicao.evento));
   hero.append(el('p','',highlight.retorno_localizado?'Retorno relacionado localizado nos eventos importados. Confira a certidão.':'Retorno do cumprimento ainda não localizado na consulta.'));
   hero.append(documents(item,highlight.expedicao));box.append(hero);
  }
  box.append(el('p','mandate-source','Fonte: eproc · última importação de eventos: '+date(item.coletado_em)),el('p','','O destaque considera o evento relacionado mais recente. Não confirma a vigência da ordem nem o conteúdo do documento.'));
  for(const mandate of [...item.mandados].sort((a,b)=>Number(b.atualizacao.evento)-Number(a.atualizacao.evento))){
   const section=el('section','mandate-events');section.append(el('h3','','Eventos no eproc · expedição '+mandate.expedicao.evento),el('p','',mandate.situacao),el('p','mandate-source','Usuário no eproc: identificação exibida pelo tribunal no evento. Não indica quem fez a coleta ou acessou o ConectaAdv.'));
   table(['Evento','Data / hora','Descrição','Usuário no eproc','Documentos'],[...mandate.eventos].sort((a,b)=>Number(b.evento)-Number(a.evento)).map(event=>[event.evento,date(event.data),event.descricao,event.usuario||'Não informado',documents(item,event)]),section);
   box.append(section);
  }
  box.append(el('p','callout warn',item.cobertura));overview.append(box);
 }
 if(!(data.resumos||[]).some(i=>i.mandados?.length))overview.append(el('p','','Nenhuma expedição identificada nos eventos importados. Isso não confirma ausência de mandado; consulte e confira os processos.'));
 const scope=panel('lista','Ver / editar lista salva');scope.append(el('h2','','Processos acompanhados'),el('p','',data.estado.somente_lista==='1'?`Somente lista: ${data.numeros.length} processos`:'Todos os processos importados'),el('p','','Esta é a seleção de números, não o cadastro dos dados dos processos. Salvar altera apenas a seleção. Para buscar os dados no tribunal, use Consultar processos.'));
 if(data.sem_cadastro.length)scope.append(el('p','callout warn',`${data.sem_cadastro.length} números da lista ainda não têm cadastro local. Salvar novamente não busca os dados. Inicie a consulta no botão abaixo; falhas ficarão identificadas no resultado.`));
 scope.append(button('Ir para Consultar processos',()=>{mandateUI.tab='monitoramento';window.NavigationState?.save(S.user.id,{tab:'monitoramento'});window.Juridico.render();}));
 const text=el('textarea');text.placeholder='Um processo por linha. Adiciona ou apaga linhas e salva.';text.value=data.numeros.join('\n');text.rows=5;text.onfocus=()=>clearTimeout(S.timer);text.oninput=()=>clearTimeout(S.timer);
 if(writable()){
  scope.append(text,button('Salvar lista prioritária',async()=>{try{await api('mandados/lista',{numeros:text.value.split(/[\n;,]+/).map(v=>v.trim()).filter(Boolean)});window.Juridico.render();}catch(e){window.Juridico.toast(e.message);}}));
  const file=el('input');file.type='file';file.accept='.xls,.xlsx,.csv';
  file.onchange=async()=>{try{const f=file.files[0];if(!f)return;const b=new Uint8Array(await f.arrayBuffer());if(b.length>32*1024*1024)throw Error('Arquivo excede 32 MB');let raw='';for(let i=0;i<b.length;i+=8192)raw+=String.fromCharCode(...b.subarray(i,i+8192));const r=await api('mandados/lista/ler',{nome:f.name,arquivo_base64:btoa(raw)});clearTimeout(S.timer);if(window.BuscaLista){await window.BuscaLista.accept(r,f.name);mandateUI.tab='monitoramento';window.NavigationState?.save(S.user.id,{tab:'monitoramento'});window.Juridico.render();return;}const choices=el('div','toolbar');scope.append(el('p','','Quer focar nas atualizações desta planilha como prioridade? Escolhe como atualizar a lista e depois salva.'));
 choices.append(button('Adicionar à prioridade atual',()=>{text.value=[...new Set([...text.value.split('\n').filter(Boolean),...r.numeros])].join('\n');choices.remove();}),button('Substituir pela planilha atualizada',()=>{text.value=r.numeros.join('\n');choices.remove();}));scope.append(choices);scope.append(el('p','callout warn',`${r.numeros.length} processos únicos reconhecidos; ${r.invalidos.length} linhas precisam de correção. Confira e clique em Salvar. Status da planilha não confirma situação atual no tribunal.`));if(r.invalidos.length)scope.append(el('pre','',r.invalidos.map(x=>`${x.aba}, linha ${x.linha}: ${x.valor}`).join('\n')));}catch(e){window.Juridico.toast(e.message);}};
  scope.append(el('p','','Carregar planilha para conferir a lista:'),file,button('Voltar a acompanhar todos',async()=>{await api('mandados/lista',{numeros:[],somente_lista:false});window.Juridico.render();}));
 }
 const monitoring=panel('monitoramento','Consultar processos');if(view==='coletas'&&mandateUI.tab==='monitoramento')await window.Monitoramento.render(monitoring);
 const channels=panel('canais','Canais de aviso');if(view==='avisos'&&!window.Juridico.isOwner?.())channels.append(el('h2','','Notificações do escritório'),el('p','','Os alertas de mandados estão em Mandados e busca e apreensão; prazos e compromissos estão em Prazos e agenda.'),button('Ver alertas de mandados',()=>window.Juridico.go('mandados'),'primary'),button('Abrir prazos e agenda',()=>window.Juridico.go('agenda'),'link'));
 if(view==='avisos'&&S.user.role==='administrador'&&window.Juridico.isOwner?.()){
  const mail=el('section','');channels.append(mail);mail.append(el('h2','','Resumos de movimentações por Gmail'));const cfg=await api('email');
  if(!cfg.disponivel)mail.append(el('p','callout warn','Configure a senha de app no Windows em que o servidor está rodando.'));
  const sender=el('input'),recipient=el('input'),secret=el('input'),auto=el('input');sender.type=recipient.type='email';sender.value=cfg.remetente;recipient.value=cfg.destinatario;secret.type='password';secret.autocomplete='new-password';secret.placeholder=cfg.configurado?'Deixe vazio para manter a senha salva':'Senha de app do Gmail (16 caracteres)';auto.type='checkbox';auto.checked=cfg.mandados_automaticos===true;
  for(const [title,node] of [['Remetente Gmail',sender],['Destinatário',recipient],['Senha de app — nunca envie por conversa',secret]]){const label=el('label','',title);label.append(node);mail.append(label);node.onfocus=()=>clearTimeout(S.timer);node.oninput=()=>clearTimeout(S.timer);}
  const autoLabel=el('label');autoLabel.append(auto,el('span','','Enviar automaticamente só novidades de mandados'));mail.append(autoLabel);
  mail.append(el('p','callout','Ao ativar, os eventos já cadastrados servem de referência. Novidades de mandados são enviadas ao destinatário salvo. Os resumos gerais continuam disponíveis para envio manual.'));
  const feedback=el('p');mail.append(feedback);
  const saveButton=button('Salvar configuração',async()=>{saveButton.disabled=true;try{await api('email',{remetente:sender.value,destinatario:recipient.value,senha_app:secret.value,mandados_automaticos:auto.checked,automatico:false});secret.value='';feedback.textContent=auto.checked?'Configuração salva. Avisos automáticos de mandados ativos.':'Configuração salva. Avisos automáticos de mandados desativados.';}catch(e){feedback.textContent=e.message;}finally{saveButton.disabled=false;}});
  const testButton=button('Enviar teste',async()=>{testButton.disabled=true;feedback.textContent='Enviando…';try{const r=await api('email/teste',{});feedback.textContent=r.mensagem;}catch(e){feedback.textContent=e.message;}finally{testButton.disabled=false;}});
  saveButton.disabled=testButton.disabled=!cfg.disponivel;mail.append(saveButton,testButton);
  const review=el('section');mail.append(review);review.append(el('h2','','Revisar e enviar resumos'),el('p','','1 — Consultados: registro das consultas concluídas. 2 — Alterações: novidades para conferir no processo. 3 — Falhas: consultas ou gravações que o ConectaAdv não concluiu.'));
  const drafts=await api('email/resumos');
  if(!drafts.itens.length)review.append(el('p','','Os resumos aparecerão quando uma consulta terminar.'));
  for(const draft of drafts.itens){
   const card=el('details');card.append(el('summary','','Consulta '+draft.id.split(':').pop().slice(0,12)));review.append(card);
   const picks=[];const note=el('p');
   for(const part of draft.resumos){
    const section=el('section'),label=el('label'),check=el('input');check.type='checkbox';check.disabled=part.envio!=='nao_enviado';check.onchange=()=>clearTimeout(S.timer);label.append(check,el('span','',part.assunto+' · '+part.envio.replaceAll('_',' ')));section.append(label);
    const preview=el('details');preview.append(el('summary','','Ver conteúdo completo'),el('pre','pre',part.texto));preview.onfocus=()=>clearTimeout(S.timer);preview.ontoggle=()=>clearTimeout(S.timer);section.append(preview);card.append(section);picks.push({check,part});
   }
   card.append(el('p','','Remetente: '+cfg.remetente+' · Destinatário: '+cfg.destinatario));
   const send=button('Enviar resumos selecionados',async()=>{const selected=picks.filter(p=>p.check.checked&&!p.check.disabled).map(p=>p.part.parte);if(!selected.length){note.textContent='Selecione pelo menos um resumo.';return;}send.disabled=true;note.textContent='Enviando para '+cfg.destinatario+'…';try{const result=await api('email/resumos/enviar',{id:draft.id,partes:selected,remetente:cfg.remetente,destinatario:cfg.destinatario});note.textContent=result.resultados.map(r=>r.erro||r.mensagem).join(' ');for(const pick of picks)if(selected.includes(pick.part.parte)){pick.check.checked=false;pick.check.disabled=true;}}catch(e){note.textContent=e.message;}finally{send.disabled=false;}});
   send.disabled=!cfg.configurado||!cfg.disponivel;card.append(send,note);
  }
  if(cfg.historico.length)table(['Data','Tipo','Resultado','Observação'],cfg.historico.map(x=>[x.criado,x.tipo,x.status,x.erro]),mail);
 }
 const wa=el('details','mandate-whatsapp');channels.append(wa);wa.append(el('summary','','WhatsApp — envio manual opcional'));wa.append(el('h2','','Teste no WhatsApp'),el('p','','Destino: +55 51 98658-3348. Este botão abre uma mensagem pronta; tu precisa confirmar o envio no WhatsApp. Não ativa envio automático.'));
 const link=el('a','primary','Abrir mensagem de teste');link.href='https://wa.me/5551986583348?text='+encodeURIComponent('TESTE — ConectaAdv: canal de alertas de mandados. Mensagem de teste, sem ocorrência judicial real.');link.target='_blank';link.rel='noopener noreferrer';wa.append(link);
 if(writable())c.append(button('Varrer eventos agora',async()=>{await api('mandados/varrer',{});window.Juridico.render();}));
 const search=el('input');search.type='search';search.placeholder='Buscar número do processo ou texto do alerta';search.value=mandateUI.query;
 const bar=el('div','toolbar');const results=el('div');const paging=el('div','toolbar');const alertDetails=el('details','ui-disclosure');alertDetails.append(el('summary','','Alertas e revisão por processo'),bar,results,paging);c.append(alertDetails);bar.append(search);
 function drawAlerts(){results.replaceChildren();paging.replaceChildren();const query=mandateUI.query.toLowerCase();const matches=data.itens.filter(r=>`${r.numero} ${r.trecho} ${r.categoria}`.toLowerCase().includes(query));const pages=Math.max(1,Math.ceil(matches.length/20));mandateUI.page=Math.min(mandateUI.page,pages);const visible=matches.slice((mandateUI.page-1)*20,mandateUI.page*20);
 results.append(el('p','',`${matches.length} alertas nesta consulta · até 20 por página. A consulta carrega os 200 alertas mais recentes.`));
 table(['Processo / evento','Indício','Trecho de origem','Revisão','WhatsApp'],visible.map(r=>[button(`${r.numero} · Evento ${r.evento}`,()=>showDetail(r.case_id),'link'),r.categoria,(()=>{const box=el('details');box.append(el('summary','','Trecho e origem'),el('p','',r.trecho));if(r.origem&&window.PainelOperacional?.origin)box.append(window.PainelOperacional.origin(r));return box;})(),r.revisado?`Revisado por ${r.revisor}`:writable()?button('Confirmar revisão',async()=>{await api(`mandados/${r.id}/revisar`,{});window.Juridico.render();}):'Pendente',(()=>{const a=el('a','','Preparar alerta');a.target='_blank';a.rel='noopener noreferrer';a.href='https://wa.me/5551986583348?text='+encodeURIComponent(`ConectaAdv — indício para revisão\nProcesso: ${r.numero}\nEvento: ${r.evento}\nCategoria: ${r.categoria}\nConfira o documento no tribunal antes de orientar o cliente.`);return a;})()]),results);
 const prev=button('Anterior',()=>{mandateUI.page--;drawAlerts();});prev.disabled=mandateUI.page===1;
 const next=button('Próxima',()=>{mandateUI.page++;drawAlerts();});next.disabled=mandateUI.page===pages;
 paging.append(prev,el('span','',`Página ${mandateUI.page} de ${pages}`),next);
 }
 search.onfocus=()=>clearTimeout(S.timer);search.oninput=()=>{clearTimeout(S.timer);mandateUI.query=search.value;mandateUI.page=1;drawAlerts();};drawAlerts();
 if(view==='mandados'||(view==='coletas'&&mandateUI.tab==='monitoramento'))S.timer=setTimeout(()=>{if(S.view===view)window.Juridico.render();},30000);
}};
setInterval(async()=>{
 const J=window.Juridico;if(!J||!J.S.user)return;
 try{const d=await J.api('mandados');const b=document.querySelector('[data-view="mandados"] span');if(b)b.textContent=`Mandados e busca e apreensão${d.pendentes?' ('+d.pendentes+')':''}`;}catch(e){const b=document.querySelector('[data-view="mandados"] span');if(b)b.textContent='Mandados · falha ao atualizar';}
},30000);
