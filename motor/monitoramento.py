"""Monitoramento por lista: cada resultado exige consulta e comparação confirmadas."""
import datetime as dt
import json, hashlib
from urllib.parse import urljoin,urlsplit
import juridico as legal
import mandados
import eproc_tribunais as courts

def schema(db):
 mandados.schema(db)
 db.executescript('''CREATE TABLE IF NOT EXISTS monitor_config(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS monitor_runs(id TEXT PRIMARY KEY,inicio TEXT,fim TEXT,tribunal TEXT,status TEXT,total INTEGER);
 CREATE TABLE IF NOT EXISTS monitor_results(run_id TEXT,numero TEXT,status TEXT,motivo TEXT,verificado TEXT,detalhes TEXT,PRIMARY KEY(run_id,numero));
 CREATE TABLE IF NOT EXISTS monitor_watch_context(numero TEXT PRIMARY KEY,data TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS monitor_watch_meta(id INTEGER PRIMARY KEY CHECK(id=1),problems TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS monitor_baselines(numero TEXT PRIMARY KEY,data TEXT NOT NULL,atualizado TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS monitor_results_number ON monitor_results(numero,verificado);
 ''')

def config(store,actor,body=None):
 if actor['role']!='administrador':raise legal.AppError('Configuração restrita ao administrador.',403)
 with store.lock,store.connect() as db:
  schema(db);old=db.execute('SELECT data FROM monitor_config WHERE id=1').fetchone()
  c=json.loads(old[0]) if old else {'ativo':False,'intervalo_horas':3,'tribunal':'TJRS','limite_minutos':50}
  if body is not None:
   if type(body.get('ativo'))is not bool or type(body.get('intervalo_horas'))is not int or body['intervalo_horas'] not in (2,3):raise legal.AppError('Escolha duas ou três horas e informe se deseja ativar.')
   if type(body.get('limite_minutos',50))is not int or not 10<=body.get('limite_minutos',50)<=55:raise legal.AppError('Orçamento deve ficar entre 10 e 55 minutos.')
   try:courts.config(body.get('tribunal','TJRS'))
   except ValueError:raise legal.AppError('Tribunal inválido.')
   numbers=[r[0] for r in db.execute('SELECT numero FROM mandate_watchlist')]
   if body['ativo'] and not any(courts.from_number(n)==body.get('tribunal','TJRS') for n in numbers):raise legal.AppError('Salve primeiro uma lista com processos desse tribunal.')
   c={k:body[k] for k in ('ativo','intervalo_horas')};c.update(tribunal=body.get('tribunal','TJRS'),limite_minutos=body.get('limite_minutos',50),actor_id=actor['id'],proxima=(dt.datetime.fromisoformat(legal.now())+dt.timedelta(hours=body['intervalo_horas'])).isoformat(timespec='seconds'))
   db.execute('INSERT OR REPLACE INTO monitor_config VALUES(1,?)',(legal.dumps(c),));store.audit(db,actor,'configurar_monitoramento','monitoramento',after=c)
  return c

def begin(store,run,tribunal,snapshot=None):
 with store.lock,store.connect() as db:
  schema(db)
  numbers=sorted(set(snapshot)) if snapshot is not None else [r[0] for r in db.execute('SELECT numero FROM mandate_watchlist') if courts.from_number(r[0])==tribunal]
  if any(courts.from_number(n)!=tribunal for n in numbers):raise legal.AppError('A lista contém processo de outro tribunal.')
  if not numbers:raise legal.AppError('Não há processos desse tribunal na lista.')
  # Rodízio: quem ainda não foi consultado vai primeiro, inclusive após estouro de orçamento.
  attempts={r[0]:r[1] for r in db.execute('SELECT numero,MAX(verificado) FROM monitor_results GROUP BY numero')}
  numbers.sort(key=lambda n:(attempts.get(n) or '',n))
  db.execute('INSERT INTO monitor_runs VALUES(?,?,NULL,?,?,?)',(run,legal.now(),tribunal,'em_andamento',len(numbers)))
  db.executemany("INSERT INTO monitor_results VALUES(?,?,'pendente','Aguardando consulta nesta rodada.',NULL,'[]')",[(run,n) for n in numbers])
  return numbers

