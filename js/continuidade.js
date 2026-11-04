'use strict';
(()=>{
 const allowedTabs=['monitoramento','lista','alertas','canais'];
 window.NavigationState={
  load(id){try{const x=JSON.parse(sessionStorage.getItem('conectaadv-nav-'+id)||'{}');return typeof x==='object'&&x!==null?x:{};}catch{return {};}},
  save(id,patch){if(!id)return;try{sessionStorage.setItem('conectaadv-nav-'+id,JSON.stringify({...this.load(id),...patch}));}catch{}},
  tab(id){const t=this.load(id).tab;return allowedTabs.includes(t)?t:'monitoramento';}
 };
 let timer=null,busy=false;
 window.CollectionIndicator={start(){clearTimeout(timer);refresh();},stop(){clearTimeout(timer);}};
 async function refresh(){
  const J=window.Juridico;if(!J?.S.user||J.S.chatOnly)return;
  if(busy){timer=setTimeout(refresh,5000);return;}busy=true;
  let bar=document.getElementById('collectionContinuity');
  if(!bar){bar=J.el('div','callout');bar.id='collectionContinuity';document.getElementById('content').before(bar);}
  try{
   const data=await J.request('/api/eproc/status');if(!J.S.user)return;
   const cur=data.atual;bar.replaceChildren();bar.hidden=!cur;
   if(cur){const active=!cur.fim;
    const label=cur.estado==='aguardando'?'Coleta aguardando login, perfil ou confirmação':active?'Coleta em andamento no servidor':'Última coleta encerrada';
    bar.append(J.el('span','',label+' · '+(cur.tribunal||'')+' · '+(cur.lidos||0)+' lidos · '+(cur.salvos_sistema||0)+' gravados. '));
    if(active)bar.append(J.el('span','','Você pode trocar de área ou usar F5. Mantenha o servidor e a janela do robô abertos. '));
    bar.append(J.button('Ver coleta',()=>J.go('integracoes'),'link'));
   }
  }catch{if(J.S.user){bar.hidden=false;bar.textContent='Sem conexão para conferir a coleta. Isso não confirma cancelamento; verifique o servidor.';}}
  finally{busy=false;if(J.S.user&&!J.S.chatOnly)timer=setTimeout(refresh,5000);}
 }
})();
