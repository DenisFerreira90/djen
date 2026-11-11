
'use strict';
window.WorkspaceNav={consultas:['proprietario','coletas','jusdown','conectores','integracoes','servico','dados','diagnostico','controladoria'],apply(){
 const J=window.Juridico;if(!J?.S.user)return;const {S,el,button,go}=J;
 const names={proprietario:'Minha área',coletas:'Lista de consultas',jusdown:'Portais',conectores:'Conexões',integracoes:'Coleta',servico:'Rotinas',dados:'Dados e backup',diagnostico:'Diagnóstico',controladoria:'Recuperar fichas',agenda:'Agenda de prazos',prazos:'Cadastro de prazos'};
 const tech=J.isOwner?.()===true;
 const technical=this.consultas.includes(S.view);
 const list=technical&&tech?this.consultas:['agenda','prazos'].includes(S.view)?['agenda','prazos']:[];
 const parent=technical?'proprietario':['agenda','prazos'].includes(S.view)?'agenda':S.view;
 document.querySelectorAll('#navigation [data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===parent));
 for(const group of document.querySelectorAll('#navigation details'))if(group.querySelector('[data-view="'+parent+'"]'))group.open=true;
 const old=document.getElementById('workspaceSectionTabs');if(old)old.remove();if(!list.length||S.chatOnly)return;
 const tabs=el('nav','section-tabs');tabs.id='workspaceSectionTabs';tabs.setAttribute('aria-label',technical?'Área exclusiva do proprietário':'Prazos e agenda');
 for(const key of list){if(['servico','dados'].includes(key)&&S.user.role!=='administrador')continue;const b=button(names[key],()=>go(key),key===S.view?'active':'');if(key===S.view)b.setAttribute('aria-current','page');tabs.append(b);}
 document.getElementById('content').prepend(tabs);
}};
if(window.Juridico?.S.user)window.WorkspaceNav.apply();
