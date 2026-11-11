"""Fila durável por processo; URLs e hashes de sessão nunca são persistidos."""
import datetime as dt
import json
import juridico as legal


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS collection_queue(numero TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,prioridade INTEGER NOT NULL,estado TEXT NOT NULL,tentativas INTEGER NOT NULL DEFAULT 0,atualizado TEXT NOT NULL,retentar_em TEXT,resultado TEXT,nivel INTEGER NOT NULL DEFAULT 0)')

    if 'nivel' not in {r[1] for r in db.execute('PRAGMA table_info(collection_queue)')}:db.execute('ALTER TABLE collection_queue ADD COLUMN nivel INTEGER NOT NULL DEFAULT 0')


def prepare(store,found,fingerprints,mode,urgent,detailed=False,selection=None):
    import gestao
    planned=[]
    for number in found:
        needed,reason=gestao.sync_plan(store,number,fingerprints.get(number,''),mode)
        planned.append((number,needed if mode=='pendentes' else needed or number in urgent,reason))
    with store.lock,store.connect() as db:
        schema(db);db.execute("UPDATE collection_queue SET estado='pendente' WHERE estado='lendo'")
        for number,needed,reason in planned:
            row=db.execute('SELECT * FROM collection_queue WHERE numero=?',(number,)).fetchone();fingerprint=fingerprints.get(number,'');priority=10 if number in urgent else 0
            if detailed and (not row or not row['nivel']) and mode!='pendentes':needed=True
            if mode=='pendentes' and not needed:
                if row:db.execute("UPDATE collection_queue SET estado='concluido',retentar_em=NULL,prioridade=? WHERE numero=?",(priority,number))
                continue
            if not row and needed:db.execute('INSERT INTO collection_queue(numero,fingerprint,prioridade,estado,atualizado) VALUES(?,?,?,?,?)',(number,fingerprint,priority,'pendente',legal.now()))
            elif row:
                changed=row['fingerprint']!=fingerprint
                if mode in ('completa','pendentes') or changed or (needed and row['estado']=='concluido'):db.execute("UPDATE collection_queue SET fingerprint=?,prioridade=?,estado='pendente',retentar_em=NULL,atualizado=? WHERE numero=?",(fingerprint,priority,legal.now(),number))
                else:db.execute('UPDATE collection_queue SET prioridade=? WHERE numero=?',(priority,number))
        rows=db.execute("SELECT * FROM collection_queue WHERE estado IN ('pendente','retentar') AND (retentar_em IS NULL OR retentar_em<=?) ORDER BY prioridade DESC,atualizado,numero",(legal.now(),)).fetchall()
        order=[r['numero'] for r in rows if r['numero'] in found]
        if selection is not None:
            selected=set(order);states={r['numero']:dict(r) for r in db.execute('SELECT * FROM collection_queue')}
            details=[];counts={'selecionados':0,'dispensados_incremental':0,'aguardando_retentativa':0,'fora_da_fila':0}
            for number,needed,reason in planned:
                row=states.get(number)
                if number in selected:decision='selecionados'
                elif row and row['estado']=='retentar' and row['retentar_em'] and row['retentar_em']>legal.now():decision='aguardando_retentativa'
                elif not needed:decision='dispensados_incremental'
                else:decision='fora_da_fila'
                counts[decision]+=1
                details.append({'numero':number,'decisao':decision,'motivo':reason,'estado_fila':row['estado'] if row else None,'retentar_em':row['retentar_em'] if row else None})
            selection.update(total_encontrados=len(planned),**counts,processos=details)
        return order


def claim(store,number):
    with store.lock,store.connect() as db:
        schema(db);db.execute("UPDATE collection_queue SET estado='lendo',tentativas=tentativas+1,atualizado=? WHERE numero=?",(legal.now(),number))


def finish(store,number,record):
    imported=record.get('gravado_no_sistema') is True
    supplements=(record.get('detalhes') or {}).get('complementos',[])
    complete=imported and (record.get('detalhes') or {}).get('cobertura_eventos',{}).get('completo',True) and not any(c.get('situacao')=='falha_na_leitura' for c in supplements)
    retry=None if complete else (dt.datetime.fromisoformat(legal.now())+dt.timedelta(minutes=30)).isoformat(timespec='seconds')
    with store.lock,store.connect() as db:
        schema(db);db.execute('UPDATE collection_queue SET estado=?,atualizado=?,retentar_em=?,resultado=?,nivel=MAX(nivel,?) WHERE numero=?',('concluido' if complete else 'retentar',legal.now(),retry,'importado' if complete else 'leitura_ou_gravacao_pendente',int(complete and len(supplements)>1),number))


def pending(store,number):
    with store.lock,store.connect() as db:
        schema(db);r=db.execute('SELECT estado FROM collection_queue WHERE numero=?',(number,)).fetchone();return bool(r and r[0]!='concluido')


def status(store,actor):
    if actor['role']!='administrador':raise legal.AppError('Fila restrita ao administrador.',403)
    with store.lock,store.connect() as db:
        schema(db)
        return {'contagens':dict(db.execute('SELECT estado,COUNT(*) FROM collection_queue GROUP BY estado')),'pendencias':[dict(r) for r in db.execute("SELECT numero,estado,tentativas,atualizado,retentar_em,resultado FROM collection_queue WHERE estado!='concluido' ORDER BY prioridade DESC,atualizado LIMIT 100")],'cobertura':'Fila apenas dos processos encontrados na listagem consultada. Ausentes não são concluídos nem excluídos.'}
