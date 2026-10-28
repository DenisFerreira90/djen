"""Política do proprietário, prévias e confirmações explícitas de visualização."""
import json
import juridico as legal

FEATURES=('recolher_auto','previas','confirmacoes','horarios','compartilhar_leitura')
DEFAULT={**dict.fromkeys(FEATURES,True),'registrar_horarios':True}
def schema(db):
 db.executescript('''
 CREATE TABLE IF NOT EXISTS chat_display_policy(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS chat_display_grants(user_id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS chat_read_baseline(room_id INTEGER,user_id INTEGER,through_id INTEGER NOT NULL,PRIMARY KEY(room_id,user_id));
 CREATE TABLE IF NOT EXISTS chat_reads(message_id INTEGER,user_id INTEGER,lida_em TEXT,PRIMARY KEY(message_id,user_id));
 CREATE TABLE IF NOT EXISTS chat_read_sharing(message_id INTEGER,user_id INTEGER,enabled INTEGER NOT NULL,PRIMARY KEY(message_id,user_id));
 CREATE TABLE IF NOT EXISTS chat_deliveries(message_id INTEGER,user_id INTEGER,recebida_em TEXT NOT NULL,PRIMARY KEY(message_id,user_id));
 CREATE INDEX IF NOT EXISTS chat_reads_user ON chat_reads(user_id,message_id);
 ''')
 if db.execute("SELECT 1 FROM sqlite_master WHERE name='chat_members'").fetchone():
  db.execute('INSERT OR IGNORE INTO chat_read_baseline SELECT room_id,user_id,last_read FROM chat_members')
def policy(db):
 row=db.execute('SELECT payload FROM chat_display_policy WHERE id=1').fetchone()
 return {**DEFAULT,**(json.loads(row[0]) if row else {})}
def grants(db,uid):
 row=db.execute('SELECT payload FROM chat_display_grants WHERE user_id=?',(uid,)).fetchone()
 return {**dict.fromkeys(FEATURES,True),**(json.loads(row[0]) if row else {})}
def allowed(db,uid):
 base=policy(db);g=grants(db,uid);return {k:base[k] and g[k] for k in FEATURES}
def effective(db,uid):
 import chat_preferencias as prefs
 prefs.schema(db);p=prefs.get_db(db,uid)
 result=allowed(db,uid)
 for key,pref in [('recolher_auto','recolher_auto'),('previas','mostrar_previas'),('confirmacoes','mostrar_confirmacoes'),('horarios','mostrar_horarios')]:result[key]=result[key] and p.get(pref,True)
 result['horarios']=result['horarios'] and result['confirmacoes'];return result

def config(store,actor,body=None):
 import chat_recursos as features
 with store.lock,store.connect() as db:
  schema(db);oid=features.owner(db);is_owner=actor['id']==oid
  if body is not None:
   if not is_owner:raise legal.AppError('Só o proprietário altera estas regras e permissões.',403)
   values=body.get('valores');scope=body.get('escopo')
   allowed=set(DEFAULT) if scope=='geral' else set(FEATURES) if scope=='usuario' else set()
   if not isinstance(values,dict) or not values or set(values)-allowed or any(type(v)is not bool for v in values.values()):raise legal.AppError('Configurações inválidas.')
   if scope=='geral':
    previous=policy(db);value={**previous,**values};db.execute('INSERT OR REPLACE INTO chat_display_policy VALUES(1,?)',(legal.dumps(value),));uid='geral'
   else:
    uid=body.get('user_id')
    if type(uid)is not int or not db.execute('SELECT 1 FROM users WHERE id=? AND ativo=1',(uid,)).fetchone():raise legal.AppError('Usuário inválido.')
    previous=grants(db,uid);value={**previous,**values};db.execute('INSERT OR REPLACE INTO chat_display_grants VALUES(?,?)',(uid,legal.dumps(value)))
   store.audit(db,actor,'configurar_visualizacao_chat','chat_configuracoes',uid,before=previous,after=value)
  result={'proprietario':is_owner,'efetivas':effective(db,actor['id'])}
  if is_owner:result.update(politica=policy(db),usuarios=[{'id':r['id'],'nome':r['nome'],'permissoes':grants(db,r['id'])} for r in db.execute('SELECT id,nome FROM users WHERE ativo=1 ORDER BY nome')])
  return result

UNREAD="""m.id>COALESCE((SELECT b.through_id FROM chat_read_baseline b WHERE b.room_id=m.room_id AND b.user_id=?),0)
 AND NOT EXISTS(SELECT 1 FROM chat_reads cr WHERE cr.message_id=m.id AND cr.user_id=?)"""