def canonical(record):
 from eproc_estruturado import detail
 raw=record.get('detalhes') or {};coverage=raw.get('cobertura_eventos',{})
 parsed=detail(record)
 if not raw:raise ValueError('PAGINA_NAO_LIDA')
 if not parsed['validado']:raise ValueError('PROCESSO_NAO_CONFIRMADO')
 if parsed.get('avisos'):raise ValueError('ESTRUTURA_PARTES_NAO_CONFIRMADA')
 if coverage.get('completo') is not True:raise ValueError('HISTORICO_INCOMPLETO')
 events=parsed['eventos']
 if len({e['numero'] for e in events})!=len(events) or len(events)!=coverage.get('eventos_visiveis'):raise ValueError('EVENTOS_NAO_CONFIRMADOS')
 if not record.get('gravado_no_sistema'):raise ValueError('GRAVACAO_NAO_CONFIRMADA')
 return {'campos':parsed['campos'],'partes':sorted(parsed['partes'],key=legal.dumps),'eventos':{e['numero']:e for e in events}}

def diff(old,new):
 changes=[]
 for key in sorted(set(old['campos'])|set(new['campos'])):
  value=new['campos'].get(key)
  if old['campos'].get(key)!=value:changes.append({'tipo':'campo','campo':key,'antes':old['campos'].get(key),'depois':value})
 if old['partes']!=new['partes']:changes.append({'tipo':'partes','descricao':'Cadastro de partes ou representantes diferente da leitura anterior.'})
 for key,event in sorted(new['eventos'].items(),key=lambda x:int(x[0])):
  if old['eventos'].get(key)!=event:changes.append({'tipo':'novo_evento' if key not in old['eventos'] else 'evento_alterado','evento':key,'data':event['data'],'descricao':event['descricao'],'documentos_referencias':event.get('documentos_referencias','')})
 removed=sorted(set(old['eventos'])-set(new['eventos']))
 if removed:changes.append({'tipo':'eventos_ausentes','eventos':removed,'descricao':'Eventos anteriores deixaram de aparecer; conferir a origem.'})
 return changes

def result(store,run,number,record=None,reason='Consulta não confirmada.'):
 with store.lock,store.connect() as db:
  schema(db);state='falha';changes=[]
  if not db.execute('SELECT 1 FROM monitor_results WHERE run_id=? AND numero=?',(run,number)).fetchone():raise legal.AppError('Processo não pertence a esta rodada.',404)
  if record is not None:
   try:
    if record.get('processo')!=number:raise ValueError('PROCESSO_DIVERGENTE')
    new=canonical(record)
   except (ValueError,KeyError,TypeError) as exc:
    reasons={'PAGINA_NAO_LIDA':'A página do processo não foi lida.','PROCESSO_NAO_CONFIRMADO':'A página não confirmou o número do processo solicitado.','PROCESSO_DIVERGENTE':'O número lido não corresponde ao processo solicitado.','GRAVACAO_NAO_CONFIRMADA':'Os dados não tiveram gravação local confirmada.','ESTRUTURA_PARTES_NAO_CONFIRMADA':'A estrutura de partes/representantes precisa de conferência.','HISTORICO_INCOMPLETO':'O histórico não teve sequência e carregamento completos confirmados.','EVENTOS_NAO_CONFIRMADOS':'Há eventos repetidos ou divergência na quantidade de eventos extraídos; confira também a exibição do processo originário.'}
    reason=record.get('diagnostico_seguro') or reasons.get(str(exc),'A leitura não passou pela validação.')
    reason+=' Não é possível afirmar se houve atualização.'
   else:
    prior=db.execute('SELECT data FROM monitor_baselines WHERE numero=?',(number,)).fetchone()
    if prior:
     changes=diff(json.loads(prior[0]),new);state='atualizado' if changes else 'sem_atualizacao'
     reason=(str(len(changes))+' diferença(s) em relação à última leitura confirmada.') if changes else 'Sem diferenças nos campos, partes e eventos comparados com a última leitura confirmada.'
    else:state='primeira_leitura';reason='Primeira leitura confirmada: base para comparar nas próximas consultas. Não significa novidade recente.'
    db.execute('INSERT OR REPLACE INTO monitor_baselines VALUES(?,?,?)',(number,legal.dumps(new),legal.now()))
  db.execute('UPDATE monitor_results SET status=?,motivo=?,verificado=?,detalhes=? WHERE run_id=? AND numero=?',(state,reason,legal.now(),legal.dumps(changes),run,number))
  return {'status':state,'motivo':reason,'diferencas':changes}

