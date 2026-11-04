"""Relatórios por pedido e data de expedição, com prévia imutável e envio manual."""
import datetime as dt,json,uuid,hashlib
from zoneinfo import ZoneInfo
import juridico as legal
import email_resumos,email_alertas
from mandados_resumo import summarize
ZONE=ZoneInfo('America/Sao_Paulo')

def schema(db):db.execute('CREATE TABLE IF NOT EXISTS mandate_reports(id TEXT PRIMARY KEY,criado TEXT NOT NULL,data TEXT NOT NULL,signature TEXT NOT NULL UNIQUE)')
def day(value):
 try:
  when=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
  return (when.astimezone(ZONE) if when.tzinfo else when).date()
 except (ValueError,TypeError):return None

def options(store,actor):
 with store.lock,store.connect() as db:
  email_resumos.schema(db)
  batches=email_resumos.completed(db,details=False,pending_only=False)
 return {'hoje':dt.datetime.fromisoformat(legal.now()).date().isoformat(),'pedidos':[{'id':b['key'],'inicio':b['inicio'],'fim':b['fim'],'situacao':b['status']} for b in sorted(batches,key=lambda b:b['inicio'],reverse=True)[:30]]}

def create(store,actor,body):
 start=body.get('inicio','');end=body.get('fim','');key=body.get('pedido')
 try:
  a=dt.date.fromisoformat(start) if start else None;b=dt.date.fromisoformat(end) if end else None
 except (ValueError,TypeError):raise legal.AppError('Escolha datas válidas.')
 if a and b and a>b:raise legal.AppError('A data inicial deve ser anterior ou igual à final.')
 with store.lock,store.connect() as db:
  schema(db);email_resumos.schema(db)
  batch=next((r for r in email_resumos.completed(db,pending_only=False) if r['key']==key),None)
  if not batch:raise legal.AppError('Selecione um pedido de consulta concluído.',404)
  batch=email_resumos.enrich(db,batch)
  confirmed={'atualizado','primeira_leitura','sem_atualizacao'}
  good=[r for r in batch['itens'] if r['status'] in confirmed]
  failures=[{'numero':r['numero'],'motivo':r.get('motivo','Consulta não concluída.'),'verificado':r.get('verificado')} for r in batch['itens'] if r['status'] not in confirmed]
  failures.extend({'numero':n,'motivo':'TJSC temporariamente desativado ou tribunal sem conector; não consultado.','verificado':None} for n in batch['sem_conector'])
  found=[];unknown=[];unverifiable=[]
  for row in good:
   case=db.execute("SELECT id FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(row['numero'],)).fetchone()
   # Não misturar dados obtidos depois do encerramento deste pedido.
   events=[]
   if case and db.execute("SELECT 1 FROM sqlite_master WHERE name='source_events'").fetchone():
    cols={r[1] for r in db.execute('PRAGMA table_info(source_events)')}
    if 'import_id' in cols:
     for entry in db.execute('SELECT e.* FROM source_events e JOIN imports i ON i.id=e.import_id WHERE e.case_id=? AND i.data<=? ORDER BY i.data,e.id',(case[0],batch['fim'])):
      event=json.loads(entry['payload']);event['numero']=entry['numero'];event['data']=entry['data'];events.append(event)
   if not events:
    unverifiable.append({'numero':row['numero'],'motivo':'Consulta registrada como concluída, mas os eventos vinculados à importação não estão disponíveis para este relatório.','verificado':row.get('verificado')});continue
   for mandate in summarize(events)['mandados']:
    issuance=mandate['expedicao'];date=day(issuance.get('data'))
    item={'numero':row['numero'],'cliente_contato':email_resumos.identity(batch,row['numero']),'expedicao':issuance,'ultimo_evento':mandate['atualizacao'],'situacao':mandate['situacao'],'retorno_localizado':mandate['retorno_localizado']}
    if not date:unknown.append(item)
    elif (not a or date>=a) and (not b or date<=b):found.append(item)
  for fail in failures+unverifiable:fail['cliente_contato']=email_resumos.identity(batch,fail['numero'])
  found.sort(key=lambda i:(i['expedicao'].get('data') or '',i['numero']),reverse=True)
  result={'pedido':key,'inicio':start,'fim':end,'consulta_inicio':batch['inicio'],'consulta_fim':batch['fim'],'consulta_situacao':batch['status'],'previstos':len(batch['itens'])+len(batch['sem_conector']),'consultados':len(good),'falhas':failures,'mandados':found,'sem_data':unknown,'sem_evidencia':unverifiable,'problemas_planilha':batch.get('problemas',[])}
  texts=messages(result);result['mensagens']=texts
  signature=hashlib.sha256(legal.dumps(result).encode()).hexdigest()
  prior=db.execute('SELECT id FROM mandate_reports WHERE signature=?',(signature,)).fetchone()
  ident=prior[0] if prior else uuid.uuid4().hex
  if not prior:db.execute('INSERT INTO mandate_reports VALUES(?,?,?,?)',(ident,legal.now(),legal.dumps(result),signature))
  result['id']=ident
  email_alertas.schema(db)
  result['envios']={r['parte']:r['status'] for r in db.execute('SELECT p.parte,d.status FROM email_digest_parts p JOIN email_delivery d ON d.id=p.delivery_id WHERE p.batch_key=?',('mandados-relatorio:'+ident,))}
 return result

def display(value):
 try:
  v=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
  return (v.astimezone(ZONE) if v.tzinfo else v).strftime('%d/%m/%Y às %H:%M:%S')
 except (ValueError,TypeError):return str(value or 'não informada')

def messages(r):
 period=(r['inicio'] or 'início do histórico')+' a '+(r['fim'] or 'fim do histórico')
 prefix='ConectaAdv — relatório de mandados\nPeríodo de EXPEDIÇÃO: '+period+'\nConsulta: '+display(r['consulta_inicio'])+' até '+display(r['consulta_fim'])+'\nSituação da coleta: '+r['consulta_situacao']+'\n'+str(r['previstos'])+' previstos · '+str(r['consultados'])+' consultas concluídas · '+str(len(r['falhas']))+' falhas/não consultados.\n'
 yes=[prefix,'MANDADOS EXPEDIDOS NO PERÍODO: '+str(len(r['mandados']))]
 for item in r['mandados']:
  e=item['expedicao'];last=item['ultimo_evento'];yes.extend(['\nProcesso: '+item['numero'],item['cliente_contato'],'Expedição: evento '+e['evento']+' · '+display(e.get('data')),e['descricao'],'Documentos: '+', '.join(e['documentos']),'Último evento relacionado: '+last['evento']+' · '+display(last.get('data'))+' · '+last['descricao'],item['situacao'],'Acesse o processo e confira o documento e a providência necessária.'])
 if not r['mandados']:yes.append('Nenhuma expedição encontrada no período nos eventos disponíveis. As falhas e evidências indisponíveis estão no relatório separado.')
 if r['sem_data']:yes.append('\nExpedições sem data para enquadrar no período: '+', '.join(i['numero']+' (evento '+i['expedicao']['evento']+')' for i in r['sem_data']))
 yes.append('Datas são dos eventos, não da descoberta. Ausência de retorno não comprova ausência de cumprimento. Conteúdo dos PDFs não foi analisado.')
 errors=[prefix,'FALHAS E NÃO CONSULTADOS — INDEPENDENTES DO FILTRO DE DATA']
 for item in r['falhas']+r['sem_evidencia']:errors.extend(['\nProcesso: '+item['numero'],item['cliente_contato'],'Tentativa: '+display(item.get('verificado')),'Motivo: '+item['motivo']])
 if not r['falhas'] and not r['sem_evidencia']:errors.append('Nenhuma falha de consulta ou evidência indisponível registrada neste pedido.')
 for issue in r['problemas_planilha']:errors.append('Planilha: '+str(issue.get('aba',''))+' · linha '+str(issue.get('linha',''))+' · '+str(issue.get('motivo','Número inválido')))
 errors.append('Estas são falhas de coleta/processamento do ConectaAdv, não falhas na tramitação judicial. Não é possível afirmar ausência de mandado nesses casos.')
 return [{'parte':'mandados','assunto':'ConectaAdv — mandados expedidos: '+str(len(r['mandados']))+' | '+period,'texto':'\n'.join(yes),'quantidade':len(r['mandados'])},{'parte':'falhas','assunto':'ConectaAdv — falhas da consulta: '+str(len(r['falhas']))+' | evidências indisponíveis: '+str(len(r['sem_evidencia'])),'texto':'\n'.join(errors),'quantidade':len(r['falhas'])+len(r['sem_evidencia'])}]

def send(store,actor,body):
 email_alertas.admin(actor)
 parts=body.get('partes');ident=body.get('id')
 if not isinstance(ident,str) or not isinstance(parts,list) or not parts or any(x not in ('mandados','falhas') for x in parts) or len(set(parts))!=len(parts):raise legal.AppError('Selecione mandados, falhas ou ambos.')
 with email_alertas.LOCK:
  config=email_alertas.load(store)
  if not config:raise legal.AppError('Configure o e-mail em Notificações antes de enviar.')
  if config['destinatario']!=body.get('destinatario') or config['remetente']!=body.get('remetente'):raise legal.AppError('Configuração alterada. Reabra a prévia.',409)
  with store.lock,store.connect() as db:
   schema(db);row=db.execute('SELECT data FROM mandate_reports WHERE id=?',(ident,)).fetchone()
   if not row:raise legal.AppError('Gere a prévia antes de enviar.',404)
   report=json.loads(row[0])
  results=[]
  for message in report['mensagens']:
   if message['parte'] in parts:
    try:results.append(email_alertas.deliver(store,config,message['assunto'],message['texto'],'mandados_periodo_'+message['parte'],digest=('mandados-relatorio:'+ident,message['parte']),quantity=message['quantidade']))
    except legal.AppError as exc:results.append({'erro':str(exc)})
  with store.lock,store.connect() as db:store.audit(db,actor,'enviar_relatorio_mandados','mandados',ident,after={'partes':parts,'destinatario':config['destinatario']})
 return {'resultados':results}
