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
            history=[dict(r) for r in db.execute('SELECT * FROM email_delivery ORDER BY id DESC LIMIT 20')]
        return {'disponivel':available,'configurado':bool(c),'remetente':c.get('remetente',DEFAULT),'destinatario':c.get('destinatario',DEFAULT),'automatico':c.get('automatico',False),'historico':history}


def save(store,actor,body):
    admin(actor)
    with LOCK:
        previous=load(store)
        sender=str(body.get('remetente','')).strip().lower();recipient=str(body.get('destinatario','')).strip().lower()
        if not re.fullmatch(r'[a-z0-9._%+\-]+@gmail\.com',sender):raise legal.AppError('Informe um remetente Gmail pessoal válido.')
        if not re.fullmatch(r'[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}',recipient):raise legal.AppError('Destinatário inválido.')
        password=str(body.get('senha_app','')).replace(' ','') or previous.get('senha','')
        if not re.fullmatch('[a-zA-Z0-9]{16}',password):raise legal.AppError('Informe a senha de app de 16 caracteres gerada pelo Google.')
        automatic=body.get('automatico') is True
        with store.lock,store.connect() as db:
            import mandados;mandados.schema(db);schema(db)
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


def deliver(store,config,subject,text,kind,ids=()):
    with store.lock,store.connect() as db:
        schema(db)
        cur=db.execute('INSERT INTO email_delivery(criado,tipo,status,quantidade,erro) VALUES(?,?,?,?,?)',(legal.now(),kind,'enviando',len(ids),''));ident=cur.lastrowid
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


def process(store):
    with LOCK:
        try:c=load(store)
        except legal.AppError:return
        if not c.get('automatico'):return
        with store.lock,store.connect() as db:
            import mandados;mandados.schema(db);schema(db)
            # Interrupção depois de aceitar SMTP é ambígua: manter os itens vinculados evita duplicação.
            scope=(db.execute("SELECT valor FROM mandate_state WHERE chave='somente_lista'").fetchone() or ['0'])[0]=='1'
            query='SELECT a.* FROM mandate_alerts a WHERE a.id>? AND a.revisado IS NULL AND NOT EXISTS(SELECT 1 FROM email_alert_items i WHERE i.alert_id=a.id)'
            if scope:query+=' AND a.numero IN (SELECT numero FROM mandate_watchlist)'
            rows=db.execute(query+' ORDER BY a.id LIMIT 20',(c['inicio_alerta'],)).fetchall()
        if not rows:return
        text='Indícios para revisão jurídica. Confira os documentos no tribunal.\n\n'+'\n\n'.join('Processo: '+r['numero']+'\nEvento: '+r['evento']+'\nCategoria: '+r['categoria'] for r in rows)
        deliver(store,c,'ConectaAdv — novos alertas para revisão',text,'alertas',[r['id'] for r in rows])
