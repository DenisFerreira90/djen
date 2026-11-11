'use strict';
window.Diagnostico={async render(){
 const J=window.Juridico,{S,el,api,button,head,card,table,stamp}=J;
 const access=await api('saude-sistema/acesso');if(!access.permitido)throw Error('Acesso técnico não autorizado.');
 head('Saúde do sistema','Falhas técnicas, armazenamento e acompanhamento de correções. A leitura dos bancos não comprova que os tribunais ou servidores externos estejam disponíveis.');
 const health=await api('saude-sistema/saude'),top=card();top.append(el('strong','','Versão '+health.versao+' · Verificado em '+stamp(health.checado_em)),el('p','','Espaço livre: '+(health.disco_livre_bytes/1024**3).toFixed(1)+' GB'),button('Atualizar painel',()=>this.renderFresh()));
 table(['Componente','Verificação local','Observação'],health.servicos.map(s=>[s.servico,s.estado.replaceAll('_',' '),s.observacao||'Verificado em '+stamp(s.checado_em)]),top);
 for(const v of health.versoes_observadas||[])top.append(el('small','','Versão observada: '+v.version+' · '+v.service+' · '+stamp(v.first_seen)));
 const backups=health.backups_confirmados_nesta_versao;top.append(el('h3','','Backups gerados pelo sistema nesta versão'));
 for(const b of backups)top.append(el('p','',b.service+' · '+stamp(b.at)));
 if(!backups.length)top.append(el('p','','Sem geração registrada nesta versão. Isso não significa que não existam backups externos.'));
 top.append(el('small','','A geração registrada não comprova download, cópia externa ou restauração testada.'));
 const c=card();c.append(el('h2','','Erros e relatórios'));
 const filters=el('div','diagnostic-filters'),fields={};
 for(const [key,title,type]of [['busca','Código ERR ou tipo da exceção','search'],['modulo','Módulo (juridico, chat, coletor, jusdown…)','text'],['inicio','De','date'],['fim','Até','date']]){const label=el('label','',title),input=el('input');input.type=type;fields[key]=input;label.append(input);filters.append(label);}
 const state=el('select');for(const [v,t]of [['','Todas as situações'],['novo','Novos'],['investigando','Em investigação'],['resolvido','Resolvidos']])state.append(new Option(t,v));fields.situacao=state;filters.append(state);c.append(filters);const result=el('div');c.append(result);let report=null;
 async function load(){const query=new URLSearchParams(Object.entries(fields).map(([k,n])=>[k,n.value]));report=await api('saude-sistema/erros?'+query);result.replaceChildren();if(!report.itens.length)result.append(el('p','','Nenhuma falha técnica registrada neste filtro. Validações normais não são classificadas como defeito do sistema.'));else table(['Código / módulo','Exceção / operação','Gravidade','Primeira / última ocorrência','Ocorrências','Situação',''],report.itens.map(e=>[e.code+' · '+e.module,e.kind+' · '+e.operation,e.severity,stamp(e.first_at)+' / '+stamp(e.last_at),e.total,e.state,button('Investigar',()=>detail(e.code))]),result);if(report.tem_mais)result.append(el('p','','Mostrando 200 grupos de erro. Refine os filtros.'));}
 filters.append(button('Filtrar',load),button('Baixar relatório filtrado',()=>{if(!report)return;const blob=new Blob([JSON.stringify({gerado_em:new Date().toISOString(),versao:health.versao,...report},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='ConectaAdv-erros.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));await load();
 async function detail(code){const d=await api('saude-sistema/erros/'+code),dialog=el('dialog','diagnostic-dialog');dialog.append(el('h2','',code+' · '+d.kind),el('p','',d.module+' · '+d.operation+' · '+d.total+' ocorrência(s)'),el('h3','','Sequência técnica da exceção'),el('pre','diagnostic-trace',JSON.stringify(d.technical,null,2)));
 const status=el('select');for(const [v,t]of [['novo','Novo'],['investigando','Investigando'],['resolvido','Resolvido']])status.append(new Option(t,v));status.value=d.state;
 const assignee=el('select');assignee.append(new Option('Sem responsável',''));for(const u of S.users.filter(u=>u.ativo))assignee.append(new Option(u.nome,u.id));assignee.value=d.assignee||'';
 const notes=el('textarea');notes.rows=4;notes.placeholder='Providência técnica. Não informe dados do cliente ou credenciais.';notes.value=d.notes||'';
 dialog.append(el('label','','Situação'),status,el('label','','Responsável'),assignee,el('label','','Observações técnicas'),notes,button('Salvar acompanhamento',async()=>{await api('saude-sistema/erros/'+code,{situacao:status.value,responsavel_id:assignee.value?Number(assignee.value):null,observacoes:notes.value});dialog.close();dialog.remove();await load();}),button('Fechar',()=>{dialog.close();dialog.remove();}));document.body.append(dialog);dialog.showModal();}
 },async renderFresh(){window.Juridico.$('content').replaceChildren();await this.render();}};
