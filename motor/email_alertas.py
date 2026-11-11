"""Gmail SMTP com segredo protegido pelo usuário do Windows e fila persistente."""
import base64
import ctypes
import hashlib
import json
import os
import re
import smtplib
import ssl
import threading
from email.message import EmailMessage
from pathlib import Path
import juridico as legal

LOCK=threading.RLock()
DEFAULT='denis.da.rosa.ferreira@gmail.com'


def admin(actor):
    if actor['role']!='administrador':raise legal.AppError('Somente administradores configuram e enviam e-mails.',403)


def crypt(data,decrypt=False):
    if os.name!='nt':raise legal.AppError('A proteção da senha de app requer Windows nesta versão.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]
    buf=ctypes.create_string_buffer(data);src=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_byte)));out=Blob()
    api=ctypes.WinDLL('crypt32',use_last_error=True)
    name='CryptUnprotectData' if decrypt else 'CryptProtectData'
    fn=getattr(api,name)
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(src),None,None,None,None,1,ctypes.byref(out)):raise legal.AppError('Não foi possível proteger ou abrir a credencial deste usuário Windows.')
    kernel=ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    try:return ctypes.string_at(out.data,out.size)
    finally:kernel.LocalFree(out.data)


def config_path(store):
    if os.name!='nt':raise legal.AppError('Configure o Gmail no computador Windows que executa o ConectaAdv.')
    key=hashlib.sha256(str(store.path.resolve()).encode()).hexdigest()[:20]
    return Path(os.environ['LOCALAPPDATA'])/'ConectaAdv'/'credenciais'/('gmail-'+key+'.bin')


