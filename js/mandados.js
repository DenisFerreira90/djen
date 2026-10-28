'use strict';
const mandateUI={tab:'alertas',page:1,query:''};
window.Mandados={async render(){
 const {S,api,head,card,el,button,table,writable,showDetail}=window.Juridico;
 head('Mandados e veículos','Alertas indicativos para revisão do relacionamento e da equipe jurídica.');
 const data=await api('mandados');
 const nav=el('div','toolbar mandate-tabs');nav.setAttribute('aria-label','Áreas de mandados');document.getElementById('content').append(nav);
 const panels={};const panel=(key,title)=>{const node=card();node.hidden=mandateUI.tab!==key;panels[key]=node;const b=button(title,()=>{clearTimeout(S.timer);mandateUI.tab=key;window.Juridico.render();},mandateUI.tab===key?'primary':'');b.setAttribute('aria-pressed',String(mandateUI.tab===key));nav.append(b);return node;};
 const c=panel('alertas',`Alertas (${data.pendentes})`);
 c.append(el('p','callout warn',data.cobertura),el('p','',`${data.pendentes} pendentes · Última varredura local: ${data.estado.ultima_varredura||'aguardando'}`),el('p','','Atualização do tribunal: depende da Coleta eproc. Configurações de envio ficam em Canais de aviso; WhatsApp permanece manual. Esta tela atualiza a cada 30 segundos.'));
 const scope=panel('lista','Lista prioritária');scope.append(el('h2','','Processos acompanhados'),el('p','',data.estado.somente_lista==='1'?`Somente lista: ${data.numeros.length} processos`:'Todos os processos importados'),el('p','','Na próxima coleta eproc, os processos desta lista encontrados na listagem serão reconsultados primeiro. A coleta exige sessão válida e não é iniciada por carregar uma planilha.'));
 if(data.sem_cadastro.length)scope.append(el('p','callout warn',`${data.sem_cadastro.length} processos da lista ainda não estão cadastrados. A lista não consulta nem importa dados do tribunal.`));
 const text=el('textarea');text.placeholder='Um processo por linha. Adiciona ou apaga linhas e salva.';text.value=data.numeros.join('\n');text.rows=5;text.onfocus=()=>clearTimeout(S.timer);text.oninput=()=>clearTimeout(S.timer);
 if(writable()){
  scope.append(text,button('Salvar lista prioritária',async()=>{try{await api('mandados/lista',{numeros:text.value.split(/[\n;,]+/).map(v=>v.trim()).filter(Boolean)});window.Juridico.render();}catch(e){window.Juridico.toast(e.message);}}));
  const file=el('input');file.type='file';file.accept='.xls,.xlsx,.csv';
  file.onchange=async()=>{try{const f=file.files[0];if(!f)return;const b=new Uint8Array(await f.arrayBuffer());if(b.length>32*1024*1024)throw Error('Arquivo excede 32 MB');let raw='';for(let i=0;i<b.length;i+=8192)raw+=String.fromCharCode(...b.subarray(i,i+8192));const r=await api('mandados/lista/ler',{nome:f.name,arquivo_base64:btoa(raw)});clearTimeout(S.timer);const choices=el('div','toolbar');scope.append(el('p','','Quer focar nas atualizações desta planilha como prioridade? Escolhe como atualizar a lista e depois salva.'));
 choices.append(button('Adicionar à prioridade atual',()=>{text.value=[...new Set([...text.value.split('\n').filter(Boolean),...r.numeros])].join('\n');choices.remove();}),button('Substituir pela planilha atualizada',()=>{text.value=r.numeros.join('\n');choices.remove();}));scope.append(choices);scope.append(el('p','callout warn',`${r.numeros.length} processos únicos reconhecidos; ${r.invalidos.length} linhas precisam de correção. Confira e clique em Salvar. Status da planilha não confirma situação atual no tribunal.`));if(r.invalidos.length)scope.append(el('pre','',r.invalidos.map(x=>`${x.aba}, linha ${x.linha}: ${x.valor}`).join('\n')));}catch(e){window.Juridico.toast(e.message);}};
  scope.append(el('p','','Carregar planilha para conferir a lista:'),file,button('Voltar a acompanhar todos',async()=>{await api('mandados/lista',{numeros:[],somente_lista:false});window.Juridico.render();}));
 }
 const channels=panel('canais','Canais de aviso');
 if(S.user.role==='administrador'){
  const mail=el('section','');channels.append(mail);mail.append(el('h2','','Alertas por Gmail'));const cfg=await api('email');
  if(!cfg.disponivel)mail.append(el('p','callout warn','Configure a senha de app no Windows em que o servidor está rodando.'));
  const sender=el('input'),recipient=el('input'),secret=el('input'),auto=el('input');sender.type=recipient.type='email';sender.value=cfg.remetente;recipient.value=cfg.destinatario;secret.type='password';secret.autocomplete='new-password';secret.placeholder=cfg.configurado?'Deixe vazio para manter a senha salva':'Senha de app do Gmail (16 caracteres)';auto.type='checkbox';auto.checked=cfg.automatico;
  for(const [title,node] of [['Remetente Gmail',sender],['Destinatário',recipient],['Senha de app — nunca envie por conversa',secret],['Enviar automaticamente novos alertas após ativar',auto]]){const label=el('label','',title);label.append(node);mail.append(label);node.onfocus=()=>clearTimeout(S.timer);node.oninput=()=>clearTimeout(S.timer);}
  mail.append(el('p','','A senha fica protegida neste usuário Windows, fora dos backups do sistema. Alertas antigos não são enviados ao ativar. A coleta do tribunal continua separada.'));
  const feedback=el('p');mail.append(feedback);
  const saveButton=button('Salvar configuração',async()=>{saveButton.disabled=true;try{await api('email',{remetente:sender.value,destinatario:recipient.value,senha_app:secret.value,automatico:auto.checked});secret.value='';feedback.textContent='Configuração salva. Agora clique em Enviar teste.';}catch(e){feedback.textContent=e.message;}finally{saveButton.disabled=false;}});
  const testButton=button('Enviar teste',async()=>{testButton.disabled=true;feedback.textContent='Enviando…';try{const r=await api('email/teste',{});feedback.textContent=r.mensagem;}catch(e){feedback.textContent=e.message;}finally{testButton.disabled=false;}});
  saveButton.disabled=testButton.disabled=!cfg.disponivel;mail.append(saveButton,testButton);
  if(cfg.historico.length)table(['Data','Tipo','Resultado','Observação'],cfg.historico.map(x=>[x.criado,x.tipo,x.status,x.erro]),mail);
 }
 const wa=el('details','mandate-whatsapp');channels.append(wa);wa.append(el('summary','','WhatsApp — envio manual opcional'));wa.append(el('h2','','Teste no WhatsApp'),el('p','','Destino: +55 51 98658-3348. Este botão abre uma mensagem pronta; tu precisa confirmar o envio no WhatsApp. Não ativa envio automático.'));
 const link=el('a','primary','Abrir mensagem de teste');link.href='https://wa.me/5551986583348?text='+encodeURIComponent('TESTE — ConectaAdv: canal de alertas de mandados. Mensagem de teste, sem ocorrência judicial real.');link.target='_blank';link.rel='noopener noreferrer';wa.append(link);
 if(writable())c.append(button('Varrer eventos agora',async()=>{await api('mandados/varrer',{});window.Juridico.render();}));
 const search=el('input');search.type='search';search.placeholder='Buscar número do processo ou texto do alerta';search.value=mandateUI.query;
 const bar=el('div','toolbar');const results=el('div');const paging=el('div','toolbar');c.append(bar,results,paging);bar.append(search);
 function drawAlerts(){results.replaceChildren();paging.replaceChildren();const query=mandateUI.query.toLowerCase();const matches=data.itens.filter(r=>`${r.numero} ${r.trecho} ${r.categoria}`.toLowerCase().includes(query));const pages=Math.max(1,Math.ceil(matches.length/20));mandateUI.page=Math.min(mandateUI.page,pages);const visible=matches.slice((mandateUI.page-1)*20,mandateUI.page*20);
 results.append(el('p','',`${matches.length} alertas nesta consulta · até 20 por página. A consulta carrega os 200 alertas mais recentes.`));
 table(['Processo / evento','Indício','Trecho de origem','Revisão','WhatsApp'],visible.map(r=>[button(`${r.numero} · Evento ${r.evento}`,()=>showDetail(r.case_id),'link'),r.categoria,r.trecho,r.revisado?`Revisado por ${r.revisor}`:writable()?button('Confirmar revisão',async()=>{await api(`mandados/${r.id}/revisar`,{});window.Juridico.render();}):'Pendente',(()=>{const a=el('a','','Preparar alerta');a.target='_blank';a.rel='noopener noreferrer';a.href='https://wa.me/5551986583348?text='+encodeURIComponent(`ConectaAdv — indício para revisão\nProcesso: ${r.numero}\nEvento: ${r.evento}\nCategoria: ${r.categoria}\nConfira o documento no tribunal antes de orientar o cliente.`);return a;})()]),results);
 const prev=button('Anterior',()=>{mandateUI.page--;drawAlerts();});prev.disabled=mandateUI.page===1;
 const next=button('Próxima',()=>{mandateUI.page++;drawAlerts();});next.disabled=mandateUI.page===pages;
 paging.append(prev,el('span','',`Página ${mandateUI.page} de ${pages}`),next);
 }
 search.onfocus=()=>clearTimeout(S.timer);search.oninput=()=>{clearTimeout(S.timer);mandateUI.query=search.value;mandateUI.page=1;drawAlerts();};drawAlerts();
 if(mandateUI.tab==='alertas')S.timer=setTimeout(()=>{if(S.view==='mandados')window.Juridico.render();},30000);
}};
setInterval(async()=>{
 const J=window.Juridico;if(!J||!J.S.user)return;
 try{const d=await J.api('mandados');const b=document.querySelector('[data-view="mandados"] span');if(b)b.textContent=`Mandados e veículos${d.pendentes?' ('+d.pendentes+')':''}`;}catch(e){const b=document.querySelector('[data-view="mandados"] span');if(b)b.textContent='Mandados · falha ao atualizar';}
},30000);
