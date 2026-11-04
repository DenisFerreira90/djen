"""Três resumos por pedido concluído. Não usa indícios locais de mandados."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import juridico as legal


def schema(db):
 db.executescript('''CREATE TABLE IF NOT EXISTS email_digest_batches(batch_key TEXT PRIMARY KEY,criado TEXT NOT NULL,ignorado INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS email_digest_parts(batch_key TEXT,parte TEXT,delivery_id INTEGER,PRIMARY KEY(batch_key,parte));
 CREATE TABLE IF NOT EXISTS email_digest_state(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL);''')


def completed(db,details=True,pending_only=True):
 import monitoramento as monitor
 monitor.jobs_schema(db)
 batches=[]
 job_query="SELECT * FROM monitor_jobs j WHERE state!='ativo'"
 if pending_only:job_query+=" AND NOT EXISTS(SELECT 1 FROM email_digest_batches b WHERE b.batch_key='pedido:'||j.id AND b.ignorado=1) AND (SELECT COUNT(*) FROM email_digest_parts p WHERE p.batch_key='pedido:'||j.id)<3"
 for job in db.execute(job_query+' ORDER BY created,id').fetchall():
  stages=db.execute('SELECT * FROM monitor_job_courts WHERE job_id=? ORDER BY tribunal',(job['id'],)).fetchall()
  if not stages or any(s['state'] in ('aguardando','consultando') for s in stages):continue
  rows=[];ended=[]
  for s in stages:
   if s['run_id']:
    run=db.execute('SELECT * FROM monitor_runs WHERE id=?',(s['run_id'],)).fetchone()
    if run and (run['status']=='em_andamento' or not run['fim']):break
    if run:ended.append(run['fim'])
    found=[dict(r) for r in db.execute('SELECT * FROM monitor_results WHERE run_id=? ORDER BY numero',(s['run_id'],))] if details else []
   else:found=[]
   bynum={r['numero']:r for r in found}
   for n in (json.loads(s['numbers']) if details else []):
    row=bynum.get(n,{'numero':n,'status':'nao_consultado','motivo':'Etapa do tribunal: '+s['state'],'verificado':None,'detalhes':'[]'})
    row['tribunal']=s['tribunal'];rows.append(row)
  else:
   summary=json.loads(job['summary'])
   batches.append({'key':'pedido:'+job['id'],'inicio':job['created'],'fim':max(ended,default=job['created']),'status':job['state'],'itens':rows,'sem_conector':summary.get('sem_conector',[]),'contexto':summary.get('contexto',{}),'problemas':summary.get('problemas',[]),'etapas':[{'tribunal':st['tribunal'],'status':st['state']} for st in stages]})
 # Compatibilidade: consultas individuais/rotinas antigas sem pedido multitribunal.
 run_query="SELECT * FROM monitor_runs r WHERE r.fim IS NOT NULL AND r.status!='em_andamento' AND NOT EXISTS(SELECT 1 FROM monitor_job_courts s WHERE s.run_id=r.id)"
 if pending_only:run_query+=" AND NOT EXISTS(SELECT 1 FROM email_digest_batches b WHERE b.batch_key='rodada:'||r.id AND b.ignorado=1) AND (SELECT COUNT(*) FROM email_digest_parts p WHERE p.batch_key='rodada:'||r.id)<3"
 for run in db.execute(run_query+' ORDER BY r.inicio,r.id').fetchall():
  rows=[dict(r) for r in db.execute('SELECT * FROM monitor_results WHERE run_id=? ORDER BY numero',(run['id'],))] if details else []
  for row in rows:row['tribunal']=run['tribunal']
  batches.append({'key':'rodada:'+run['id'],'inicio':run['inicio'],'fim':run['fim'],'status':run['status'],'itens':rows,'sem_conector':[],'contexto':{},'problemas':[],'etapas':[{'tribunal':run['tribunal'],'status':run['status']}]})
 return batches


def initialize(db,rearm=False):
 schema(db);initialized=db.execute('SELECT version FROM email_digest_state WHERE id=1').fetchone()
 if initialized and initialized[0]>=3 and not rearm:return False
 for batch in completed(db,details=False,pending_only=False):db.execute('INSERT INTO email_digest_batches VALUES(?,?,1) ON CONFLICT(batch_key) DO UPDATE SET ignorado=1',(batch['key'],legal.now()))
 db.execute('INSERT OR REPLACE INTO email_digest_state VALUES(1,3)')
 return True


def enrich(db,batch):
    """Contato somente da planilha ou de pessoa cliente explicitamente vinculada."""
    import re
    def key(v):return ' '.join(str(v or '').casefold().split())
    clients={}
    for number in {r['numero'] for r in batch['itens']}|set(batch['sem_conector']):
        entries=[dict(c) for c in batch.get('contexto',{}).get(number,[])]
        if not entries:
            row=db.execute('SELECT data FROM monitor_watch_context WHERE numero=?',(number,)).fetchone()
            if row:entries=json.loads(row[0])
        case=db.execute("SELECT id FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
        known=[]
        if case:
            for row in db.execute("SELECT p.data FROM records t JOIN records p ON p.id=json_extract(t.data,'$.pessoa_id') AND p.kind='pessoas' WHERE t.kind='partes' AND t.case_id=?",(case[0],)):
                person=json.loads(row[0])
                if person.get('tipo')=='cliente':known.append(person)
        for person in known:
            contact=' | '.join(v for v in (('Telefone: '+str(person['telefone'])) if person.get('telefone') else '',('E-mail: '+str(person['email'])) if person.get('email') else '') if v)
            existing=next((e for e in entries if key(e.get('nome_cliente'))==key(person.get('nome'))),None)
            if existing:
                if not existing.get('contato') and contact:existing['contato']=contact;existing['origem_contato']='Cadastro de cliente vinculado ao processo'
            else:entries.append({'nome_cliente':person.get('nome',''),'contato':contact,'origem':'Cadastro de cliente vinculado ao processo'})
        clients[number]=entries
    batch['clientes']=clients
    return batch


def identity(batch,number):
    entries=batch.get('clientes',{}).get(number,[]) or batch.get('contexto',{}).get(number,[])
    if not entries:return 'Cliente: não informado\nContato: não informado'
    lines=[]
    for entry in entries:
        lines.append('Cliente: '+(entry.get('nome_cliente') or 'não informado'))
        lines.append('Contato: '+(entry.get('contato') or 'não informado'))
        if entry.get('origem'):lines.append('Fonte do nome: '+entry['origem'])
        if entry.get('origem_contato'):lines.append('Fonte do contato: '+entry['origem_contato'])
    return '\n'.join(lines)


def messages(batch):
    items=sorted(batch['itens'],key=lambda r:(r.get('tribunal',''),r['numero']))
    groups={}
    for row in items:groups.setdefault(row['status'],[]).append(row)
    changed=groups.get('atualizado',[]);quiet=groups.get('sem_atualizacao',[]);first_reads=groups.get('primeira_leitura',[])
    problems=[r for r in items if r['status'] not in ('atualizado','sem_atualizacao','primeira_leitura')]
    def date(value):
        if not value:return 'não concluída'
        try:
            dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if dt.tzinfo:dt=dt.astimezone(ZoneInfo('America/Sao_Paulo'))
            return dt.strftime('%d/%m/%Y às %H:%M:%S')
        except (ValueError,TypeError):return str(value)
    states={'encerrado':'Concluída','cancelado':'Cancelada','parcial':'Concluída parcialmente','coletado_revisar':'Concluída — confira os resultados','erro_exportacao':'Falha ao exportar os dados'}
    prefix=('ConectaAdv | Resumo da consulta\n'
            'Início: '+date(batch['inicio'])+'\n'
            'Término: '+date(batch['fim'])+'\n'
            'Situação da coleta: '+states.get(batch['status'],'Finalizada — confira os resultados')+'\n'
            'Horários de Brasília\n\n')
    def line(row):return 'Processo: '+row['numero']+' | '+row.get('tribunal','')+'\n'+identity(batch,row['numero'])+'\nConsultado em: '+date(row.get('verificado'))
    first=[prefix,'E-MAIL 2 — PROCESSOS COM ALTERAÇÕES\n','Total: '+str(len(changed))+' processo(s).\n']
    if not changed:first.append('Nenhum processo com alteração identificada nesta consulta.\nAs consultas não concluídas estão no e-mail 3.\n')
    for row in changed:
        first.append('\n'+line(row))
        changes=json.loads(row['detalhes'])
        for change in changes:
            kind=change.get('tipo')
            if kind in ('novo_evento','evento_alterado'):
                label='Novo evento' if kind=='novo_evento' else 'Alteração em evento existente'
                first.append(label+': '+str(change.get('evento',''))+'\nData/hora na origem: '+date(change.get('data'))+'\nDescrição: '+str(change.get('descricao') or 'não informada'))
                if change.get('documentos_referencias'):first.append('Referências de documentos: '+str(change['documentos_referencias']))
            elif kind=='campo':first.append('Campo alterado: '+str(change.get('campo',''))+'\nAntes: '+str(change.get('antes') or 'não informado')+'\nDepois: '+str(change.get('depois') or 'não informado'))
            elif kind=='partes':first.append('Partes/representantes: '+str(change.get('descricao','alteração identificada.')))
            elif kind=='eventos_ausentes':first.append('Eventos que deixaram de aparecer: '+', '.join(change.get('eventos',[]))+'. Conferir na origem; não presumir exclusão definitiva.')
        if not any(c.get('tipo') in ('novo_evento','evento_alterado') for c in changes):first.append('Sem novo evento confirmado: a diferença foi em outros dados comparados.')
        first.append('Acesse o processo no tribunal e confira a providência necessária.\n')
    first.append('O aviso descreve diferenças; não interpreta decisões, não calcula prazos e não compara PDFs.')
    confirmed=quiet+first_reads+changed
    second=[prefix,'E-MAIL 1 — PROCESSOS CONSULTADOS\n','Total consultado com sucesso: '+str(len(confirmed))+' processo(s).',
            'Sem alteração: '+str(len(quiet))+' | Com alteração: '+str(len(changed))+' | Primeira leitura: '+str(len(first_reads)),
            'Este é o registro das consultas. Confira as novidades e providências no e-mail 2.']
    if not confirmed:second.append('Nenhuma consulta concluída com sucesso. Confira o e-mail 3.')
    if quiet:
        second.append('\nSEM ALTERAÇÃO: '+str(len(quiet)))
        for row in quiet:second.append('\n'+line(row))
    if first_reads:
        second.append('\nPRIMEIRA LEITURA: '+str(len(first_reads)))
        second.append('Leitura inicial salva. Ainda não há uma coleta anterior para comparar; isto não confirma ausência de alteração.')
        for row in first_reads:second.append('\n'+line(row))
    if changed:
        second.append('\nCOM ALTERAÇÃO — detalhes no e-mail 2: '+str(len(changed)))
        for row in changed:second.append('\n'+line(row))
    third=[prefix,'E-MAIL 3 — FALHAS NA COLETA DO CONECTAADV\n', 'São falhas de consulta, leitura, importação ou gravação no nosso sistema e na integração com o eproc. Não indicam falha na tramitação do processo judicial.\n']
    names={'falha':'CONSULTA NÃO CONFIRMADA','nao_consultado':'PROCESSO NÃO CONSULTADO','pendente':'PENDENTE DE CONCLUSÃO'}
    for row in problems:third.append('\n'+names.get(row['status'],row['status'])+'\n'+line(row)+'\nMotivo: '+row.get('motivo','Não informado.'))
    for number in sorted(batch['sem_conector']):third.append('\nSEM CONECTOR DISPONÍVEL\nProcesso: '+number+'\n'+identity(batch,number)+'\nNão consultado; não é possível afirmar se houve movimentação.')
    for issue in batch.get('problemas',[]):third.append('\nERRO NA IMPORTAÇÃO - '+str(issue.get('aba',''))+', linha '+str(issue.get('linha',''))+'\nNúmero recebido: '+str(issue.get('valor',''))+'\nMotivo: '+str(issue.get('motivo') or 'Número inválido ou sem precisão garantida.'))
    stage_problems=[s for s in batch.get('etapas',[]) if s['status'] not in ('coletado_revisar','encerrado')]
    for stage in stage_problems:third.append('\nCOLETA NO '+stage['tribunal']+': '+states.get(stage['status'],'Não concluída')+'\nVerifique os resultados individuais e o log da coleta.')
    count=len(problems)+len(batch['sem_conector'])+len(batch.get('problemas',[]))+len(stage_problems)
    if not count:third.append('Nenhum erro, falha ou impedimento registrado nesta execução.')
    third.append('\nFalha, falta de conector ou leitura incompleta NÃO significam ausência de movimentação. Falhas do próprio envio de e-mail ficam no histórico local; um canal indisponível não pode entregar sua própria notificação.')
    short=batch['key'].split(':',1)[1][:12]
    reports=[('alteracoes','ConectaAdv 2/3 - processos com alteração: '+str(len(changed))+' | '+short,'\n'.join(first),len(changed)),('sem_diferencas','ConectaAdv 1/3 - processos consultados: '+str(len(confirmed))+' | '+short,'\n'.join(second),len(confirmed)),('erros','ConectaAdv 3/3 - falhas na coleta: '+str(count)+' | '+short,'\n'.join(third),count)]

    return [reports[1],reports[0],reports[2]]