def load(store):
    p=config_path(store)
    return json.loads(crypt(p.read_bytes(),True)) if p.exists() else {}


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS email_delivery(id INTEGER PRIMARY KEY,criado TEXT,tipo TEXT,status TEXT,quantidade INTEGER,erro TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS email_alert_items(alert_id INTEGER PRIMARY KEY,delivery_id INTEGER)')


def status(store,actor):
    admin(actor)
    with LOCK:
        try:c=load(store);available=True
        except legal.AppError:c={};available=False
        with store.lock,store.connect() as db:
            schema(db)
            import email_resumos;email_resumos.schema(db)
            history=[dict(r) for r in db.execute('SELECT * FROM email_delivery ORDER BY id DESC LIMIT 20')]
        return {'disponivel':available,'configurado':bool(c),'remetente':c.get('remetente',DEFAULT),'destinatario':c.get('destinatario',DEFAULT),'automatico':False,'revisao_manual':True,'formato_alertas':'tres_resumos_por_pedido','historico':history}


def save(store,actor,body):
    admin(actor)
    with LOCK:
        previous=load(store)
        sender=str(body.get('remetente','')).strip().lower();recipient=str(body.get('destinatario','')).strip().lower()
        if not re.fullmatch(r'[a-z0-9._%+\-]+@gmail\.com',sender):raise legal.AppError('Informe um remetente Gmail pessoal válido.')
        if not re.fullmatch(r'[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}',recipient):raise legal.AppError('Destinatário inválido.')
        password=str(body.get('senha_app','')).replace(' ','') or previous.get('senha','')
        if not re.fullmatch('[a-zA-Z0-9]{16}',password):raise legal.AppError('Informe a senha de app de 16 caracteres gerada pelo Google.')
        automatic=False if review_required(store) else body.get('automatico') is True
        with store.lock,store.connect() as db:
            import mandados;mandados.schema(db);schema(db)
            import email_resumos
            email_resumos.initialize(db,rearm=automatic and not previous.get('automatico'))
            floor=previous.get('inicio_alerta',0) if previous.get('automatico') and automatic else db.execute('SELECT COALESCE(MAX(id),0) FROM mandate_alerts').fetchone()[0]
        c={'remetente':sender,'destinatario':recipient,'senha':password,'automatico':automatic,'inicio_alerta':floor}
        p=config_path(store);p.parent.mkdir(parents=True,exist_ok=True)
        temp=p.with_suffix('.tmp');temp.write_bytes(crypt(json.dumps(c).encode()));os.replace(temp,p)
        with store.lock,store.connect() as db:store.audit(db,actor,'configurar_email','email',after={'remetente':sender,'destinatario':recipient,'automatico':automatic})
    return status(store,actor)


def smtp_send(config,subject,text):
    msg=EmailMessage();msg['From']=config['remetente'];msg['To']=config['destinatario'];msg['Subject']=subject;msg.set_content(text)
    with smtplib.SMTP_SSL('smtp.gmail.com',465,timeout=25,context=ssl.create_default_context()) as smtp:
        smtp.login(config['remetente'],config['senha'])
        if smtp.send_message(msg):raise smtplib.SMTPRecipientsRefused({})


def deliver(store,config,subject,text,kind,ids=(),digest=None,quantity=None):
    with store.lock,store.connect() as db:
        schema(db)
        if digest:
            import email_resumos;email_resumos.schema(db)
            if db.execute('SELECT 1 FROM email_digest_parts WHERE batch_key=? AND parte=?',digest).fetchone():return {'mensagem':'Resumo já reservado; não será repetido.'}
        cur=db.execute('INSERT INTO email_delivery(criado,tipo,status,quantidade,erro) VALUES(?,?,?,?,?)',(legal.now(),kind,'enviando',len(ids) if quantity is None else quantity,''));ident=cur.lastrowid
        if digest:db.execute('INSERT INTO email_digest_parts VALUES(?,?,?)',(*digest,ident))
        db.executemany('INSERT INTO email_alert_items VALUES(?,?)',[(i,ident) for i in ids])
    state='aceito_smtp';error=''
    try:smtp_send(config,subject,text)
    except smtplib.SMTPAuthenticationError:state='falha';error='Gmail recusou a autenticação. Confira a senha de app.'
    except Exception:state='incerto';error='Envio não confirmado. Confira Enviados antes de tentar novamente; não haverá repetição automática.'
    with store.lock,store.connect() as db:db.execute('UPDATE email_delivery SET status=?,erro=? WHERE id=?',(state,error,ident))
    if state!='aceito_smtp':raise legal.AppError(error)
    return {'mensagem':'Mensagem aceita pelo Gmail. Confira a caixa de entrada e o spam; aceitação SMTP não confirma entrega.'}


def test(store,actor):
    admin(actor)
    with LOCK:
        c=load(store)
        if not c:raise legal.AppError('Salve a configuração antes de enviar o teste.')
        result=deliver(store,c,'ConectaAdv — teste de e-mail','Mensagem de teste do ConectaAdv. Nenhuma ocorrência judicial real.\nData: '+legal.now(),'teste')
        with store.lock,store.connect() as db:store.audit(db,actor,'enviar_teste_email','email')
        return result


def prepare(store):
    """Inicializa a política antes de aceitar novas consultas; não envia mensagens."""
    import email_resumos
    if review_required(store):return
    with LOCK:
        try:c=load(store)
        except legal.AppError:return
        if not c.get('automatico'):return
        with store.lock,store.connect() as db:
            schema(db);email_resumos.initialize(db)


def process(store):
    """Envia três resumos de execução, nunca lotes de indícios de mandados."""
    import email_resumos
    if review_required(store):return
    with LOCK:
        try:c=load(store)
        except legal.AppError:return
        if not c.get('automatico'):return
        with store.lock,store.connect() as db:
            schema(db)
            if email_resumos.initialize(db):return
            # Reserva antiga em "enviando" pode ter sido aceita pelo SMTP antes de uma queda.
            db.execute("UPDATE email_delivery SET status='incerto',erro='Servidor interrompido durante o envio. Confira Enviados; não haverá repetição automática.' WHERE status='enviando' AND id IN(SELECT delivery_id FROM email_digest_parts)")
            batches=email_resumos.completed(db)
            batch=next((b for b in batches if not db.execute('SELECT 1 FROM email_digest_batches WHERE batch_key=? AND ignorado=1',(b['key'],)).fetchone() and db.execute('SELECT COUNT(*) FROM email_digest_parts WHERE batch_key=?',(b['key'],)).fetchone()[0]<3),None)
            if not batch:return
            db.execute('INSERT OR IGNORE INTO email_digest_batches VALUES(?,?,0)',(batch['key'],legal.now()))
            batch=email_resumos.enrich(db,batch)
        errors=[]
        for part,subject,text,count in email_resumos.messages(batch):
            try:deliver(store,c,subject,text,'resumo_'+part,digest=(batch['key'],part),quantity=count)
            except legal.AppError as exc:errors.append(str(exc))
        if errors:raise legal.AppError(' '.join(dict.fromkeys(errors)))


def review_required(store):
    # Revisão manual é obrigatória nesta versão, mesmo com configuração antiga automática.
    return True


def drafts(store,actor):
    admin(actor)
    import email_resumos
    with LOCK,store.lock,store.connect() as db:
        schema(db);email_resumos.schema(db)
        db.execute('CREATE TABLE IF NOT EXISTS email_review_drafts(batch_key TEXT PRIMARY KEY,criado TEXT NOT NULL,conteudo TEXT NOT NULL)')
        batches=email_resumos.completed(db,pending_only=False)
        for batch in sorted(batches,key=lambda b:b['inicio'],reverse=True)[:20]:
            if db.execute('SELECT 1 FROM email_review_drafts WHERE batch_key=?',(batch['key'],)).fetchone():continue
            batch=email_resumos.enrich(db,batch)
            messages=[{'parte':p,'assunto':s,'texto':t,'quantidade':n} for p,s,t,n in email_resumos.messages(batch)]
            db.execute('INSERT INTO email_review_drafts VALUES(?,?,?)',(batch['key'],legal.now(),legal.dumps(messages)))
        rows=db.execute('SELECT * FROM email_review_drafts ORDER BY criado DESC,rowid DESC LIMIT 20').fetchall()
        output=[]
        for row in rows:
            parts=json.loads(row['conteudo'])
            for part in parts:
                sent=db.execute('SELECT d.status FROM email_digest_parts p JOIN email_delivery d ON d.id=p.delivery_id WHERE p.batch_key=? AND p.parte=?',(row['batch_key'],part['parte'])).fetchone()
                part['envio']=sent[0] if sent else 'nao_enviado'
            output.append({'id':row['batch_key'],'criado':row['criado'],'resumos':parts})
        return {'itens':output,'modo':'revisao_manual'}


def send_selected(store,actor,body):
    admin(actor)
    parts=body.get('partes');key=body.get('id')
    if not isinstance(key,str) or not isinstance(parts,list) or not parts or len(parts)>3 or len(set(str(p) for p in parts))!=len(parts) or any(p not in ('alteracoes','sem_diferencas','erros') for p in parts):raise legal.AppError('Selecione de um a três resumos válidos.')
    with LOCK:
        c=load(store)
        if not c:raise legal.AppError('Salve o remetente, destinatário e senha de app em Canais de aviso.')
        if body.get('destinatario')!=c['destinatario'] or body.get('remetente')!=c['remetente']:raise legal.AppError('A configuração de envio mudou. Reabra a prévia antes de enviar.',409)
        with store.lock,store.connect() as db:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='email_review_drafts'").fetchone()
            row=db.execute('SELECT conteudo FROM email_review_drafts WHERE batch_key=?',(key,)).fetchone() if exists else None
            if not row:raise legal.AppError('Abra a prévia do pedido antes de enviar.',404)
            messages=json.loads(row[0])
        results=[]
        for message in messages:
            if message['parte'] not in parts:continue
            try:
                result=deliver(store,c,message['assunto'],message['texto'],'resumo_'+message['parte'],digest=(key,message['parte']),quantity=message['quantidade'])
                results.append({'parte':message['parte'],**result})
            except legal.AppError as exc:results.append({'parte':message['parte'],'erro':str(exc)})
        with store.lock,store.connect() as db:store.audit(db,actor,'enviar_resumos_selecionados','email',after={'pedido':key,'partes':parts,'destinatario':c['destinatario']})
        return {'resultados':results}
