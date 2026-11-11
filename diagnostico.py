"""Diagnóstico isolado: falhas desta base nunca devem impedir a operação principal."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import traceback
import uuid

BASE=Path(__file__).resolve().parent
PATH=BASE/'dados_diagnostico'/'diagnostico.sqlite3'
VERSION='51'
LOCK=threading.RLock()
FAILURE=None
STARTED=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
SECRET=re.compile(r'(?i)(senha|password|secret|token|cookie|authorization|certificado|semente|otp|2fa|payload|conteudo|html|documento|mensagem|texto)')

def now():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def mask(value):
    if isinstance(value,dict):return {str(k)[:60]:('[REDACTED]' if SECRET.search(str(k)) else mask(v)) for k,v in list(value.items())[:40]}
    if isinstance(value,(tuple,list)):return [mask(x) for x in value[:40]]
    if value is None or type(value)in (bool,int,float):return value
    text=str(value)[:4000]
    text=re.sub(r'https?://[^\s<>]+','[URL OMITIDA]',text)
    text=re.sub(r'(?i)(?:bearer\s+\S+|(?:senha|password|token|secret|cookie|authorization|otp|2fa)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+)','[CREDENCIAL OMITIDA]',text)
    text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[EMAIL]',text)
    text=re.sub(r'\b\d[\d.()/+ -]{8,}\d\b','[IDENTIFICADOR]',text)
    text=re.sub(r'\b[A-Za-z0-9_-]{24,}\b','[TOKEN]',text)
    return text

def label(value):
    return re.sub(r'[^a-zA-Z0-9_./:-]','_',str(value))[:90]

def route(value):
    # No queries, hashes, process numbers or document ids in route identifiers.
    path=str(value).split('?',1)[0]
    return '/'.join(':id' if re.search(r'\d',p) or len(p)>35 else label(p) for p in path.split('/'))[:150]

def connect():
    PATH.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    db=sqlite3.connect(PATH,timeout=.05);db.row_factory=sqlite3.Row
    try:
        os.chmod(PATH,0o600)
        db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA max_page_count=8192')
        db.executescript('''CREATE TABLE IF NOT EXISTS faults(code TEXT PRIMARY KEY,fingerprint TEXT UNIQUE,module TEXT,operation TEXT,kind TEXT,severity TEXT,first_at TEXT,last_at TEXT,total INTEGER,state TEXT,assignee INTEGER,notes TEXT,technical TEXT,actor_id INTEGER);
        CREATE INDEX IF NOT EXISTS fault_time ON faults(last_at);
        CREATE TABLE IF NOT EXISTS grants(user_id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY,at TEXT,actor_id INTEGER,code TEXT,action TEXT);
        CREATE TABLE IF NOT EXISTS backup_checks(service TEXT PRIMARY KEY,at TEXT);
        CREATE TABLE IF NOT EXISTS versions(version TEXT,service TEXT,first_seen TEXT,last_seen TEXT,PRIMARY KEY(version,service));
        ''')
        cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=30)).isoformat(timespec='seconds')
        db.execute('DELETE FROM faults WHERE last_at<?',(cutoff,));db.execute('DELETE FROM changes WHERE at<?',(cutoff,));db.commit()
        return db
    except Exception:db.close();raise

def capture(exc,module='sistema',operation='',actor_id=None,severity='erro'):
    """Allowlisted context; never exception text, source lines, locals or request body."""
    global FAILURE
    code='ERR-'+uuid.uuid4().hex[:10].upper();result={'codigo':code,'registrado':False}
    acquired=False;db=None
    try:
        acquired=LOCK.acquire(timeout=.02)
        if not acquired:return result
        frames=[];chain=[];cur=exc;seen=set()
        while cur is not None and id(cur) not in seen and len(chain)<5:
            seen.add(id(cur));kind=label(type(cur).__name__)
            trace=[{'arquivo':label(Path(f.filename).name),'funcao':label(f.name),'linha':f.lineno} for f in traceback.extract_tb(cur.__traceback__)[-30:]]
            chain.append({'tipo':kind,'frames':trace});frames.extend(trace)
            cur=cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
        technical={'excecoes':chain,'mensagem':'Conteúdo livre da exceção omitido para proteger dados e credenciais.','versao':VERSION}
        if type(getattr(exc,'errno',None))is int:technical['errno']=exc.errno
        if re.fullmatch(r'SQLITE_[A-Z_]+',str(getattr(exc,'sqlite_errorname',''))):technical['sqlite_errorname']=exc.sqlite_errorname
        module=label(module);operation=route(operation);kind=label(type(exc).__name__)
        fingerprint=hashlib.sha256(json.dumps([module,operation,kind,frames],sort_keys=True).encode()).hexdigest()
        db=connect();stamp=now();old=db.execute('SELECT code,state FROM faults WHERE fingerprint=?',(fingerprint,)).fetchone()
        if old:
            code=old['code'];db.execute("UPDATE faults SET last_at=?,total=total+1,technical=?,state=CASE WHEN state='resolvido' THEN 'novo' ELSE state END WHERE code=?",(stamp,json.dumps(technical,ensure_ascii=False),code))
        else:db.execute('INSERT INTO faults VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(code,fingerprint,module,operation,kind,'aviso' if severity=='aviso' else 'erro',stamp,stamp,1,'novo',None,'',json.dumps(technical,ensure_ascii=False),actor_id if type(actor_id)is int else None))
        cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=30)).isoformat(timespec='seconds')
        db.execute('DELETE FROM faults WHERE last_at<?',(cutoff,));db.execute('DELETE FROM faults WHERE code IN (SELECT code FROM faults ORDER BY last_at DESC LIMIT -1 OFFSET 1000)')
        db.execute('DELETE FROM changes WHERE id IN (SELECT id FROM changes ORDER BY id DESC LIMIT -1 OFFSET 3000)');db.commit()
        FAILURE=None;return {'codigo':code,'registrado':True}
    except Exception:
        FAILURE=now();return result
    finally:
        if db is not None:db.close()
        if acquired:LOCK.release()

def owner(store):
    import chat_recursos
    with store.lock,store.connect() as db:return chat_recursos.owner(db)

def permission(store,actor):
    if actor['id']==owner(store):return {'permitido':True,'proprietario':True}
    try:
        with connect() as db:allowed=bool(db.execute('SELECT 1 FROM grants WHERE user_id=?',(actor['id'],)).fetchone())
    except Exception:allowed=False
    return {'permitido':allowed,'proprietario':False}

def require(store,actor):
    import juridico as legal
    caps=permission(store,actor)
    if not caps['permitido']:raise legal.AppError('Diagnóstico restrito ao proprietário e à TI autorizada.',403)
    return caps

def grants(store,actor,body=None):
    import juridico as legal
    if actor['id']!=owner(store):raise legal.AppError('Só o proprietário concede acesso técnico.',403)
    with store.lock,store.connect() as source:
        users=[dict(r) for r in source.execute('SELECT id,nome,ativo FROM users')]
    with connect() as db:
        if body is not None:
            uid=body.get('user_id');enabled=body.get('permitido')
            if type(uid)is not int or type(enabled)is not bool or not any(u['id']==uid and u['ativo'] for u in users) or uid==actor['id']:raise legal.AppError('Permissão inválida.')
            if enabled:db.execute('INSERT OR IGNORE INTO grants VALUES(?)',(uid,))
            else:db.execute('DELETE FROM grants WHERE user_id=?',(uid,))
            db.execute('INSERT INTO changes(at,actor_id,code,action) VALUES(?,?,?,?)',(now(),actor['id'],str(uid),'conceder_acesso' if enabled else 'retirar_acesso'))
        ids={r[0] for r in db.execute('SELECT user_id FROM grants')}
        return {'usuarios':[{**u,'permitido':u['id']==actor['id'] or u['id'] in ids} for u in users]}

def faults(store,actor,filters=None,code=None,body=None):
    import juridico as legal
    require(store,actor);filters=filters or {}
    with connect() as db:
        if code:
            row=db.execute('SELECT * FROM faults WHERE code=?',(code,)).fetchone()
            if not row:raise legal.AppError('Registro não encontrado ou fora da retenção.',404)
            if body is not None:
                state=body.get('situacao');uid=body.get('responsavel_id');notes=str(body.get('observacoes',''))
                if state not in ('novo','investigando','resolvido') or len(notes)>2000:raise legal.AppError('Situação ou observação inválida.')
                if uid is not None:
                    if type(uid)is not int:raise legal.AppError('Responsável inválido.')
                    with store.connect() as src:
                        u=src.execute('SELECT id FROM users WHERE id=? AND ativo=1',(uid,)).fetchone()
                    if not u:raise legal.AppError('Responsável inválido.')
                db.execute('UPDATE faults SET state=?,assignee=?,notes=? WHERE code=?',(state,uid,mask(notes),code))
                db.execute('INSERT INTO changes(at,actor_id,code,action) VALUES(?,?,?,?)',(now(),actor['id'],code,'situacao_'+state))
                row=db.execute('SELECT * FROM faults WHERE code=?',(code,)).fetchone()
            db.execute('INSERT INTO changes(at,actor_id,code,action) VALUES(?,?,?,?)',(now(),actor['id'],code,'consultar_detalhe'))
            d=dict(row);d.pop('fingerprint');d['technical']=json.loads(d['technical']);return d
        query='SELECT code,module,operation,kind,severity,first_at,last_at,total,state,assignee FROM faults WHERE 1=1';args=[]
        for key,col in [('modulo','module'),('situacao','state')]:
            if filters.get(key):query+=' AND '+col+'=?';args.append(str(filters[key])[:90])
        if filters.get('busca'):query+=' AND (instr(code,?)>0 OR instr(kind,?)>0)';args.extend([str(filters['busca'])[:90]]*2)
        for key,op in [('inicio','>='),('fim','<=')]:
            if filters.get(key):
                try:dt.date.fromisoformat(filters[key])
                except ValueError:raise legal.AppError('Data inválida.')
                query+=' AND substr(last_at,1,10)'+op+'?';args.append(filters[key])
        rows=db.execute(query+' ORDER BY last_at DESC LIMIT 201',args).fetchall()
        return {'itens':[dict(r) for r in rows[:200]],'tem_mais':len(rows)>200,'retencao_dias':30}

def backup_confirmed(service):
    try:
        with connect() as db:db.execute('INSERT OR REPLACE INTO backup_checks VALUES(?,?)',(label(service),now()))
    except Exception:pass

def health(store,actor,chat_independent=False,chat_external=False):
    require(store,actor)
    import juridico as legal
    services=[]
    def probe(name,path):
        path=Path(path)
        if not path.is_file():return {'servico':name,'estado':'nao_configurado','checado_em':now()}
        try:
            db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)
            try:db.execute('SELECT count(*) FROM sqlite_master').fetchone()
            finally:db.close()
            return {'servico':name,'estado':'acessivel','tamanho_bytes':path.stat().st_size,'checado_em':now()}
        except Exception:return {'servico':name,'estado':'indisponivel','checado_em':now()}
    services.append(probe('chat' if chat_independent else 'principal',store.path))
    if not chat_independent:
        import chat_servico
        if chat_external:services.append({**probe('banco_chat',chat_servico.CHAT_PATH),'observacao':'Acesso ao banco não confirma que o servidor da porta 8766 esteja ativo.'})
        else:services.append({'servico':'chat','estado':'compartilha_principal','checado_em':now()})
        services.append(probe('jusdown',BASE/'dados_jusdown'/'jusdown.sqlite3'))
        import sys
        collector=sys.modules.get('eproc')
        instance=getattr(collector,'collector',None)
        if instance:
            current=getattr(instance,'current',None) or {}
            services.append({'servico':'coletor','estado':label(current.get('estado','ocioso')),'lidos':current.get('lidos',0),'checado_em':now(),'observacao':'Executa no processo principal; não é um serviço independente.'})
        else:services.append({'servico':'coletor','estado':'nao_inicializado','checado_em':now()})
    try:
        with connect() as db:
            service='chat' if chat_independent else 'principal'
            db.execute('INSERT OR IGNORE INTO versions VALUES(?,?,?,?)',(VERSION,service,now(),now()));db.execute('UPDATE versions SET last_seen=? WHERE version=? AND service=?',(now(),VERSION,service))
            versions=[dict(r) for r in db.execute('SELECT * FROM versions ORDER BY first_seen DESC LIMIT 20')]
            counts={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM faults GROUP BY state')}
            backups=[dict(r) for r in db.execute('SELECT service,at FROM backup_checks')]
        diag='acessivel'
    except Exception:diag='indisponivel';counts={};backups=[];versions=[]
    services.append({'servico':'diagnostico','estado':diag,'checado_em':now()})
    disk=shutil.disk_usage(BASE)
    return {'versao':VERSION,'versoes_observadas':versions,'inicio_servidor':STARTED,'checado_em':now(),'servicos':services,'erros':counts,'disco_livre_bytes':disk.free,'backups_confirmados_nesta_versao':backups,'ultima_falha_diagnostico':FAILURE,'observacao':'Sondagens locais. Não comprovam disponibilidade dos tribunais, integridade completa dos bancos ou execução de servidores externos.'}