def finish(store,run,state):
 with store.lock,store.connect() as db:
  schema(db)
  db.execute("UPDATE monitor_results SET status='nao_consultado',motivo=? WHERE run_id=? AND status='pendente'",('Rodada encerrada: '+state+'. Sem leitura confirmada nesta rodada.',run))
  db.execute('UPDATE monitor_runs SET fim=?,status=? WHERE id=?',(legal.now(),state,run))

def status(store,actor,run='',page=1):
 with store.lock,store.connect() as db:
  schema(db);runs=[dict(r) for r in db.execute('SELECT * FROM monitor_runs ORDER BY inicio DESC,id DESC LIMIT 30')]
  selected=run or (runs[0]['id'] if runs else '')
  if selected and not db.execute('SELECT 1 FROM monitor_runs WHERE id=?',(selected,)).fetchone():raise legal.AppError('Rodada não encontrada.',404)
  counts=dict(db.execute('SELECT status,COUNT(*) FROM monitor_results WHERE run_id=? GROUP BY status',(selected,)))
  try:page=int(page)
  except (ValueError,TypeError):raise legal.AppError('Página inválida.')
  if not 1<=page<=100000:raise legal.AppError('Página inválida.')
  rows=[]
  for row in db.execute('SELECT r.*,b.atualizado AS ultima_confirmada FROM monitor_results r LEFT JOIN monitor_baselines b ON b.numero=r.numero WHERE run_id=? ORDER BY CASE r.status WHEN \'atualizado\' THEN 0 WHEN \'falha\' THEN 1 ELSE 2 END,r.numero LIMIT 50 OFFSET ?',(selected,(page-1)*50)):
   item=dict(row);item['detalhes']=json.loads(item['detalhes']);rows.append(item)
  listed=[r[0] for r in db.execute('SELECT numero FROM mandate_watchlist')]
  total=len(listed)
  from collections import Counter
  coverage=dict(Counter(courts.from_number(n) or 'outros_tribunais' for n in listed))
  return {'rodadas':runs,'rodada':selected,'contagens':counts,'itens':rows,'pagina':page,'total_lista':total,'tribunais_lista':coverage,'limite':50,'cobertura':'Comparação de campos, partes e eventos lidos. Não compara o conteúdo dos PDFs. Falha ou processo não consultado não significa ausência de novidade.'}

def tick(store,collector):
 if manual_tick(store,collector):return True
 if repeat_tick(store,collector):return True
 if collector.thread and collector.thread.is_alive():return
 with store.lock,store.connect() as db:
  schema(db);row=db.execute('SELECT data FROM monitor_config WHERE id=1').fetchone()
  if not row:return False
  cfg=json.loads(row[0]);now=dt.datetime.fromisoformat(legal.now())
  if not cfg['ativo'] or now<dt.datetime.fromisoformat(cfg['proxima']):return False
  user=db.execute("SELECT * FROM users WHERE id=? AND ativo=1 AND role='administrador'",(cfg['actor_id'],)).fetchone()
  if not user:return False
  # Reserva antes de iniciar: sem rodada simultânea nem rajada ao recuperar janela perdida.
  cfg['proxima']=(now+dt.timedelta(hours=cfg['intervalo_horas'])).isoformat(timespec='seconds')
  db.execute('UPDATE monitor_config SET data=? WHERE id=1',(legal.dumps(cfg),));actor=store.public_user(user)
  store.audit(db,actor,'iniciar_monitoramento_agendado','monitoramento',after={'tribunal':cfg['tribunal']})
 try:collector.start(actor=actor,options={'monitorar_lista':True,'tribunal':cfg['tribunal'],'modo':'completa','automatico':True,'limite_minutos':cfg['limite_minutos']})
 except ValueError:return False
 return True


