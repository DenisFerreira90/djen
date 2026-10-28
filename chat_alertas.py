"""Feed autenticado de novas mensagens para avisos, sem conteúdo sensível nas prévias."""
import juridico as legal
import chat_interno as chat
import chat_recursos as ext
import chat_visualizacao as visual

def feed(store,actor,after=None):
 if after is not None and (type(after)is not int or after<0):raise legal.AppError('Cursor inválido.')
 with store.lock,store.connect() as db:
  chat.schema(db);ext.ensure_general(db)
  maximum=db.execute('SELECT COALESCE(MAX(id),0) FROM chat_messages').fetchone()[0]
  if after is None or after>maximum:
   cursor=db.execute('SELECT COALESCE(MAX(id),0) FROM chat_messages').fetchone()[0]
   return {'cursor':cursor,'itens':[],'tem_mais':False}
  rows=db.execute('''SELECT m.id,m.room_id,m.sender_id,r.titulo,r.tipo,u.nome,
    EXISTS(SELECT 1 FROM chat_mutes t WHERE t.room_id=m.room_id AND t.user_id=?) AS silenciado,
    cm.last_read FROM chat_messages m JOIN chat_rooms r ON r.id=m.room_id
    JOIN users u ON u.id=m.sender_id JOIN chat_members cm ON cm.room_id=m.room_id AND cm.user_id=?
    WHERE m.id>? AND '''+visual.UNREAD+''' ORDER BY m.id LIMIT 101''',(actor['id'],actor['id'],after,actor['id'],actor['id'])).fetchall()
  more=len(rows)>100;rows=rows[:100];items=[]
  for r in rows:
   if r['sender_id']==actor['id'] or r['silenciado']:continue
   d={k:r[k] for k in ('id','room_id','nome','titulo')}
   if r['tipo']=='direta':d['titulo']=r['nome']
   items.append(d)
  # Cursor avança também para mensagens próprias, lidas ou silenciadas.
  cursor=rows[-1]['id'] if more else db.execute('SELECT COALESCE(MAX(id),0) FROM chat_messages').fetchone()[0]
  return {'cursor':max(after,cursor),'itens':items,'tem_mais':more}
