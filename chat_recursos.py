"""Interações e governança do chat, persistidas no mesmo banco."""
import json
import juridico as legal

EMOJIS=('👍','❤️','😂','😮','😢','🙏','✅','⚠️')
def schema(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS chat_control(id INTEGER PRIMARY KEY CHECK(id=1),owner_id INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS chat_roles(user_id INTEGER PRIMARY KEY,admin INTEGER NOT NULL DEFAULT 0,speaker INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS chat_meta(message_id INTEGER PRIMARY KEY,reply_id INTEGER,forwarded INTEGER DEFAULT 0);
 CREATE TABLE IF NOT EXISTS chat_reactions(message_id INTEGER,user_id INTEGER,emoji TEXT,PRIMARY KEY(message_id,user_id));
 CREATE TABLE IF NOT EXISTS chat_mutes(room_id INTEGER,user_id INTEGER,PRIMARY KEY(room_id,user_id));
 CREATE TABLE IF NOT EXISTS chat_announcements(message_id INTEGER PRIMARY KEY,room_id INTEGER,title TEXT,position INTEGER);
 CREATE TABLE IF NOT EXISTS chat_polls(message_id INTEGER PRIMARY KEY,options TEXT,closed INTEGER DEFAULT 0);
 CREATE TABLE IF NOT EXISTS chat_votes(message_id INTEGER,user_id INTEGER,choice INTEGER,PRIMARY KEY(message_id,user_id));
 ''')
def owner(db):
 schema(db);r=db.execute('SELECT owner_id FROM chat_control WHERE id=1').fetchone()
 # Migração previsível: conta que criou a instalação. Pode ser escolhida localmente.
 if not r:
  r=db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
  if not r:raise legal.AppError('Cadastre a conta proprietária primeiro.',409)
  db.execute('INSERT INTO chat_control VALUES(1,?)',(r[0],))
 return r[0]
def manager(db,uid):return uid==owner(db) or bool(db.execute('SELECT 1 FROM chat_roles WHERE user_id=? AND admin=1',(uid,)).fetchone())
def require_manager(store,actor,only_owner=False):
 with store.lock,store.connect() as db:
  if (actor['id']!=owner(db) if only_owner else not manager(db,actor['id'])):raise legal.AppError('Ação restrita ao proprietário do chat.' if only_owner else 'Ação restrita à administração do chat.',403)
def can_post(db,uid,kind):
 if kind not in ('geral','comunicado'):return True
 return manager(db,uid) or bool(db.execute('SELECT 1 FROM chat_roles WHERE user_id=? AND speaker=1',(uid,)).fetchone())
def ensure_general(db):
 import chat_interno as chat
 chat.schema(db);oid=owner(db)
 row=db.execute("SELECT id FROM chat_rooms WHERE direct_key='__geral__'").fetchone()
 if not row:
  rid=db.execute("INSERT INTO chat_rooms(titulo,tipo,owner_id,criado,direct_key) VALUES('Geral do escritório','geral',?,?, '__geral__')",(oid,legal.now())).lastrowid
 else:rid=row[0]
 db.execute('INSERT OR IGNORE INTO chat_members(room_id,user_id) SELECT ?,id FROM users WHERE ativo=1',(rid,))
 db.execute('DELETE FROM chat_members WHERE room_id=? AND user_id IN (SELECT id FROM users WHERE ativo=0)',(rid,))
 return rid
def config(store,actor,body=None):
 with store.lock,store.connect() as db:
  oid=owner(db)
  if body is not None:
   if actor['id']!=oid:raise legal.AppError('Só o proprietário concede ou retira permissões.',403)
   uid=body.get('user_id')
   if type(uid)is not int or not db.execute('SELECT 1 FROM users WHERE id=? AND ativo=1',(uid,)).fetchone():raise legal.AppError('Usuário inválido.')
   if uid==oid:raise legal.AppError('A conta proprietária não pode perder suas permissões.')
   if type(body.get('admin'))is not bool or type(body.get('speaker'))is not bool:raise legal.AppError('Permissões inválidas.')
   db.execute('INSERT OR REPLACE INTO chat_roles VALUES(?,?,?)',(uid,int(body['admin']),int(body['speaker'])))
   store.audit(db,actor,'permissoes_chat','chat_usuario',uid,after={'admin':body['admin'],'speaker':body['speaker']})
  result={'owner_id':oid,'owner_nome':db.execute('SELECT nome FROM users WHERE id=?',(oid,)).fetchone()[0],'proprietario':actor['id']==oid,'administrador':manager(db,actor['id']),'pode_publicar':actor['role']!='leitor' and can_post(db,actor['id'],'geral')}
  if result['proprietario']:result['usuarios']=[dict(r) for r in db.execute('SELECT u.id,u.nome,COALESCE(r.admin,0) AS admin,COALESCE(r.speaker,0) AS speaker FROM users u LEFT JOIN chat_roles r ON r.user_id=u.id WHERE u.ativo=1 ORDER BY u.nome')]
  return result

def member(db,actor,rid):
 if not db.execute('SELECT 1 FROM chat_members WHERE room_id=? AND user_id=?',(rid,actor['id'])).fetchone():raise legal.AppError('Você não participa desta conversa.',403)
def message(db,actor,mid):
 import chat_interno as chat
 chat.schema(db);schema(db)
 row=db.execute('SELECT m.*,r.tipo FROM chat_messages m JOIN chat_rooms r ON r.id=m.room_id WHERE m.id=?',(mid,)).fetchone()
 if not row:raise legal.AppError('Mensagem não encontrada.',404)
 member(db,actor,row['room_id']);return row

def enrich(db,actor,d):
 schema(db);mid=d['id'];meta=db.execute('SELECT * FROM chat_meta WHERE message_id=?',(mid,)).fetchone()
 d['encaminhada']=bool(meta and meta['forwarded']);d['resposta']=None
 if meta and meta['reply_id']:
  r=db.execute('SELECT m.id,m.texto,u.nome FROM chat_messages m JOIN users u ON u.id=m.sender_id WHERE m.id=? AND m.room_id=?',(meta['reply_id'],d['room_id'])).fetchone()
  if r:d['resposta']=dict(r)
 d['reacoes']=[dict(r) for r in db.execute('SELECT r.emoji,u.id AS user_id,u.nome FROM chat_reactions r JOIN users u ON u.id=r.user_id WHERE message_id=?',(mid,))]
 p=db.execute('SELECT * FROM chat_polls WHERE message_id=?',(mid,)).fetchone()
 if p:
  d['enquete']={'opcoes':json.loads(p['options']),'encerrada':bool(p['closed']),'votos':[dict(v) for v in db.execute('SELECT v.user_id,v.choice AS opcao,u.nome FROM chat_votes v JOIN users u ON u.id=v.user_id WHERE message_id=?',(mid,))]}
 return d

def prepare(db,actor,rid,body):
 schema(db);reply=body.get('responder_id');poll=body.get('enquete')
 if reply is not None:
  if type(reply)is not int:raise legal.AppError('Resposta inválida.')
  r=message(db,actor,reply)
  if r['room_id']!=rid:raise legal.AppError('Responda a uma mensagem desta conversa.')
 if poll is not None:
  if not isinstance(poll,list) or not 2<=len(poll)<=12 or any(not isinstance(x,str) or not 1<=len(x.strip())<=200 for x in poll) or len({x.strip().casefold() for x in poll})!=len(poll):raise legal.AppError('Informe de 2 a 12 opções diferentes, até 200 caracteres.')
 return reply,poll

def action(store,actor,mid,body):
 import chat_interno as chat
 with store.lock,store.connect() as db:
  row=message(db,actor,mid);act=body.get('acao')
  if act=='reagir':
   emoji=body.get('emoji')
   if emoji not in EMOJIS:raise legal.AppError('Reação inválida.')
   old=db.execute('SELECT emoji FROM chat_reactions WHERE message_id=? AND user_id=?',(mid,actor['id'])).fetchone()
   db.execute('DELETE FROM chat_reactions WHERE message_id=? AND user_id=?',(mid,actor['id']))
   if not old or old[0]!=emoji:db.execute('INSERT INTO chat_reactions VALUES(?,?,?)',(mid,actor['id'],emoji))
  elif act in ('votar','encerrar'):
   p=db.execute('SELECT * FROM chat_polls WHERE message_id=?',(mid,)).fetchone()
   if not p:raise legal.AppError('Enquete não encontrada.',404)
   if act=='encerrar':
    if actor['id']!=row['sender_id'] and not manager(db,actor['id']):raise legal.AppError('Só o autor ou a administração pode encerrar.',403)
    db.execute('UPDATE chat_polls SET closed=1 WHERE message_id=?',(mid,))
   else:
    if p['closed']:raise legal.AppError('Votação encerrada.',409)
    choice=body.get('opcao')
    if type(choice)is not int or not 0<=choice<len(json.loads(p['options'])):raise legal.AppError('Opção inválida.')
    db.execute('INSERT OR REPLACE INTO chat_votes VALUES(?,?,?)',(mid,actor['id'],choice))
  elif act in ('fixar','desfixar'):
   if not manager(db,actor['id']) or row['tipo'] not in ('geral','comunicado'):raise legal.AppError('Só a administração fixa avisos neste canal.',403)
   if act=='desfixar':db.execute('DELETE FROM chat_announcements WHERE message_id=?',(mid,))
   else:
    title=str(body.get('titulo','')).strip();pos=body.get('ordem',0)
    if not 1<=len(title)<=120 or type(pos)is not int or not 0<=pos<=9999:raise legal.AppError('Informe título e ordem de 0 a 9999.')
    db.execute('INSERT OR REPLACE INTO chat_announcements VALUES(?,?,?,?)',(mid,row['room_id'],title,pos))
  else:raise legal.AppError('Ação inválida.')
  store.audit(db,actor,'chat_'+act,'chat_mensagem',mid,after={k:v for k,v in body.items() if k in ('emoji','opcao','titulo','ordem')})
 return {'ok':True}
def mute(store,actor,rid,body):
 with store.lock,store.connect() as db:
  schema(db);member(db,actor,rid)
  if type(body.get('silenciado'))is not bool:raise legal.AppError('Opção inválida.')
  db.execute('DELETE FROM chat_mutes WHERE room_id=? AND user_id=?',(rid,actor['id']))
  if body['silenciado']:db.execute('INSERT INTO chat_mutes VALUES(?,?)',(rid,actor['id']))
 return {'ok':True}
def forward(store,actor,mid,body):
 import chat_interno as chat
 with store.lock,store.connect() as db:
  row=message(db,actor,mid);target=body.get('destino_id');nonce=str(body.get('nonce',''))
  if type(target)is not int:raise legal.AppError('Conversa de destino inválida.')
  # Snapshot do conteúdo, sem remetente original, resposta, votos ou reações.
  import base64
  files=[{'nome':r['nome'],'tipo':r['tipo'],'base64':base64.b64encode(r['conteudo']).decode()} for r in db.execute('SELECT * FROM chat_files WHERE message_id=?',(mid,))]
  text=row['texto']
 result=chat.send(store,actor,target,{'texto':text,'anexos':files,'nonce':nonce,'_encaminhada':True})
 return result
