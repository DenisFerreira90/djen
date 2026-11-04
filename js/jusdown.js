'use strict';
window.Jusdown={state:null,async render(){
 const J=window.Juridico,{S,api,head,card,el,button,table}=J,admin=S.user.role==='administrador';
 if(this.state?.user!==S.user.id)this.state={user:S.user.id,q:'',court:'',mode:'todos',activation:'ativos'};
 const state=this.state,data=await api('jusdown');if(!admin)state.activation='ativos';
 if(!data.tribunais.some(t=>t.id===state.court))state.court='';
 const degree={1:'1º grau',2:'2º grau',superior:'Superior',unificado:'1º/2º grau unificados',portal:'Página de informações'};
 const labels={verde:'Respondeu na última leitura',amarelo:'Instabilidade / primeira falha',vermelho:'Falhas consecutivas',cinza:'Sem confirmação'};
 const infoLabels={primeira_leitura:'Primeira leitura: base inicial',novidades:'Novidades detectadas',sem_novidades_detectadas:'Nenhum novo informe detectado',leitura_nao_confirmada:'Leitura dos informes não confirmada',leitura_sem_informes:'Nenhum informe público identificável',fonte_nao_configurada:'Fonte não configurada'};
 const stamp=t=>t?new Date(t).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'—';
 const link=(text,url)=>{const a=el('a','',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;};
 const dot=(color,text)=>{const n=el('span','jusdown-status');n.append(el('span','jusdown-dot '+color),el('span','',text||labels[color]));return n;};
 const showInfo=(value,full=false)=>{
  const n=el('div'),info=value||{};n.append(el('strong','',infoLabels[info.estado]||'Informações ainda não consultadas'));
  if(info.url)n.append(link('Página consultada',info.url));if(info.verificado_em)n.append(el('p','','Leitura: '+stamp(info.verificado_em)));
  const entries=info.estado==='novidades'?info.novidades:info.estado==='primeira_leitura'?info.referencias:[];
  if(entries?.length){const list=el('details','ui-disclosure');list.append(el('summary','',`${entries.length} informe(s) · ${info.estado==='primeira_leitura'?'referências iniciais, sem afirmar que são novidades':'comparados à leitura anterior'}`));for(const x of entries)list.append(link(x.titulo,x.url));n.append(list);}
  if(info.detalhe&&(full||info.estado==='leitura_nao_confirmada'))n.append(el('p','',info.detalhe));return n;
 };
 head('JUSDOWN','Meus portais · rodadas diárias às 8h e 12h30 (Brasília).');
 const intro=card(),feedback=el('p','','');intro.append(el('p','',`${data.resumo.tribunais} tribunais ativos · ${data.resumo.instancias} portais/sistemas acompanhados${admin?' · '+(data.resumo.inativos||0)+' tribunais inativos':''}.`));
 intro.append(el('p','callout','Os relatórios reúnem a resposta técnica do endereço e informes públicos encontrados na página configurada. Não consultam movimentações de processos. A primeira leitura forma a base de comparação. Falhas e páginas sem informes identificáveis ficam explícitas.'));
 intro.append(el('p','',`${data.ativo?'Rotina automática ativa':'Rotina automática pausada'} · 08:00 e 12:30 · ${data.em_andamento?'rodada em andamento':'aguardando próxima rodada'}. Mantenha o computador ligado, conectado e o servidor aberto. A consulta começa no horário; o relatório fecha após as respostas.`));
 const controls=el('div','jusdown-toolbar');intro.append(controls,feedback);controls.append(button('Atualizar painel',()=>J.render(),'link'));
 const check=async court=>{try{const r=await api('jusdown/verificar',{tribunal:court});feedback.textContent=r.iniciado?'Consulta iniciada. Ao concluir, o relatório ficará abaixo. Você pode navegar por outras áreas.':'Rodada já em andamento ou solicitação feita há menos de 1 minuto.';}catch(e){feedback.textContent=e.message;}};
 if(admin)controls.append(button('Verificar todos agora',()=>check(''),'primary'),button(data.ativo?'Pausar rotina':'Ativar rotina',async()=>{await api('jusdown/configurar',{ativo:!data.ativo});await J.render();}));if(data.erro_monitor)intro.append(el('p','callout warn',data.erro_monitor));
 const reports=card(),reportSelect=el('select'),reportBody=el('div');reports.append(el('h2','','Relatórios das rodadas'));
 for(const [i,r] of (data.rotinas||[]).entries())reportSelect.append(new Option(`${stamp(r.previsto||r.inicio)} · ${r.manual?'manual':'agendada'} · ${r.estado}`,String(i)));reportSelect.setAttribute('aria-label','Selecionar relatório');reports.append(reportSelect,reportBody);
 const reportCache=new Map();const reportDraw=async()=>{reportBody.replaceChildren();let r=(data.rotinas||[])[Number(reportSelect.value)||0];if(!r){reportBody.append(el('p','','Nenhuma rodada registrada. Use Verificar todos agora para criar uma leitura inicial.'));return;}
  try{const key=r.slot;if(!reportCache.has(key))reportCache.set(key,(await api('jusdown/relatorio?slot='+encodeURIComponent(key)))[0]||r);if((data.rotinas||[])[Number(reportSelect.value)||0]?.slot!==key)return;r=reportCache.get(key);}catch(e){reportBody.append(el('p','callout warn','Não foi possível abrir o relatório: '+e.message));return;}
  reportBody.append(el('p','',`Situação: ${r.estado} · previsto: ${stamp(r.previsto)} · início: ${stamp(r.inicio)} · encerramento: ${stamp(r.fim)}`));if(r.motivo)reportBody.append(el('p','callout warn',r.motivo));
  const rows=(r.portais||[]).filter(p=>!state.court||p.tribunal===state.court);table(['Tribunal / portal','Resultado técnico','Informações públicas'],rows.map(p=>[p.nome_portal||p.tribunal+' · '+p.sistema,dot(p.cor||'cinza'),showInfo(p.informacoes,true)]),reportBody);if(r.estado==='executando')reportBody.append(el('p','','Rodada em andamento. Atualize o painel para conferir o encerramento.'));};reportSelect.onchange=reportDraw;
 const box=card(),toolbar=el('div','jusdown-toolbar'),search=el('input'),court=el('select'),mode=el('select'),activation=el('select'),results=el('div');
 search.placeholder='Pesquisar tribunal, sistema ou portal…';search.value=state.q;search.setAttribute('aria-label','Pesquisar tribunal');court.setAttribute('aria-label','Tribunal');court.append(new Option('Todos os tribunais',''));for(const c of data.tribunais)court.append(new Option(c.id+(c.ativo===false?' (inativo)':'')+' · '+c.nome,c.id));court.value=state.court;
 for(const [v,t] of [['todos','Todos os resultados'],['problemas','Com problemas'],['verde','🟢 Respondeu'],['amarelo','🟡 Instabilidade'],['vermelho','🔴 Falhas consecutivas'],['cinza','⚪ Sem confirmação'],['novidades','Novidades detectadas']])mode.append(new Option(t,v));mode.value=state.mode;mode.setAttribute('aria-label','Situação');toolbar.append(search,court,mode);
 if(admin){for(const [v,t] of [['ativos','Tribunais ativos'],['inativos','Inativos (admin)'],['todos','Ativos e inativos']])activation.append(new Option(t,v));activation.value=state.activation;activation.setAttribute('aria-label','Ativação do tribunal');toolbar.append(activation);}
 toolbar.append(button('Limpar filtros',()=>{Object.assign(state,{q:'',court:'',mode:'todos',activation:'ativos'});J.render();},'link'));box.append(el('h2','','Portais acompanhados'),toolbar,results);
 const normalize=t=>String(t||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
 const draw=()=>{results.replaceChildren();let rows=data.itens.filter(r=>{
  if(state.activation==='ativos'&&r.ativo===false||state.activation==='inativos'&&r.ativo!==false)return false;
  if(state.court&&r.tribunal!==state.court)return false;
  if(state.q&&!normalize([r.tribunal,r.nome,r.nome_portal,r.estados,r.uf,r.sistema,r.unidade].join(' ')).includes(normalize(state.q)))return false;
  if(state.mode==='problemas')return ['amarelo','vermelho'].includes(r.cor);
  if(state.mode==='novidades')return r.informacoes?.estado==='novidades';return state.mode==='todos'||r.cor===state.mode;
 });results.append(el('p','',`${rows.length} portais exibidos. As cores correspondem à última verificação, não a monitoramento contínuo.`));
 for(const c of data.tribunais){const items=rows.filter(r=>r.tribunal===c.id);if(!items.length)continue;
  const d=el('details','jusdown-court');d.open=!!state.court||!!state.q;d.append(el('summary','',`${c.id} · ${c.nome} · ${items.length} portal(is)${c.ativo===false?' · INATIVO':''}`));
  const tools=el('div','jusdown-toolbar');if(admin)tools.append(button('Verificar só '+c.id,()=>check(c.id),'primary'),button(c.ativo===false?'Reativar tribunal':'Inativar e ocultar da equipe',async()=>{try{await api('jusdown/tribunal',{tribunal:c.id,ativo:c.ativo===false});await J.render();}catch(e){feedback.textContent=e.message;}},'link'));d.append(tools);
  table(['Portal / grau','Última verificação','Informações / novidades',''],items.map(r=>{const name=el('div');name.append(link(r.nome_portal||r.sistema,r.url),el('p','',degree[r.grau]||r.grau));const status=el('div');status.append(dot(r.cor),el('p','',stamp(r.verificado_em)),el('p','',r.desatualizado?'Leitura anterior à rodada esperada.':r.detalhe||'Aguardando primeira consulta.'));if(r.rede_incerta)status.append(el('p','callout warn','Muitas falhas simultâneas. Confira a rede local.'));for(const n of r.manutencoes||[])status.append(el('p','callout warn',n.texto));const info=showInfo(r.informacoes);const actions=el('div');if(admin){actions.append(button('Remover da lista',async()=>{try{await api('jusdown/remover-portal',{id:r.id});await J.render();}catch(e){feedback.textContent=e.message;}},'link'));}return [name,status,info,actions];}),d);results.append(d);
 }if(!rows.length)results.append(el('p','','Nenhum portal nesses filtros.'));};
 search.oninput=()=>{state.q=search.value;draw();};mode.onchange=()=>{state.mode=mode.value;draw();};activation.onchange=()=>{state.activation=activation.value;state.court='';court.value='';draw();};court.onchange=()=>{state.court=court.value;if(admin&&data.tribunais.find(c=>c.id===state.court)?.ativo===false){state.activation='inativos';activation.value='inativos';}draw();reportDraw();};
 if(admin){const setup=card(),details=el('details','ui-disclosure'),form=el('form','form-grid');details.append(el('summary','','Adicionar portal'));setup.append(details);details.append(form,el('p','','Use links públicos, sem hash ou sessão. A fonte de informações deve ser a página oficial de avisos/novidades. Remover apenas tira da lista; não apaga processos nem o histórico. Para corrigir um endereço, remova e cadastre o correto.'));
 const field=(title,node)=>{const l=el('label','',title);l.append(node);form.append(l);return node;};
 const sigla=field('Sigla do tribunal (ex.: TJAC)',el('input')),name=field('Nome do portal',el('input')),system=field('Sistema (eproc, PJe, Projudi…)',el('input')),grade=field('Grau',el('select')),url=field('URL pública do portal / sistema',el('input')),source=field('URL pública dos avisos e atualizações',el('input'));
 for(const [v,t] of Object.entries(degree))grade.append(new Option(t,v));grade.value='portal';url.type=source.type='url';for(const n of [sigla,name,system,url,source])n.required=true;
 const message=el('p','full',''),save=el('button','primary','Adicionar portal');save.type='submit';form.append(message,save);form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await api('jusdown/adicionar-portal',{tribunal:sigla.value,nome:name.value,sistema:system.value,grau:grade.value,url:url.value,url_informacoes:source.value});await J.render();}catch(err){message.textContent=err.message;}finally{save.disabled=false;}};
 }
 const alerts=card();alerts.append(el('h2','','Alertas recentes'));table(['Data / hora','Portal ou tribunal','Alerta'],data.alertas.filter(a=>!a.reconhecido&&(!state.court||a.alvo===state.court||data.itens.some(i=>i.id===a.alvo&&i.tribunal===state.court))).slice(0,40).map(a=>[stamp(a.data),a.alvo,a.texto]),alerts);
 draw();reportDraw();
}};
