"""Mensageria corporativa local; acesso a histórico administrativo sempre auditado."""
import base64
import hashlib
import json
import re
import uuid
import juridico as legal
import chat_recursos as features
import chat_visualizacao as visual
import chat_escritorio as office

MAX_FILE=10*1024*1024

def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS chat_profiles(user_id INTEGER PRIMARY KEY,ramal TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS chat_rooms(id INTEGER PRIMARY KEY,titulo TEXT NOT NULL,tipo TEXT NOT NULL,owner_id INTEGER,criado TEXT NOT NULL,direct_key TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS chat_members(room_id INTEGER,user_id INTEGER,last_read INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(room_id,user_id));
    CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY,room_id INTEGER NOT NULL,sender_id INTEGER NOT NULL,texto TEXT NOT NULL,criado TEXT NOT NULL,nonce TEXT NOT NULL,UNIQUE(sender_id,nonce));
    CREATE INDEX IF NOT EXISTS chat_message_room ON chat_messages(room_id,id);
    CREATE TABLE IF NOT EXISTS chat_files(id TEXT PRIMARY KEY,message_id INTEGER NOT NULL,nome TEXT NOT NULL,mime TEXT NOT NULL,tipo TEXT NOT NULL,tamanho INTEGER NOT NULL,sha256 TEXT NOT NULL,conteudo BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS chat_file_message ON chat_files(message_id);
    ''')
    visual.schema(db)
    office.schema(db)


def editor(actor):
    if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)


def access(store,db,actor,rid,reason='',action='consultar_chat'):
    room=db.execute('SELECT * FROM chat_rooms WHERE id=?',(rid,)).fetchone()
    if not room:raise legal.AppError('Conversa não encontrada.',404)
    member=db.execute('SELECT 1 FROM chat_members WHERE room_id=? AND user_id=?',(rid,actor['id'])).fetchone()
    if member:return dict(room)
    if actor['id']!=features.owner(db):raise legal.AppError('Você não participa desta conversa.',403)
    if len(str(reason).strip())<5:raise legal.AppError('Informe o motivo da consulta administrativa ao histórico.',403)
    store.audit(db,actor,action,'chat',rid,after={'motivo':str(reason)[:500]})
    return dict(room)


def users(store):
    with store.lock,store.connect() as db:
        schema(db)
        import chat_preferencias as prefs
        prefs.schema(db);result=[]
        for row in db.execute("SELECT u.id,u.nome,u.role,COALESCE(p.ramal,'') AS ramal FROM users u LEFT JOIN chat_profiles p ON p.user_id=u.id WHERE u.ativo=1 ORDER BY u.nome").fetchall():
            r=dict(row);r.update(office.user_info(db,r['id']));r['presenca']=prefs.status_db(db,r['id']);photo=db.execute('SELECT atualizado FROM chat_avatars WHERE user_id=?',(r['id'],)).fetchone();r['foto_atualizada']=photo[0] if photo else None;result.append(r)
        return result


def profile(store,actor,uid,body):
    features.require_manager(store,actor)
    name=str(body.get('nome','')).strip();extension=str(body.get('ramal','')).strip()
    if not 2<=len(name)<=120 or len(extension)>20 or not re.fullmatch(r'[0-9+() #.-]*',extension):raise legal.AppError('Informe nome válido e ramal opcional de até 20 caracteres.')
    with store.lock,store.connect() as db:
        schema(db)
        if not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():raise legal.AppError('Usuário não encontrado.',404)
        db.execute('UPDATE users SET nome=? WHERE id=?',(name,uid));db.execute('INSERT OR REPLACE INTO chat_profiles VALUES(?,?)',(uid,extension))
        store.audit(db,actor,'alterar_nome_ramal','chat_usuario',uid,after={'nome':name,'ramal':extension})
    return {'ok':True}


def rename(store,actor,rid,title):
    features.require_manager(store,actor)
    title=str(title).strip()
    if not 1<=len(title)<=120:raise legal.AppError('Nome de setor inválido.')
    with store.lock,store.connect() as db:
        schema(db)
        if not db.execute("SELECT 1 FROM chat_rooms WHERE id=? AND tipo!='direta'",(rid,)).fetchone():raise legal.AppError('Grupo não encontrado.',404)
        db.execute('UPDATE chat_rooms SET titulo=? WHERE id=?',(title,rid));store.audit(db,actor,'renomear_grupo','chat',rid,after={'titulo':title})
    return {'ok':True}


def rooms(store,actor,audit=False):
    if audit:features.require_manager(store,actor,True)
    with store.lock,store.connect() as db:
        schema(db);features.ensure_general(db)
        query='SELECT r.*,COALESCE(m.last_read,0) AS last_read FROM chat_rooms r LEFT JOIN chat_members m ON m.room_id=r.id AND m.user_id=?'
        if not audit:query+=' WHERE m.user_id IS NOT NULL'
        rows=[]
        for r in db.execute(query+' ORDER BY r.id DESC',(actor['id'],)).fetchall():
            d=dict(r);d.pop('direct_key',None);d.update(office.room_info(db,d,actor))
            d['silenciado']=bool(db.execute('SELECT 1 FROM chat_mutes WHERE room_id=? AND user_id=?',(r['id'],actor['id'])).fetchone())
            d['nao_lidas']=db.execute('SELECT COUNT(*) FROM chat_messages m WHERE m.room_id=? AND m.sender_id!=? AND '+visual.UNREAD,(r['id'],actor['id'],actor['id'],actor['id'])).fetchone()[0]
            d['membros']=[dict(u) for u in db.execute('SELECT u.id,u.nome FROM users u JOIN chat_members m ON m.user_id=u.id WHERE m.room_id=?',(r['id'],))]
            if d['tipo']=='direta':d['titulo']=' / '.join(m['nome'] for m in d['membros'])
            rows.append(d)
        import chat_preferencias as prefs
        prefs.schema(db);pins={r[0] for r in db.execute('SELECT room_id FROM chat_pins WHERE user_id=?',(actor['id'],))}
        for room in rows:room['fixada']=room['id'] in pins
        rows.sort(key=lambda r:(not r['fixada'],-r['id']))
        if audit:store.audit(db,actor,'listar_conversas_administracao','chat')
        return rows


def create(store,actor,body):
    editor(actor);kind=body.get('tipo','grupo');title=str(body.get('titulo','')).strip()
    if kind not in ('direta','grupo','comunicado'):raise legal.AppError('Tipo de conversa inválido.')
    if kind!='direta':features.require_manager(store,actor)
    ids=body.get('membros',[])
    if not isinstance(ids,list) or len(ids)>100 or any(type(v)is not int for v in ids):raise legal.AppError('Selecione até 100 integrantes.')
    ids=set(ids)|{actor['id']}
    if len(ids)<2 or (kind=='direta' and len(ids)!=2):raise legal.AppError('Selecione os participantes da conversa.')
    if len(title)>120 or (kind!='direta' and not title):raise legal.AppError('Informe um título de até 120 caracteres.')
    with store.lock,store.connect() as db:
        schema(db)
        people=[dict(r) for r in db.execute('SELECT id,nome FROM users WHERE ativo=1') if r['id'] in ids]
        if len(people)!=len(ids):raise legal.AppError('Há participante inexistente ou desativado.')
        key=':'.join(map(str,sorted(ids))) if kind=='direta' else None
        if key:
            old=db.execute('SELECT id FROM chat_rooms WHERE direct_key=?',(key,)).fetchone()
            if old:return {'id':old[0]}
            title=' / '.join(p['nome'] for p in people)
        cur=db.execute('INSERT INTO chat_rooms(titulo,tipo,owner_id,criado,direct_key) VALUES(?,?,?,?,?)',(title,kind,actor['id'],legal.now(),key));rid=cur.lastrowid
        db.executemany('INSERT INTO chat_members(room_id,user_id) VALUES(?,?)',[(rid,i) for i in ids])
        store.audit(db,actor,'criar_conversa','chat',rid,after={'tipo':kind,'membros':sorted(ids)})
        return {'id':rid}


def members(store,actor,rid,ids):
    editor(actor)
    if not isinstance(ids,list) or len(ids)>100 or any(type(v)is not int for v in ids):raise legal.AppError('Participantes inválidos.')
    with store.lock,store.connect() as db:
        schema(db);room=db.execute('SELECT * FROM chat_rooms WHERE id=?',(rid,)).fetchone()
        if not room:raise legal.AppError('Conversa não encontrada.',404)
        if room['tipo']=='direta':raise legal.AppError('Conversa individual tem participantes fixos.')
        if not features.manager(db,actor['id']):raise legal.AppError('Somente administradores do chat gerenciam integrantes.',403)
        if room['tipo']=='geral':raise legal.AppError('O Geral reúne automaticamente todos os usuários ativos.')
        if db.execute('SELECT 1 FROM chat_broadcasts WHERE room_id=? LIMIT 1',(rid,)).fetchone():raise legal.AppError('Este aviso mantém os destinatários do envio. Publique um novo aviso para outra seleção.')
        ids=set(ids)|{room['owner_id']}
        valid={r[0] for r in db.execute('SELECT id FROM users WHERE ativo=1')}
        if not ids<=valid:raise legal.AppError('Participante inexistente ou desativado.')
        reads={r['user_id']:r['last_read'] for r in db.execute('SELECT * FROM chat_members WHERE room_id=?',(rid,))}
        db.execute('DELETE FROM chat_members WHERE room_id=?',(rid,));db.executemany('INSERT INTO chat_members(room_id,user_id,last_read) VALUES(?,?,?)',[(rid,i,reads.get(i,0)) for i in ids])
        store.audit(db,actor,'alterar_integrantes','chat',rid,after={'membros':sorted(ids)})
    return {'ok':True}


def attachment(item):
    if not isinstance(item,dict):raise legal.AppError('Anexo inválido.')
    try:data=base64.b64decode(item.get('base64',''),validate=True)
    except (ValueError,TypeError):raise legal.AppError('Anexo inválido.')
    if not data or len(data)>MAX_FILE:raise legal.AppError('Cada arquivo pode ter até 10 MB.')
    name=str(item.get('nome','arquivo')).replace('\\','/').split('/')[-1][:180]
    if not name or any(ord(c)<32 for c in name):raise legal.AppError('Nome de arquivo inválido.')
    # Tipo determinado pelos bytes, nunca pelo MIME enviado pelo navegador.
    if data.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
    elif data.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
    elif data.startswith((b'GIF87a',b'GIF89a')):mime='image/gif'
    elif data[:4]==b'RIFF' and data[8:12]==b'WEBP':mime='image/webp'
    elif data.startswith(b'OggS'):mime='audio/ogg'
    elif data[:4]==b'RIFF' and data[8:12]==b'WAVE':mime='audio/wav'
    elif data.startswith(b'\x1aE\xdf\xa3'):mime='audio/webm' if item.get('tipo')=='audio' else 'video/webm'
    elif data[4:8]==b'ftyp':mime='video/mp4'
    else:mime='application/octet-stream'
    kind=str(item.get('tipo','arquivo'))
    if kind not in ('arquivo','audio','figurinha'):raise legal.AppError('Tipo de anexo inválido.')
    if kind=='figurinha' and mime not in ('image/png','image/jpeg','image/gif','image/webp'):raise legal.AppError('Use PNG, JPG, GIF ou WebP para a figurinha.')
    return (uuid.uuid4().hex,name,mime,kind,len(data),hashlib.sha256(data).hexdigest(),data)


def send(store,actor,rid,body):
    editor(actor);text=str(body.get('texto','')).strip();files=body.get('anexos',[]);nonce=str(body.get('nonce',''))
    if len(text)>10000 or not isinstance(files,list) or len(files)>1:raise legal.AppError('Até 10 mil caracteres e um arquivo por mensagem.')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',nonce):raise legal.AppError('Identificador da mensagem inválido.')
    if not text and not files:raise legal.AppError('Escreva ou anexe um arquivo.')
    with store.lock,store.connect() as db:
        schema(db)
        if not db.execute('SELECT 1 FROM chat_members WHERE room_id=? AND user_id=?',(rid,actor['id'])).fetchone():raise legal.AppError('Você não participa desta conversa.',403)
        room=access(store,db,actor,rid)
        if not features.can_post(db,actor['id'],room['tipo']):raise legal.AppError('Você não tem permissão para publicar neste canal.',403)
        reply,poll=features.prepare(db,actor,rid,body)
        old=db.execute('SELECT id,room_id FROM chat_messages WHERE sender_id=? AND nonce=?',(actor['id'],nonce)).fetchone()
        if old:
            if old['room_id']!=rid:raise legal.AppError('Identificador já usado em outra conversa.')
            return {'id':old['id']}
        parsed=[attachment(f) for f in files]
        cur=db.execute('INSERT INTO chat_messages(room_id,sender_id,texto,criado,nonce) VALUES(?,?,?,?,?)',(rid,actor['id'],text,legal.now(),nonce));mid=cur.lastrowid
        db.execute('INSERT INTO chat_meta VALUES(?,?,?)',(mid,reply,int(body.get('_encaminhada') is True)))
        if poll:db.execute('INSERT INTO chat_polls(message_id,options) VALUES(?,?)',(mid,json.dumps([x.strip() for x in poll],ensure_ascii=False)))
        for f in parsed:db.execute('INSERT INTO chat_files VALUES(?,?,?,?,?,?,?,?)',(f[0],mid,*f[1:]))
        store.audit(db,actor,'enviar_mensagem','chat',rid,after={'mensagem_id':mid,'anexos':len(parsed)})
        return {'id':mid}


def messages(store,actor,rid,after=0,before=0,search='',reason=''):
    with store.lock,store.connect() as db:
        schema(db);room=access(store,db,actor,rid,reason);room.update(office.room_info(db,room,actor))
        args=[rid];query='SELECT m.*,u.nome FROM chat_messages m JOIN users u ON u.id=m.sender_id WHERE m.room_id=?'
        if after:query+=' AND m.id>?';args.append(after)
        if before:query+=' AND m.id<?';args.append(before)
        if search:query+=" AND m.texto LIKE ? ESCAPE '\\'";args.append('%'+str(search).replace('\\','\\\\').replace('%','\\%').replace('_','\\_')[:200]+'%')
        rows=db.execute(query+(' ORDER BY m.id ASC' if after else ' ORDER BY m.id DESC')+' LIMIT 101',args).fetchall();more=len(rows)>100;rows=rows[:100]
        result=[]
        for r in sorted(rows,key=lambda r:r['id']):
            d=dict(r);d.pop('nonce');d['anexos']=[dict(f) for f in db.execute('SELECT id,nome,mime,tipo,tamanho,sha256 FROM chat_files WHERE message_id=?',(r['id'],))];features.enrich(db,actor,d);notice=db.execute('SELECT tipo,titulo,escopo FROM chat_notices WHERE message_id=?',(r['id'],)).fetchone()
            if notice:d['aviso']=dict(notice)
            confirmation=visual.receipt_db(db,actor,r)
            if confirmation:d['confirmacao']={k:v for k,v in confirmation.items() if k!='pessoas'}
            result.append(d)
        room['pode_publicar']=features.can_post(db,actor['id'],room['tipo'])
        features.schema(db)
        room['fixados']=[]
        for a in db.execute('SELECT a.* FROM chat_announcements a WHERE room_id=? ORDER BY position,message_id',(rid,)):
            r=db.execute('SELECT m.*,u.nome FROM chat_messages m JOIN users u ON u.id=m.sender_id WHERE m.id=?',(a['message_id'],)).fetchone()
            if r:room['fixados'].append({'titulo':a['title'],'ordem':a['position'],'mensagem_id':a['message_id'],'texto':r['texto']})
        room['membros']=[dict(r) for r in db.execute('SELECT u.id,u.nome FROM chat_members m JOIN users u ON u.id=m.user_id WHERE m.room_id=?',(rid,))]
        return {'conversa':room,'itens':result,'tem_mais':more}


def read(store,actor,rid,mid):
    return visual.acknowledge(store,actor,rid,mid if isinstance(mid,list) else [mid],True)


def download(store,actor,fid,reason=''):
    with store.lock,store.connect() as db:
        schema(db);row=db.execute('SELECT f.*,m.room_id FROM chat_files f JOIN chat_messages m ON m.id=f.message_id WHERE f.id=?',(fid,)).fetchone()
        if not row:raise legal.AppError('Arquivo não encontrado.',404)
        access(store,db,actor,row['room_id'],reason,'consultar_anexo_administracao')
        store.audit(db,actor,'baixar_anexo_chat','chat',row['room_id'],after={'arquivo_id':fid})
        return dict(row)
