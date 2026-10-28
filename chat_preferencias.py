"""Preferências privadas por usuário e presença com expiração; não monitora o computador."""
import base64
import datetime as dt
import json
import re
import juridico as legal

DEFAULT={'tema':'sistema','ocultar_historico':False,'ocultar_bolha':False,'fixar_painel':False,'largura':420,'altura':640,'estado':'automatico','som_notificacoes':False,'notificacoes_desktop':False,'recolher_auto':True,'mostrar_previas':True,'mostrar_confirmacoes':True,'mostrar_horarios':True}
STATES={'automatico','online','ausente','ocupado','reuniao','telefone','invisivel'}

def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS chat_preferences(user_id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_pins(user_id INTEGER,room_id INTEGER,PRIMARY KEY(user_id,room_id));
    CREATE TABLE IF NOT EXISTS chat_presence(user_id INTEGER,device_id TEXT,ultima_atividade TEXT,ultimo_sinal TEXT,PRIMARY KEY(user_id,device_id));
    CREATE TABLE IF NOT EXISTS chat_avatars(user_id INTEGER PRIMARY KEY,mime TEXT NOT NULL,conteudo BLOB NOT NULL,atualizado TEXT NOT NULL);''')


def get_db(db,uid):
    row=db.execute('SELECT payload FROM chat_preferences WHERE user_id=?',(uid,)).fetchone()
    return {**DEFAULT,**(json.loads(row[0]) if row else {})}


def get(store,actor):
    with store.lock,store.connect() as db:
        schema(db);p=get_db(db,actor['id']);photo=db.execute('SELECT atualizado FROM chat_avatars WHERE user_id=?',(actor['id'],)).fetchone();p['foto_atualizada']=photo[0] if photo else None
        import chat_visualizacao as visual
        visual.schema(db);p['recursos']=visual.effective(db,actor['id']);p['limites']=visual.allowed(db,actor['id']);return p


def save(store,actor,body):
    if not isinstance(body,dict) or set(body)-set(DEFAULT):raise legal.AppError('Preferência inválida.')
    with store.lock,store.connect() as db:
        schema(db);p={**get_db(db,actor['id']),**body}
        if p['tema'] not in ('sistema','escuro') or p['estado'] not in STATES:raise legal.AppError('Tema ou presença inválidos.')
        if type(p['largura'])is not int or not 320<=p['largura']<=900:raise legal.AppError('A largura deve estar entre 320 e 900 pixels.')
        if type(p['altura'])is not int or not 320<=p['altura']<=1200:raise legal.AppError('Altura inválida.')
        if any(type(p[k])is not bool for k in ('ocultar_historico','ocultar_bolha','fixar_painel','som_notificacoes','notificacoes_desktop','recolher_auto','mostrar_previas','mostrar_confirmacoes','mostrar_horarios')):raise legal.AppError('Opção de privacidade inválida.')
        db.execute('INSERT OR REPLACE INTO chat_preferences VALUES(?,?)',(actor['id'],legal.dumps(p)))
        store.audit(db,actor,'alterar_preferencias_chat','chat_usuario',actor['id'],after=body)
    return get(store,actor)


def pin(store,actor,rid,enabled):
    import chat_interno
    with store.lock,store.connect() as db:
        schema(db);chat_interno.schema(db)
        if not db.execute('SELECT 1 FROM chat_members WHERE room_id=? AND user_id=?',(rid,actor['id'])).fetchone():raise legal.AppError('Você não participa desta conversa.',403)
        if enabled:db.execute('INSERT OR IGNORE INTO chat_pins VALUES(?,?)',(actor['id'],rid))
        else:db.execute('DELETE FROM chat_pins WHERE user_id=? AND room_id=?',(actor['id'],rid))
    return {'ok':True}


def heartbeat(store,actor,body):
    device=str(body.get('dispositivo',''));idle=body.get('ocioso_segundos',0)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',device) or type(idle)is not int or not 0<=idle<=86400:raise legal.AppError('Sinal de presença inválido.')
    now=dt.datetime.fromisoformat(legal.now());active=(now-dt.timedelta(seconds=idle)).isoformat(timespec='seconds')
    with store.lock,store.connect() as db:
        schema(db);db.execute('DELETE FROM chat_presence WHERE ultimo_sinal<?',((now-dt.timedelta(days=1)).isoformat(timespec='seconds'),))
        db.execute('INSERT OR REPLACE INTO chat_presence VALUES(?,?,?,?)',(actor['id'],device,active,legal.now()))
    return {'ok':True}


def status_db(db,uid):
    p=get_db(db,uid)
    if p['estado']=='invisivel':return 'offline'
    now=dt.datetime.fromisoformat(legal.now());cutoff=(now-dt.timedelta(seconds=90)).isoformat(timespec='seconds')
    rows=db.execute('SELECT ultima_atividade FROM chat_presence WHERE user_id=? AND ultimo_sinal>=?',(uid,cutoff)).fetchall()
    if not rows:return 'offline'
    if p['estado']!='automatico':return p['estado']
    return 'online' if any((now-dt.datetime.fromisoformat(r[0])).total_seconds()<300 for r in rows) else 'ausente'


def avatar_save(store,actor,body):
    if body.get('remover') is True:
        with store.lock,store.connect() as db:schema(db);db.execute('DELETE FROM chat_avatars WHERE user_id=?',(actor['id'],))
        return {'ok':True}
    try:data=base64.b64decode(body.get('base64',''),validate=True)
    except (ValueError,TypeError):raise legal.AppError('Foto inválida.')
    if not data or len(data)>1024*1024:raise legal.AppError('A foto deve ter até 1 MB.')
    if data.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
    elif data.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
    elif data[:4]==b'RIFF' and data[8:12]==b'WEBP':mime='image/webp'
    else:raise legal.AppError('Use PNG, JPG ou WebP.')
    with store.lock,store.connect() as db:
        schema(db);db.execute('INSERT OR REPLACE INTO chat_avatars VALUES(?,?,?,?)',(actor['id'],mime,data,legal.now()));store.audit(db,actor,'alterar_foto_chat','chat_usuario',actor['id'])
    return {'ok':True}


def avatar(store,uid):
    with store.lock,store.connect() as db:
        schema(db);r=db.execute('SELECT a.* FROM chat_avatars a JOIN users u ON u.id=a.user_id WHERE a.user_id=? AND u.ativo=1',(uid,)).fetchone()
        if not r:raise legal.AppError('Foto não encontrada.',404)
        return dict(r)


def offline(store,actor,device):
    if not isinstance(device,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',device):return
    with store.lock,store.connect() as db:schema(db);db.execute('DELETE FROM chat_presence WHERE user_id=? AND device_id=?',(actor['id'],device))
