'use strict';
window.WorkspaceNav={consultas:['coletas','jusdown','conectores','integracoes','servico','avisos','dados'],apply(){
 const J=window.Juridico;if(!J?.S.user)return;const {S,el,button,go}=J;
 const names={coletas:'Coletas e processos',jusdown:'JUSDOWN',conectores:'Tribunais',integracoes:'Operação da coleta',servico:'Rotinas automáticas',avisos:'Notificações',dados:'Dados e importações',agenda:'Agenda de prazos',prazos:'Cadastro de prazos'};
 const list=this.consultas.includes(S.view)?this.consultas:['agenda','prazos'].includes(S.view)?['agenda','prazos']:[];
 const parent=this.consultas.includes(S.view)?'centralconsultas':['agenda','prazos'].includes(S.view)?'agenda':S.view;
 document.querySelectorAll('#navigation [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===parent));
 for(const group of document.querySelectorAll('#navigation details'))if(group.querySelector('[data-view="'+parent+'"]'))group.open=true;
 const old=document.getElementById('workspaceSectionTabs');if(old)old.remove();if(!list.length||S.chatOnly)return;
 const tabs=el('nav','section-tabs');tabs.id='workspaceSectionTabs';tabs.setAttribute('aria-label',parent==='centralconsultas'?'Consultas e monitoramento':'Prazos e agenda');
 for(const key of list){if(key==='servico'&&S.user.role!=='administrador')continue;const b=button(names[key],()=>go(key),key===S.view?'active':'');if(key===S.view)b.setAttribute('aria-current','page');tabs.append(b);}
 document.getElementById('content').prepend(tabs);
}};
if(window.Juridico?.S.user)window.WorkspaceNav.apply();
