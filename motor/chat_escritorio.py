"""Unidades, setores e comunicados internos com destinatários conferidos."""
import hashlib,json,re
import juridico as legal


def schema(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS chat_offices(id INTEGER PRIMARY KEY,nome TEXT NOT NULL,endereco TEXT NOT NULL,atendimento INTEGER NOT NULL,ativo INTEGER NOT NULL DEFAULT 1);
 CREATE TABLE IF NOT EXISTS chat_user_office(user_id INTEGER PRIMARY KEY,office_id INTEGER);
 CREATE TABLE IF NOT EXISTS chat_room_office(room_id INTEGER PRIMARY KEY,office_id INTEGER,setor INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS chat_notices(message_id INTEGER PRIMARY KEY,tipo TEXT NOT NULL,titulo TEXT NOT NULL,escopo TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS chat_broadcasts(sender_id INTEGER,nonce TEXT,room_id INTEGER,message_id INTEGER,payload_hash TEXT,PRIMARY KEY(sender_id,nonce));
 ''')
 if not db.execute('SELECT 1 FROM chat_offices LIMIT 1').fetchone():
  db.executemany('INSERT INTO chat_offices VALUES(?,?,?,?,1)',[(1,'Principal — 805','Ramiro Barcelos, 805',1),(2,'Casa 2 — 787','Ramiro Barcelos, 787',0)])

def owner_required(db,actor):
 import chat_recursos as features
 if actor['id']!=features.owner(db):raise legal.AppError('Só o proprietário organiza unidades e setores.',403)
def directory(store,actor,body=None):
 import chat_interno as chat,chat_recursos as features
 with store.lock,store.connect() as db:
  chat.schema(db);schema(db);is_owner=actor['id']==features.owner(db)
  if body is not None:
   owner_required(db,actor);action=body.get('acao')
   oid=body.get('unidade_id')
   if action in ('pessoa','setor') and oid is not None:
    if type(oid)is not int or not db.execute('SELECT 1 FROM chat_offices WHERE id=? AND ativo=1',(oid,)).fetchone():raise legal.AppError('Unidade inválida.')
   if action=='pessoa':
    uid=body.get('user_id')
    if type(uid)is not int or not db.execute('SELECT 1 FROM users WHERE id=? AND ativo=1',(uid,)).fetchone():raise legal.AppError('Pessoa inválida.')
    db.execute('INSERT OR REPLACE INTO chat_user_office VALUES(?,?)',(uid,oid));entity=uid
   elif action=='setor':
    rid=body.get('room_id')
    if type(rid)is not int or not db.execute("SELECT 1 FROM chat_rooms WHERE id=? AND tipo='grupo'",(rid,)).fetchone():raise legal.AppError('Selecione um grupo de setor.')
    if type(body.get('setor'))is not bool:raise legal.AppError('Classificação inválida.')
    db.execute('INSERT OR REPLACE INTO chat_room_office VALUES(?,?,?)',(rid,oid,int(body['setor'])));entity=rid
   elif action=='unidade':
    title=str(body.get('nome','')).strip();address=str(body.get('endereco','')).strip()
    if not 1<=len(title)<=100 or len(address)>200 or type(body.get('atendimento'))is not bool or type(body.get('ativo'))is not bool:raise legal.AppError('Dados da unidade inválidos.')
    if type(oid)is not int or not db.execute('SELECT 1 FROM chat_offices WHERE id=?',(oid,)).fetchone():raise legal.AppError('Unidade não encontrada.')
    db.execute('UPDATE chat_offices SET nome=?,endereco=?,atendimento=?,ativo=? WHERE id=?',(title,address,int(body['atendimento']),int(body['ativo']),oid));entity=oid
   else:raise legal.AppError('Operação inválida.')
   store.audit(db,actor,'organizar_chat_'+action,'chat_escritorio',entity,after={k:v for k,v in body.items() if k!='acao'})
  result={'proprietario':is_owner,'unidades':[dict(r) for r in db.execute('SELECT * FROM chat_offices ORDER BY id')],
   'setores':[dict(r) for r in db.execute("SELECT r.id,r.titulo,o.office_id AS unidade_id,(SELECT COUNT(*) FROM chat_members m JOIN users u ON u.id=m.user_id WHERE m.room_id=r.id AND u.ativo=1) AS integrantes FROM chat_rooms r JOIN chat_room_office o ON o.room_id=r.id WHERE r.tipo='grupo' AND o.setor=1 ORDER BY r.titulo")]}
  if is_owner:
   result['usuarios']=[dict(r) for r in db.execute('SELECT u.id,u.nome,o.office_id AS unidade_id FROM users u LEFT JOIN chat_user_office o ON o.user_id=u.id WHERE u.ativo=1 ORDER BY u.nome')]
   result['grupos']=[dict(r) for r in db.execute("SELECT r.id,r.titulo,o.office_id AS unidade_id,COALESCE(o.setor,0) AS setor FROM chat_rooms r LEFT JOIN chat_room_office o ON o.room_id=r.id WHERE r.tipo='grupo' ORDER BY r.titulo")]
  return result

def user_info(db,uid):
 row=db.execute('SELECT o.id,o.nome FROM chat_user_office p JOIN chat_offices o ON o.id=p.office_id WHERE p.user_id=?',(uid,)).fetchone()
 return {'unidade_id':row['id'] if row else None,'unidade_nome':row['nome'] if row else '',
  'setores':[r[0] for r in db.execute("SELECT r.titulo FROM chat_members m JOIN chat_rooms r ON r.id=m.room_id JOIN chat_room_office o ON o.room_id=r.id WHERE m.user_id=? AND o.setor=1 ORDER BY r.titulo",(uid,))]}
def room_info(db,room,actor):
 row=db.execute('SELECT o.office_id,o.setor,u.nome FROM chat_room_office o LEFT JOIN chat_offices u ON u.id=o.office_id WHERE o.room_id=?',(room['id'],)).fetchone()
 result={'audiencia_fixa':bool(db.execute('SELECT 1 FROM chat_broadcasts WHERE room_id=? LIMIT 1',(room['id'],)).fetchone()) and room['tipo']!='geral','unidade_id':row['office_id'] if row else None,'unidade_nome':row['nome'] if row else '', 'setor':bool(row and row['setor'])}
 if room['tipo']=='direta':
  peer=db.execute('SELECT user_id FROM chat_members WHERE room_id=? AND user_id!=? LIMIT 1',(room['id'],actor['id'])).fetchone()
  if peer:result.update({k:v for k,v in user_info(db,peer[0]).items() if k!='setores'})
 return result

def recipients(db,actor,audience):
 if not isinstance(audience,dict) or set(audience)-{'escopo','ids'}:raise legal.AppError('Seleção de destinatários inválida.')
 scope=audience.get('escopo');ids=audience.get('ids',[])
 if scope not in ('todos','unidades','setores','pessoas') or not isinstance(ids,list) or len(ids)>5000 or any(type(v)is not int or v<1 for v in ids):raise legal.AppError('Destinatários inválidos.')
 ids=set(ids)
 if scope!='todos' and not ids:raise legal.AppError('Escolha pelo menos um destinatário.')
 active={r['id']:dict(r) for r in db.execute('SELECT id,nome FROM users WHERE ativo=1')}
 if scope=='todos':
  if ids:raise legal.AppError('Escritório inteiro não aceita uma seleção parcial.')
  selected=set(active)
 elif scope=='pessoas':
  if not ids<=set(active):raise legal.AppError('Uma pessoa não está mais ativa. Revise a seleção.',409)
  selected=ids
 elif scope=='unidades':
  valid={r[0] for r in db.execute('SELECT id FROM chat_offices WHERE ativo=1')}
  if not ids<=valid:raise legal.AppError('Unidade indisponível. Revise a seleção.',409)
  selected={r['user_id'] for r in db.execute('SELECT * FROM chat_user_office') if r['office_id'] in ids and r['user_id'] in active}
 else:
  valid={r[0] for r in db.execute('SELECT room_id FROM chat_room_office WHERE setor=1')}
  if not ids<=valid:raise legal.AppError('Setor indisponível. Revise a seleção.',409)
  selected={r['user_id'] for r in db.execute('SELECT * FROM chat_members') if r['room_id'] in ids and r['user_id'] in active}
 selected.discard(actor['id'])
 if not selected:raise legal.AppError('A seleção não tem destinatários ativos além de você.')
 people=sorted([active[uid] for uid in selected],key=lambda r:(r['nome'].casefold(),r['id']))
 token=hashlib.sha256(legal.dumps({'escopo':scope,'ids':sorted(ids),'pessoas':sorted(selected)}).encode()).hexdigest()
 return {'pessoas':people,'total':len(people),'token':token,'escopo':scope}

def sender_allowed(db,actor):
 import chat_interno as chat,chat_recursos as features
 chat.editor(actor)
 if not features.can_post(db,actor['id'],'geral'):raise legal.AppError('Você não tem permissão para publicar comunicados e alertas.',403)
def preview(store,actor,body):
 import chat_interno as chat
 with store.lock,store.connect() as db:
  chat.schema(db);schema(db);sender_allowed(db,actor);return recipients(db,actor,body.get('audiencia'))

def broadcast(store,actor,body):
 import chat_interno as chat,chat_recursos as features
 title=str(body.get('titulo','')).strip();text=str(body.get('texto','')).strip();kind=body.get('tipo');nonce=body.get('nonce');files=body.get('anexos',[])
 if not 1<=len(title)<=120 or not 1<=len(text)<=9500 or kind not in ('comunicado','alerta') or not isinstance(nonce,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',nonce):raise legal.AppError('Informe título, mensagem e tipo válidos.')
 if not isinstance(files,list) or len(files)>1:raise legal.AppError('Até um anexo por aviso.')
 parsed=[chat.attachment(f) for f in files]
 digest=hashlib.sha256(legal.dumps(body).encode()).hexdigest()
 with store.lock,store.connect() as db:
  chat.schema(db);schema(db);sender_allowed(db,actor)
  old=db.execute('SELECT * FROM chat_broadcasts WHERE sender_id=? AND nonce=?',(actor['id'],nonce)).fetchone()
  if old:
   if old['payload_hash']!=digest:raise legal.AppError('Este envio já foi usado para outro conteúdo. Abra um novo aviso.',409)
   return {'id':old['room_id'],'mensagem_id':old['message_id'],'repetido':True}
  if db.execute('SELECT 1 FROM chat_messages WHERE sender_id=? AND nonce=?',(actor['id'],nonce)).fetchone():raise legal.AppError('Identificador já usado em outro envio.',409)
  audience=body.get('audiencia');selection=recipients(db,actor,audience)
  if body.get('previa_token')!=selection['token']:raise legal.AppError('Destinatários mudaram ou ainda não foram conferidos. Faça a prévia novamente.',409)
  rid=features.ensure_general(db) if selection['escopo']=='todos' else None
  # Todas as chamadas que criam esquemas terminam antes dos INSERTs do envio.
  if rid is None:
   rid=db.execute('INSERT INTO chat_rooms(titulo,tipo,owner_id,criado) VALUES(?,?,?,?)',((('Alerta · ' if kind=='alerta' else '')+title)[:120],'comunicado',actor['id'],legal.now())).lastrowid
   db.executemany('INSERT INTO chat_members(room_id,user_id) VALUES(?,?)',[(rid,uid) for uid in {actor['id'],*(p['id'] for p in selection['pessoas'])}])
   if selection['escopo']=='unidades' and len(set(audience['ids']))==1:db.execute('INSERT INTO chat_room_office VALUES(?,?,0)',(rid,audience['ids'][0]))
  mid=db.execute('INSERT INTO chat_messages(room_id,sender_id,texto,criado,nonce) VALUES(?,?,?,?,?)',(rid,actor['id'],title+'\n\n'+text,legal.now(),nonce)).lastrowid
  db.execute('INSERT INTO chat_meta VALUES(?,NULL,0)',(mid,))
  db.execute('INSERT INTO chat_notices VALUES(?,?,?,?)',(mid,kind,title,selection['escopo']))
  for f in parsed:db.execute('INSERT INTO chat_files VALUES(?,?,?,?,?,?,?,?)',(f[0],mid,*f[1:]))
  db.execute('INSERT INTO chat_broadcasts VALUES(?,?,?,?,?)',(actor['id'],nonce,rid,mid,digest))
  store.audit(db,actor,'publicar_aviso_direcionado','chat',rid,after={'mensagem_id':mid,'tipo':kind,'escopo':selection['escopo'],'destinatarios':[p['id'] for p in selection['pessoas']]})
  return {'id':rid,'mensagem_id':mid,'total':selection['total'],'repetido':False}