def lookup(collector,context,page,entry,number,snapshot_js):
 """Usa somente o formulário real observado; nunca constrói URL com hash."""
 def form_on_page():
  for frame in page.frames:
   if urlsplit(frame.url).hostname!=courts.config(collector.options['tribunal'])['host']:continue
   forms=frame.locator('form[name="formPesquisaRapida"]')
   for i in range(forms.count()):
    f=forms.nth(i);action=urljoin(frame.url,f.get_attribute('action') or '')
    inputs=f.locator('input[name="txtNumProcessoPesquisaRapida"]');buttons=f.locator('button[name="btnPesquisaRapidaSubmit"]')
    if courts.valid_url(action,collector.options['tribunal'],('processo_pesquisa_rapida',)) and inputs.count()==1 and buttons.count()==1 and inputs.first.is_visible() and buttons.first.is_visible():return inputs.first,buttons.first
  return None
 found=form_on_page()
 if not found:page.goto(entry,wait_until='domcontentloaded',timeout=60000);found=form_on_page()
 if not found:raise ValueError('FORMULARIO_NAO_LOCALIZADO')
 previous=set(context.pages);found[0].fill(number,timeout=10000);found[1].click(timeout=20000)
 for _ in range(80):
  collector.check()
  candidates=[p for p in context.pages if not p.is_closed() and (p==page or p not in previous)]
  for candidate in candidates:
   for frame in candidate.frames:
    if not courts.valid_url(frame.url,collector.options['tribunal'],('processo_selecionar','processo_consultar','processo_pesquisa_rapida')):continue
    if frame.locator('input[type="password"]').count():continue
    text=frame.locator('body').inner_text()
    import re
    if re.search(r'Nº do processo\s*'+re.escape(number)+r'\b',text):return candidate,frame
  page.wait_for_timeout(250)
 raise ValueError('PROCESSO_NAO_CONFIRMADO')


