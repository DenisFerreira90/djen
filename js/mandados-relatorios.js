'use strict';
(()=>{
const state={pedido:'',inicio:null,fim:null,result:null};
window.MandateReports={async render(container){
 const J=window.Juridico,{el,button,api,table,S}=J;
 const options=await api('mandados/relatorios');
 const section=el('section','card');container.append(section);section.append(el('h2','','Buscar mandados por data de expedição'),el('p','','Selecione a consulta da lista e o período. As falhas desse pedido aparecem mesmo quando não há mandados no período. Não prevê expedições futuras.'));
 if(!options.pedidos.length){section.append(el('p','','Ainda não há pedido concluído. Vá a Consultas e atualizações, carregue sua lista e clique em Procurar.'));return;}
 const order=el('select'),start=el('input'),end=el('input'),feedback=el('p');start.type=end.type='date';
 for(const p of options.pedidos)order.append(new Option(J.stamp(p.inicio)+' · '+p.situacao+' · '+p.id.split(':').pop().slice(0,8),p.id));
 if(!options.pedidos.some(p=>p.id===state.pedido))state.pedido=options.pedidos[0].id;order.value=state.pedido;start.value=state.inicio??options.hoje;end.value=state.fim??options.hoje;
 const controls=el('div','toolbar');for(const [title,node] of [['Consulta da lista',order],['Expedição de',start],['Até',end]]){const label=el('label','',title);label.append(node);controls.append(label);node.onfocus=()=>clearTimeout(S.timer);node.onchange=()=>{clearTimeout(S.timer);feedback.textContent='Filtro alterado. Clique em Filtrar e preparar relatórios.';sendArea.replaceChildren();};}section.append(controls);
 const shortcuts=el('div','toolbar');
 function period(a,b){start.value=a;end.value=b;state.result=null;sendArea.replaceChildren();feedback.textContent='Período selecionado. Clique em Filtrar e preparar relatórios.';clearTimeout(S.timer);}
 shortcuts.append(button('Hoje',()=>period(options.hoje,options.hoje)),button('Ontem',()=>{const d=new Date(options.hoje+'T12:00:00');d.setDate(d.getDate()-1);const v=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');period(v,v);}),button('Esta semana',()=>{const d=new Date(options.hoje+'T12:00:00');d.setDate(d.getDate()-((d.getDay()+6)%7));period(d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'),options.hoje);}),button('Todo o histórico',()=>period('','')));section.append(shortcuts);
 const resultArea=el('div'),sendArea=el('div');
 const filter=button('Filtrar e preparar relatórios',async()=>{filter.disabled=true;clearTimeout(S.timer);feedback.textContent='Preparando a prévia…';resultArea.replaceChildren();sendArea.replaceChildren();state.result=null;try{
  const r=await api('mandados/relatorios',{pedido:order.value,inicio:start.value,fim:end.value});state.pedido=order.value;state.inicio=start.value;state.fim=end.value;state.result=r;await draw(r);feedback.textContent='Prévia pronta. Nenhum e-mail foi enviado.';
 }catch(err){feedback.textContent=err.message;}finally{filter.disabled=false;}},'primary');section.append(filter,feedback,resultArea,sendArea);
 async function draw(r){
  resultArea.replaceChildren();sendArea.replaceChildren();
  resultArea.append(el('h3','','Resultado do período '+(r.inicio||'inicial')+' a '+(r.fim||'final')),el('p','callout',r.previstos+' processos previstos · '+r.consultados+' consultas concluídas · '+r.falhas.length+' falhas/não consultados · '+r.mandados.length+' expedições no período.'),el('p','','Consulta encerrada em '+J.stamp(r.consulta_fim)+'. Este relatório é uma fotografia desse pedido, não uma consulta em tempo real.'));
  if(r.mandados.length)table(['Processo / cliente / contato','Expedição','Documento','Último evento do mandado'],r.mandados.map(x=>[el('pre','pre',x.numero+'\n'+x.cliente_contato),J.stamp(x.expedicao.data)+' · evento '+x.expedicao.evento,(x.expedicao.documentos||[]).join(', ')||'Não informado',x.situacao+' · evento '+x.ultimo_evento.evento+' · '+J.stamp(x.ultimo_evento.data)]),resultArea);
  else resultArea.append(el('p','','Nenhuma expedição encontrada no período nos eventos disponíveis. Confira as falhas abaixo.'));
  const issues=r.falhas.concat(r.sem_evidencia);resultArea.append(el('h3','','Falhas e pendências — não são excluídas pelo filtro de datas'));
  if(issues.length){table(['Processo / cliente','Tentativa','Motivo'],issues.map(x=>[el('pre','pre',x.numero+'\n'+x.cliente_contato),x.verificado?J.stamp(x.verificado):'Não concluída',x.motivo]),resultArea);resultArea.append(button('Copiar números com falha / pendência',async()=>{try{await navigator.clipboard.writeText([...new Set(issues.map(x=>x.numero))].join('\n'));J.toast('Números copiados.');}catch{const area=el('textarea');area.value=[...new Set(issues.map(x=>x.numero))].join('\n');resultArea.append(area);area.focus();area.select();J.toast('Selecione e copie os números com Ctrl+C.');}}));}
  else resultArea.append(el('p','','Nenhuma falha de consulta ou evidência indisponível registrada neste pedido.'));
  if(r.sem_evidencia.length)resultArea.append(el('p','callout warn',r.sem_evidencia.length+' consultas constam como concluídas, mas faltam eventos vinculados para emitir este relatório. Confira os números acima.'));
  if(r.sem_data.length)resultArea.append(el('p','callout warn','Expedições sem data, fora do filtro até conferência: '+r.sem_data.map(x=>x.numero+' · evento '+x.expedicao.evento).join('; ')));
  if(r.problemas_planilha.length)resultArea.append(el('p','callout warn',r.problemas_planilha.length+' linhas inválidas da planilha. Veja os detalhes no relatório de falhas.'));
  sendArea.append(el('h3','','Revisar e enviar desta tela'));
  const picks=[];for(const m of r.mensagens){const details=el('details');details.ontoggle=()=>clearTimeout(S.timer);details.append(el('summary','',m.parte==='mandados'?'Mandados encontrados — ver conteúdo':'Falhas e números para conferência — ver conteúdo'),el('pre','pre',m.texto));sendArea.append(details);if(S.user.role==='administrador'){const checkbox=el('input');checkbox.type='checkbox';checkbox.disabled=!!r.envios[m.parte];checkbox.onchange=()=>clearTimeout(S.timer);const label=el('label','',m.parte==='mandados'?'Enviar mandados encontrados':'Enviar falhas');label.append(checkbox,el('small','',r.envios[m.parte]?' · tentativa já registrada: '+r.envios[m.parte]:' · ainda não enviado'));sendArea.append(label);picks.push({checkbox,m});}}
  if(S.user.role!=='administrador'){sendArea.append(el('p','','Somente administradores podem enviar estes relatórios por e-mail.'));return;}
  const cfg=await api('email');sendArea.append(el('p','','De: '+cfg.remetente+' · Para: '+cfg.destinatario));
  const send=button('Enviar relatórios selecionados',async()=>{const parts=picks.filter(x=>x.checkbox.checked&&!x.checkbox.disabled).map(x=>x.m.parte);if(!parts.length){J.toast('Selecione mandados, falhas ou ambos.');return;}send.disabled=true;try{const result=await api('mandados/relatorios/enviar',{id:r.id,partes:parts,remetente:cfg.remetente,destinatario:cfg.destinatario});J.toast(result.resultados.map(x=>x.erro||x.mensagem).join(' '));for(const x of picks)if(parts.includes(x.m.parte)){x.checkbox.disabled=true;x.checkbox.checked=false;}}catch(err){J.toast(err.message);}finally{send.disabled=false;}});send.disabled=!cfg.configurado||!cfg.disponivel;sendArea.append(send);
 }
 if(state.result)await draw(state.result);
}};
})();
