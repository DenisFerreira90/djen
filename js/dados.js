'use strict';
(()=>{
let tab='planilha';
window.Dados={open:async key=>{tab=key;await window.Juridico.go('dados');},render:async()=>{
 const {S,api,head,card,el,button,toast}=window.Juridico;
 if(S.view==='planilhas')tab='planilha';
 const admin=S.user.role==='administrador';if(tab==='backup'&&!admin)tab='planilha';
 head('Central de dados','Importação, exportação e recuperação reunidas por finalidade.');
 const tabs=el('div','toolbar mandate-tabs');tabs.setAttribute('aria-label','Operações de dados');document.getElementById('content').append(tabs);
 for(const [key,title] of [['planilha','Importar planilha'],['coletas','Recuperar coleta'],['exportar','Exportar dados'],...(admin?[['backup','Backup e restauração']]:[])]){const b=button(title,()=>{tab=key;window.Juridico.render();},tab===key?'primary':'');b.setAttribute('aria-pressed',String(tab===key));tabs.append(b);}
 if(tab==='planilha'){await window.Org.render('planilhas',true);return;}
 if(tab==='exportar'){
  const c=card();c.append(el('h2','','Planilha para consulta'),el('p','','Baixe cadastros e dados relacionados em abas do Excel. Para recuperar a instalação, use Backup e restauração.'),button('Exportar Excel',()=>location.href='/api/juridico/planilha/exportar','primary'));
  if(admin){const raw=card();raw.append(el('h2','','Exportação estruturada'),el('p','','JSON com cadastros, evidências e auditoria administrativa. Não equivale ao backup integral do banco.'),button('Exportar JSON',()=>location.href='/api/juridico/exportar'));}return;
 }
 if(tab==='coletas'){
  const c=card();c.append(el('h2','','Importar uma coleta já realizada'),el('p','','Use o ZIP da coleta eproc ou processos.json para recuperar a origem guardada. Isso importa os dados disponíveis e não faz uma nova consulta ao tribunal.'));
  if(S.user.role==='leitor'){c.append(el('p','','Seu perfil permite apenas leitura.'));return;}
  const file=el('input');file.type='file';file.accept='.zip,.json';const feedback=el('p');const send=button('Importar coleta',async()=>{send.disabled=true;try{if(!file.files[0])throw Error('Selecione o arquivo.');const r=await api('importar',{arquivo_base64:await file64(file.files[0])});feedback.textContent=`${r.criados} processos novos; ${r.existentes} existentes. Confira as fichas e a cobertura dos dados.`;}catch(e){feedback.textContent=e.message;}finally{send.disabled=false;}},'primary');c.append(file,send,feedback);return;
 }
 if(tab==='backup'){
  const c=card();c.append(el('h2','','Criar cópia restaurável'),el('p','','Salva o banco com cadastros, usuários, auditoria, chat e calendários. Não inclui a sessão do navegador, arquivos externos das coletas ou credenciais de e-mail.'),button('Baixar backup restaurável',()=>location.href='/api/juridico/backup','primary'));
  const restore=card();restore.append(el('h2','','Restaurar uma cópia'),el('p','callout warn','A restauração substitui o banco atual e encerra as sessões. Uma cópia anterior é guardada pelo sistema. Antes de restaurar, baixe o backup atual.'));
  const details=el('details','ui-disclosure');details.append(el('summary','','Abrir restauração do banco'));const file=el('input'),confirmation=el('input'),feedback=el('p');file.type='file';file.accept='.zip';confirmation.placeholder='Digite RESTAURAR';
  const send=button('Restaurar backup selecionado',async()=>{send.disabled=true;try{if(!file.files[0])throw Error('Selecione o backup.');if(confirmation.value!=='RESTAURAR')throw Error('Digite RESTAURAR para confirmar.');await api('restaurar',{confirmacao:confirmation.value,arquivo_base64:await file64(file.files[0])});location.reload();}catch(e){feedback.textContent=e.message;send.disabled=false;}});details.append(el('label','','Arquivo de backup'),file,el('label','','Confirmação'),confirmation,send,feedback);restore.append(details);
 }
}};
async function file64(file){if(file.size>32*1024*1024)throw Error('Arquivo excede 32 MB.');const bytes=new Uint8Array(await file.arrayBuffer());let raw='';for(let i=0;i<bytes.length;i+=8192)raw+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(raw);}
})();
