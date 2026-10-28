"""Fila durável por processo; URLs e hashes de sessão nunca são persistidos."""
import datetime as dt
import json
import juridico as legal


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS collection_queue(numero TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,prioridade INTEGER NOT NULL,estado TEXT NOT NULL,tentativas INTEGER NOT NULL DEFAULT 0,atualizado TEXT NOT NULL,retentar_em TEXT,resultado TEXT,nivel INTEGER NOT NULL DEFAULT 0)')

    if 'nivel' not in {r[1] for r in db.execute('PRAGMA table_info(collection_queue)')}:db.execute('ALTER TABLE collection_queue ADD COLUMN nivel INTEGER NOT NULL DEFAULT 0')


def prepare(store,found,fingerprints,mode,urgent,detailed=False):
    import gestao
    planned=[]
    for number in found:
        needed,reason=gestao.sync_plan(store,number,fingerprints.get(number,''),mode)
        planned.append((number,needed or number in urgent))
    with store.lock,store.connect() as db:
        schema(db);db.execute("UPDATE collection_queue SET estado='pendente' WHERE estado='lendo'")
        for number,needed in planned:
            row=db.execute('SELECT * FROM collection_queue WHERE numero=?',(number,)).fetchone();fingerprint=fingerprints.get(number,'');priority=10 if number in urgent else 0
            if detailed and (not row or not row['nivel']):needed=True
            if not row and needed:db.execute('INSERT INTO collection_queue(numero,fingerprint,prioridade,estado,atualizado) VALUES(?,?,?,?,?)',(number,fingerprint,priority,'pendente',legal.now()))
            elif row:
                changed=row['fingerprint']!=fingerprint
                if changed or (needed and row['estado']=='concluido'):db.execute("UPDATE collection_queue SET fingerprint=?,prioridade=?,estado='pendente',retentar_em=NULL,atualizado=? WHERE numero=?",(fingerprint,priority,legal.now(),number))
                else:db.execute('UPDATE collection_queue SET prioridade=? WHERE numero=?',(priority,number))
        rows=db.execute("SELECT * FROM collection_queue WHERE estado IN ('pendente','retentar') AND (retentar_em IS NULL OR retentar_em<=?) ORDER BY prioridade DESC,atualizado,numero",(legal.now(),)).fetchall()
        return [r['numero'] for r in rows if r['numero'] in found]


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
