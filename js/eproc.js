'use strict';
(() => {
 const get = id => document.getElementById(id);
 const labels = {iniciando:'Iniciando',aguardando:'Aguardando sua participação',coletando:'Coletando',coletado_revisar:'Leitura encerrada — conferir dados',parcial:'Parcial — conferir paginação e falhas',cancelado:'Cancelado',erro:'Falha na coleta',erro_exportacao:'Falha ao gravar arquivo'};
 let pending = false;
 const date = v => v ? new Date(v).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}) : '—';
 function render(data) {
  const cur = data.atual;
  const active = cur && ['iniciando','aguardando','coletando'].includes(cur.estado);
  get('eprocStart').disabled = pending || !!active;
  get('eprocContinue').hidden = !cur || cur.estado !== 'aguardando';
  get('eprocCancel').hidden = !active;
  get('eprocStatus').textContent = cur ? `${labels[cur.estado] || cur.estado} · ${cur.lidos}/${cur.encontrados} processos · ${cur.mensagem}` : 'Pronto. Execute com INICIAR.bat e instale o navegador pelo INSTALAR_EPROC.bat na primeira utilização.';
  get('eprocLog').textContent = cur ? cur.log.map(x=>`${date(x.data)} — ${x.mensagem}`).join('\n') : 'Nenhuma execução nesta sessão.';
  get('eprocHistory').replaceChildren();
  for (const item of data.historico) {
   const row = document.createElement('tr');
   for(const val of [date(item.inicio),date(item.fim),labels[item.estado] || item.estado,`${item.lidos} / ${item.encontrados}`]) {
    const cell = document.createElement('td');cell.textContent=val;row.append(cell);
   }
   const cell=document.createElement('td');
   if(item.arquivo_pronto) {const a=document.createElement('a');a.textContent='Baixar ZIP + log';a.href='./api/eproc/exportar?id='+encodeURIComponent(item.id);cell.append(a);}
   else cell.textContent='Em andamento / sem arquivo';
   row.append(cell);get('eprocHistory').append(row);
  }
 }
 async function refresh() {
  try {
   const response = await fetch('./api/eproc/status',{cache:'no-store'});
   if(!response.ok) throw new Error();
   render(await response.json());
  } catch {
   get('eprocStatus').textContent='Coleta eproc disponível apenas pelo servidor Python local: execute INICIAR.bat. A hospedagem PHP continua com a consulta DJEN.';
   get('eprocStart').disabled=true;
  }
 }
 async function action(name) {
  pending=true;get('eprocStart').disabled=true;
  try {
   const session=await (await fetch('./api/juridico/sessao')).json();
   if(!session.usuario) throw new Error('Entre no sistema na página inicial antes de coletar.');
   const response=await fetch('./api/eproc/'+name,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:'{}'});
   const data=await response.json();
   if(!response.ok) throw new Error(data.erro || 'Falha na solicitação.');
   render(data.resultado || data);
  } catch(error) { get('eprocStatus').textContent=error.message; }
  finally {pending=false;await refresh();}
 }
 get('eprocStart').onclick=()=>action('iniciar');
 get('eprocContinue').onclick=()=>action('continuar');
 get('eprocCancel').onclick=()=>action('cancelar');
 refresh();setInterval(refresh,2500);
})();