def collect(collector,context,records,pages):
 from juridico import store
 import eproc
 run=collector.current['id'];numbers=collector.monitor_numbers;collector.update(encontrados=len(numbers))
 # A rotina já usada seleciona o perfil e localiza a listagem sem percorrer suas páginas.
 frame=collector.await_listing(context);entry=frame.url;page=context.new_page()
 errors=0
 try:
  for number in numbers:
   collector.check();collector.log('Monitoramento por número: '+number)
   record={'processo':number,'detalhes':None,'gravado_no_sistema':False,'situacao':'falha_na_leitura'}
   extras=set(context.pages);global_failure=False;stage='Pesquisa do processo pelo número'
   try:
    target,frame=lookup(collector,context,page,entry,number,eproc.SNAPSHOT)
    stage='Carregamento do histórico de movimentações'
    from eproc_eventos import expand
    from types import SimpleNamespace
    cov=expand(collector,SimpleNamespace(evaluate=frame.evaluate,wait_for_timeout=frame.page.wait_for_timeout));snapshot=frame.evaluate(eproc.SNAPSHOT)
    import mandados_documentos
    mandados_documentos.capture(number,snapshot)
    import re
    if not re.search(r'Nº do processo\s*'+re.escape(number)+r'\b',snapshot['texto']):raise ValueError('PROCESSO_NAO_CONFIRMADO')
    record.update(detalhes={**eproc.public_snapshot(snapshot),'cobertura_eventos':cov},situacao='pagina_lida_requer_conferencia' if cov['completo'] else 'historico_parcial')
    same=False
    try:candidate=canonical({**record,'gravado_no_sistema':True})
    except (ValueError,KeyError,TypeError):candidate=None
    if candidate is not None:
     with store.lock,store.connect() as db:
      baseline=db.execute('SELECT data FROM monitor_baselines WHERE numero=?',(number,)).fetchone()
      exists=db.execute("SELECT 1 FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
      same=bool(baseline and exists and json.loads(baseline[0])==candidate)
    if candidate is not None:
     if not same:
      stage='Gravação dos dados no sistema'
      store.import_corpus({'execucao':{'id':run+':monitor:'+number,'fim':legal.now()},'processos':[record],'paginas_da_lista':[]},collector.actor)
      collector.update(salvos_sistema=collector.current.get('salvos_sistema',0)+1)
     record['gravado_no_sistema']=True;record['gravacao_dispensada_sem_alteracao']=same
   except InterruptedError:raise
   except Exception as exc:
    record['situacao']='consulta_ou_importacao_nao_confirmada'
    record['diagnostico_seguro']=collector.diagnostic(exc,stage)
    global_failure=isinstance(exc,ValueError) and str(exc)=='FORMULARIO_NAO_LOCALIZADO'
   finally:
    for extra in list(context.pages):
     if extra not in extras and extra!=page:
      try:extra.close()
      except Exception:pass
   outcome=result(store,run,number,record,reason='Consulta pelo número não confirmada. Pode haver sessão vencida, falta de acesso, formulário incompatível ou falha de gravação.')
   if outcome['status']=='falha':errors+=1
   collector.log(number+': '+outcome['status']+' - '+outcome['motivo'])
   if record.get('gravacao_dispensada_sem_alteracao'):record['detalhes']=None
   records.append(record);collector.update(lidos=len(records),falhas=errors);collector.save_checkpoint(records,pages)
   if global_failure:
    collector.log('Formulário de pesquisa não localizado: rodada interrompida; demais processos ficam não consultados. Confira login e compatibilidade do layout.');return 'parcial'
   collector.check();page.wait_for_timeout(500)
 finally:
  try:page.close()
  except Exception:pass
 return 'coletado_revisar' if not errors else 'parcial'

# Pedidos manuais, em sequência, usando o mesmo coletor e sessões separadas.
def jobs_schema(db):
 schema(db)
 db.executescript('''CREATE TABLE IF NOT EXISTS monitor_repeat(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS monitor_jobs(id TEXT PRIMARY KEY,actor_id INTEGER,created TEXT,state TEXT,nonce TEXT,summary TEXT,UNIQUE(actor_id,nonce));
 CREATE TABLE IF NOT EXISTS monitor_job_courts(job_id TEXT,tribunal TEXT,state TEXT,run_id TEXT,numbers TEXT,PRIMARY KEY(job_id,tribunal));''')

def search_list(store,actor,collector,body,automatic=False):
 import re,uuid
 if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
 nums=body.get('numeros');nonce=body.get('nonce')
 raw_context=body.get('contexto',None);problems=body.get('problemas',None)
 if raw_context is not None and (not isinstance(raw_context,list) or len(raw_context)>20000 or any(not isinstance(r,dict) or set(r)-{'numero','nome_cliente','contato','origem'} or any(not isinstance(v,str) for v in r.values()) for r in raw_context)):raise legal.AppError('Informações de cliente inválidas.')
 if problems is not None and (not isinstance(problems,list) or len(problems)>20000 or any(not isinstance(r,dict) or set(r)-{'aba','linha','valor','motivo'} or type(r.get('linha'))is not int or any(not isinstance(r.get(k,''),str) for k in ('aba','valor','motivo')) for r in problems)):raise legal.AppError('Relatório de importação inválido.')
 interval=body.get('intervalo_horas',0)
 if type(interval)is not int or interval not in (0,2,3):raise legal.AppError('Escolha uma consulta, duas ou três horas.')
 if 'intervalo_horas' in body and actor['role']!='administrador':raise legal.AppError('Somente o administrador configura a repetição.',403)
 if not isinstance(nums,list) or not 1<=len(nums)<=20000 or not isinstance(nonce,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',nonce):raise legal.AppError('Lista ou identificação do pedido inválida.')
 numbers={mandados.number(n) for n in nums}
 if None in numbers:raise legal.AppError('Corrija os números inválidos antes de procurar.')
 if body.get('acao','substituir') not in ('substituir','adicionar'):raise legal.AppError('Modo de lista inválido.')
 with store.lock,store.connect() as db:
  jobs_schema(db)
  prior=db.execute('SELECT id,summary FROM monitor_jobs WHERE actor_id=? AND nonce=?',(actor['id'],nonce)).fetchone()
  signature=hashlib.sha256(legal.dumps({'numeros':sorted(numbers),'acao':body.get('acao','substituir'),'intervalo_horas':interval,'contexto':raw_context,'problemas':problems}).encode()).hexdigest()
  if prior:
   if json.loads(prior['summary']).get('signature')!=signature:raise legal.AppError('Pedido reutilizado com outra lista.',409)
   return {'id':prior['id'],'repetido':True}
  if (collector.thread and collector.thread.is_alive()) or db.execute("SELECT 1 FROM monitor_jobs WHERE state='ativo'").fetchone():raise legal.AppError('Existe uma consulta em andamento. Aguarde ou cancele antes de iniciar outra.',409)
  if body.get('acao')=='adicionar':numbers.update(r[0] for r in db.execute('SELECT numero FROM mandate_watchlist'))
  grouped={court:sorted(n for n in numbers if courts.from_number(n)==court) for court in courts.TRIBUNAIS if courts.enabled(court)}
  if not any(grouped.values()):raise legal.AppError('Nenhum processo pertence ao TJRS, único tribunal ativo. TJSC está temporariamente desativado. A lista atual não foi alterada.')
  if raw_context is not None:
   grouped_context={}
   for ctx in raw_context:
    number=mandados.number(ctx.get('numero',''))
    if number not in numbers:raise legal.AppError('Cliente informado para processo fora da lista.')
    clean={'nome_cliente':ctx.get('nome_cliente','').strip()[:240],'contato':ctx.get('contato','').strip()[:500],'origem':ctx.get('origem','').strip()[:180]}
    if clean not in grouped_context.setdefault(number,[]):grouped_context[number].append(clean)
   if body.get('acao','substituir')=='substituir':db.execute('DELETE FROM monitor_watch_context')
   for n,entries in grouped_context.items():db.execute('INSERT OR REPLACE INTO monitor_watch_context VALUES(?,?)',(n,legal.dumps(entries)))
  if problems is not None:
   problems=[{'aba':r.get('aba','')[:120],'linha':r['linha'],'valor':r.get('valor','')[:100],'motivo':r.get('motivo','')[:300]} for r in problems]
   if body.get('acao')=='adicionar':
    old=db.execute('SELECT problems FROM monitor_watch_meta WHERE id=1').fetchone()
    if old:
     for issue in json.loads(old[0]):
      if issue not in problems:problems.append(issue)
   db.execute('INSERT OR REPLACE INTO monitor_watch_meta VALUES(1,?)',(legal.dumps(problems),))
  stored_problems=db.execute('SELECT problems FROM monitor_watch_meta WHERE id=1').fetchone()
  contexts={r['numero']:json.loads(r['data']) for r in db.execute('SELECT * FROM monitor_watch_context') if r['numero'] in numbers}
  jid=uuid.uuid4().hex
  summary={'contexto':contexts,'problemas':json.loads(stored_problems[0]) if stored_problems else [],'automatico':automatic,'signature':signature,'total':len(numbers),'sem_conector':sorted(n for n in numbers if not courts.enabled(courts.from_number(n))),'tribunais':{k:len(v) for k,v in grouped.items() if v}}
  db.execute('DELETE FROM mandate_watchlist');db.executemany('INSERT INTO mandate_watchlist VALUES(?)',[(n,) for n in sorted(numbers)])
  db.execute("INSERT OR REPLACE INTO mandate_state VALUES('somente_lista','1')")
  db.execute("INSERT OR REPLACE INTO mandate_state VALUES('cursor','0')")
  db.execute('INSERT INTO monitor_jobs VALUES(?,?,?,?,?,?)',(jid,actor['id'],legal.now(),'ativo',nonce,legal.dumps(summary)))
  db.executemany("INSERT INTO monitor_job_courts VALUES(?,?,'aguardando',NULL,?)",[(jid,k,legal.dumps(v)) for k,v in grouped.items() if v])
  if 'intervalo_horas' in body:
   repeat={'ativo':bool(interval),'intervalo_horas':interval or 3,'actor_id':actor['id'],'proxima':(dt.datetime.fromisoformat(legal.now())+dt.timedelta(hours=interval or 3)).isoformat(timespec='seconds')}
   db.execute('INSERT OR REPLACE INTO monitor_repeat VALUES(1,?)',(legal.dumps(repeat),))
   old=db.execute('SELECT data FROM monitor_config WHERE id=1').fetchone()
   if old:
    oldcfg=json.loads(old[0]);oldcfg['ativo']=False;db.execute('UPDATE monitor_config SET data=? WHERE id=1',(legal.dumps(oldcfg),))
  store.audit(db,actor,'procurar_lista','monitoramento',jid,after={'total':len(numbers),'tribunais':summary['tribunais'],'sem_conector':len(summary['sem_conector'])})
 # A fila continua pelo agendador, inclusive após recarregar a página.
 manual_tick(store,collector)
 return {'id':jid,'repetido':False,'resumo':summary}

def job_status(store,actor):
 with store.lock,store.connect() as db:
  jobs_schema(db)
  jobs=[]
  for row in db.execute('SELECT * FROM monitor_jobs ORDER BY created DESC,rowid DESC LIMIT 5'):
   item=dict(row);item.pop('nonce',None);item['resumo']=json.loads(item.pop('summary'));item['resumo'].pop('signature',None)
   item['etapas']=[dict(r) for r in db.execute('SELECT tribunal,state,run_id FROM monitor_job_courts WHERE job_id=? ORDER BY tribunal',(item['id'],))]
   for stage in item['etapas']:
    stage['contagens']=dict(db.execute('SELECT status,COUNT(*) FROM monitor_results WHERE run_id=? GROUP BY status',(stage['run_id'],))) if stage['run_id'] else {}
   jobs.append(item)
  return jobs

def cancel_job(store,actor,collector,jid):
 with store.lock,store.connect() as db:
  jobs_schema(db);job=db.execute('SELECT * FROM monitor_jobs WHERE id=?',(jid,)).fetchone()
  if not job:raise legal.AppError('Pedido não encontrado.',404)
  if actor['role']=='leitor' or (actor['role']!='administrador' and job['actor_id']!=actor['id']):raise legal.AppError('Não é permitido cancelar este pedido.',403)
  db.execute("UPDATE monitor_jobs SET state='cancelado' WHERE id=?",(jid,))
  db.execute("UPDATE monitor_job_courts SET state='cancelado' WHERE job_id=? AND state='aguardando'",(jid,))
  if collector.options.get('monitor_job')==jid and collector.thread and collector.thread.is_alive():collector.action('cancelar')
  store.audit(db,actor,'cancelar_pedido_lista','monitoramento',jid)
 return {'cancelado':True}

def manual_tick(store,collector):
 if collector.thread and collector.thread.is_alive():return False
 with store.lock,store.connect() as db:
  jobs_schema(db)
  # Registra o encerramento antes de decidir se pode seguir ao outro tribunal.
  for stage in db.execute("SELECT * FROM monitor_job_courts WHERE state='consultando'").fetchall():
   run=db.execute('SELECT status FROM monitor_runs WHERE id=?',(stage['run_id'],)).fetchone()
   final=run[0] if run and run[0]!='em_andamento' else 'interrompido'
   if run and run[0]=='em_andamento':
    db.execute("UPDATE monitor_results SET status='nao_consultado',motivo='Servidor interrompido antes da confirmação.' WHERE run_id=? AND status='pendente'",(stage['run_id'],))
    db.execute("UPDATE monitor_runs SET status='interrompido',fim=? WHERE id=?",(legal.now(),stage['run_id']))
   db.execute('UPDATE monitor_job_courts SET state=? WHERE job_id=? AND tribunal=?',(final,stage['job_id'],stage['tribunal']))
   if final=='cancelado':
    db.execute("UPDATE monitor_jobs SET state='cancelado' WHERE id=?",(stage['job_id'],))
    db.execute("UPDATE monitor_job_courts SET state='cancelado' WHERE job_id=? AND state='aguardando'",(stage['job_id'],))
  for job in db.execute("SELECT * FROM monitor_jobs WHERE state='ativo' ORDER BY created").fetchall():
   for paused in courts.TRIBUNAIS:
    if not courts.enabled(paused):db.execute("UPDATE monitor_job_courts SET state='tribunal_desativado' WHERE job_id=? AND state='aguardando' AND tribunal=?",(job['id'],paused))
   stage=db.execute("SELECT * FROM monitor_job_courts WHERE job_id=? AND state='aguardando' ORDER BY tribunal",(job['id'],)).fetchone()
   if not stage:
    db.execute("UPDATE monitor_jobs SET state='encerrado' WHERE id=?",(job['id'],));continue
   user=db.execute("SELECT * FROM users WHERE id=? AND ativo=1 AND role!='leitor'",(job['actor_id'],)).fetchone()
   if not user:
    db.execute("UPDATE monitor_jobs SET state='acesso_revogado' WHERE id=?",(job['id'],));db.execute("UPDATE monitor_job_courts SET state='acesso_revogado' WHERE job_id=? AND state='aguardando'",(job['id'],));continue
   db.commit()
   try:
    output=collector.start(actor=store.public_user(user),options={'automatico':bool(json.loads(job['summary']).get('automatico')),'monitorar_lista':True,'monitor_job':job['id'],'numeros_monitorados':json.loads(stage['numbers']),'tribunal':stage['tribunal'],'modo':'completa','limite_minutos':50})
   except ValueError:return False
   db.execute("UPDATE monitor_job_courts SET state='consultando',run_id=? WHERE job_id=? AND tribunal=?",(output['atual']['id'],job['id'],stage['tribunal']))
   return True
 return False

def repeat_config(store,actor):
 if actor['role']!='administrador':raise legal.AppError('Rotina restrita ao administrador.',403)
 with store.lock,store.connect() as db:
  jobs_schema(db);row=db.execute('SELECT data FROM monitor_repeat WHERE id=1').fetchone()
  return json.loads(row[0]) if row else {'ativo':False,'intervalo_horas':3}

def repeat_tick(store,collector):
 import uuid
 if collector.thread and collector.thread.is_alive():return False
 with store.lock,store.connect() as db:
  jobs_schema(db);row=db.execute('SELECT data FROM monitor_repeat WHERE id=1').fetchone()
  if not row:return False
  cfg=json.loads(row[0]);now=dt.datetime.fromisoformat(legal.now())
  if not cfg['ativo'] or now<dt.datetime.fromisoformat(cfg['proxima']) or db.execute("SELECT 1 FROM monitor_jobs WHERE state='ativo'").fetchone():return False
  user=db.execute("SELECT * FROM users WHERE id=? AND ativo=1 AND role='administrador'",(cfg['actor_id'],)).fetchone()
  numbers=[r[0] for r in db.execute('SELECT numero FROM mandate_watchlist')]
  if not user or not any(courts.enabled(courts.from_number(n)) for n in numbers):
   cfg['ativo']=False;db.execute('UPDATE monitor_repeat SET data=? WHERE id=1',(legal.dumps(cfg),));return False
  cfg['proxima']=(now+dt.timedelta(hours=cfg['intervalo_horas'])).isoformat(timespec='seconds');db.execute('UPDATE monitor_repeat SET data=? WHERE id=1',(legal.dumps(cfg),));actor=store.public_user(user)
 try:search_list(store,actor,collector,{'numeros':numbers,'nonce':'auto-'+uuid.uuid4().hex,'acao':'substituir'},automatic=True)
 except legal.AppError:return False
 return True

def pause_repeat(store,actor):
 if actor['role']!='administrador':raise legal.AppError('Rotina restrita ao administrador.',403)
 with store.lock,store.connect() as db:
  jobs_schema(db);row=db.execute('SELECT data FROM monitor_repeat WHERE id=1').fetchone()
  if row:
   cfg=json.loads(row[0]);cfg['ativo']=False;db.execute('UPDATE monitor_repeat SET data=? WHERE id=1',(legal.dumps(cfg),))
  store.audit(db,actor,'pausar_repeticao_lista','monitoramento')
 return {'pausado':True}