def acknowledge(store,actor,rid,ids,read=False):
 import chat_interno as chat
 if not isinstance(ids,list) or len(ids)>100 or any(type(v)is not int or v<1 for v in ids):raise legal.AppError('Selecione até 100 mensagens válidas.')
 with store.lock,store.connect() as db:
  chat.schema(db);schema(db);settings=policy(db)
  if not db.execute('SELECT 1 FROM chat_members WHERE room_id=? AND user_id=?',(rid,actor['id'])).fetchone():raise legal.AppError('Você não participa desta conversa.',403)
  ids=set(ids)
  if ids:
   placeholders=','.join('?' for _ in ids)
   rows=db.execute('SELECT id,sender_id FROM chat_messages WHERE room_id=? AND id IN ('+placeholders+')',(rid,*ids)).fetchall()
   if len(rows)!=len(ids):raise legal.AppError('Mensagem fora desta conversa.',403)
   now=legal.now();baseline=db.execute('SELECT through_id FROM chat_read_baseline WHERE room_id=? AND user_id=?',(rid,actor['id'])).fetchone()
   through=baseline[0] if baseline else 0;share=allowed(db,actor['id'])['compartilhar_leitura']
   for row in rows:
    if row['sender_id']==actor['id'] or row['id']<=through:continue
    db.execute('INSERT OR IGNORE INTO chat_deliveries VALUES(?,?,?)',(row['id'],actor['id'],now))
    if read:
     created=db.execute('INSERT OR IGNORE INTO chat_reads VALUES(?,?,?)',(row['id'],actor['id'],now if settings['registrar_horarios'] and share else None)).rowcount
     if created:db.execute('INSERT OR IGNORE INTO chat_read_sharing VALUES(?,?,?)',(row['id'],actor['id'],int(share)))
 return {'ok':True}

def receipt_db(db,actor,m):
 if m['sender_id']!=actor['id']:return None
 caps=effective(db,actor['id'])
 if not caps['confirmacoes']:return None
 people=[];base={r['user_id']:r['through_id'] for r in db.execute('SELECT * FROM chat_read_baseline WHERE room_id=?',(m['room_id'],))}
 read={r['user_id']:r['lida_em'] for r in db.execute('SELECT * FROM chat_reads WHERE message_id=?',(m['id'],))}
 delivered={r['user_id']:r['recebida_em'] for r in db.execute('SELECT * FROM chat_deliveries WHERE message_id=?',(m['id'],))}
 sharing={r['user_id']:bool(r['enabled']) for r in db.execute('SELECT * FROM chat_read_sharing WHERE message_id=?',(m['id'],))};global_share=policy(db)['compartilhar_leitura']
 denied={r['user_id'] for r in db.execute('SELECT * FROM chat_display_grants') if json.loads(r['payload']).get('compartilhar_leitura') is False}
 for u in db.execute('SELECT u.id,u.nome FROM users u JOIN chat_members cm ON cm.user_id=u.id WHERE cm.room_id=? AND u.id!=? AND u.ativo=1',(m['room_id'],actor['id'])):
  legacy=base.get(u['id'],0)>=m['id'];known=u['id'] in read or legacy;seen=known and global_share and u['id'] not in denied and sharing.get(u['id'],True);received=u['id'] in delivered or known
  d={'id':u['id'],'nome':u['nome'],'estado':'visualizada' if seen else 'recebida' if received else 'enviada','horario_anterior_indisponivel':bool(seen and read.get(u['id']) is None)}
  if caps['horarios']:d.update(lida_em=read.get(u['id']) if seen else None,recebida_em=delivered.get(u['id']))
  people.append(d)
 seen=sum(p['estado']=='visualizada' for p in people);received=sum(p['estado'] in ('recebida','visualizada') for p in people)
 return {'estado':'visualizada' if people and seen==len(people) else 'recebida' if people and received==len(people) else 'enviada','visualizadas':seen,'total':len(people),'horarios_permitidos':caps['horarios'],'pessoas':people}
def receipt(store,actor,mid):
 import chat_interno as chat
 with store.lock,store.connect() as db:
  chat.schema(db);m=db.execute('SELECT * FROM chat_messages WHERE id=?',(mid,)).fetchone()
  if not m or not db.execute('SELECT 1 FROM chat_members WHERE room_id=? AND user_id=?',(m['room_id'],actor['id'])).fetchone():raise legal.AppError('Mensagem indisponível.',403)
  result=receipt_db(db,actor,m)
  if result is None:raise legal.AppError('Você não pode consultar estas confirmações.',403)
  return result

def previews(store,actor):
 import chat_interno as chat
 import chat_preferencias as prefs
 with store.lock,store.connect() as db:
  chat.schema(db);caps=effective(db,actor['id']);p=prefs.get_db(db,actor['id'])
  if not caps['previas'] or p.get('ocultar_historico'):raise legal.AppError('Prévias desativadas nas configurações.',403)
  rows=db.execute('''SELECT m.id,m.room_id,m.texto,m.criado,u.nome,r.titulo FROM chat_messages m
   JOIN chat_members cm ON cm.room_id=m.room_id AND cm.user_id=? JOIN chat_rooms r ON r.id=m.room_id
   JOIN users u ON u.id=m.sender_id WHERE m.sender_id!=? AND '''+UNREAD+''' AND NOT EXISTS(SELECT 1 FROM chat_mutes mt WHERE mt.room_id=m.room_id AND mt.user_id=?) ORDER BY m.id DESC LIMIT 5''',(actor['id'],actor['id'],actor['id'],actor['id'],actor['id'])).fetchall()
  return {'itens':[{**dict(r),'texto':r['texto'][:160] or 'Anexo recebido'} for r in rows]}
