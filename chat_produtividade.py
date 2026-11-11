"""Ferramentas do chat; referências sempre sujeitas à participação e ao histórico permitido."""
import datetime as dt
import juridico as legal


def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS chat_history_policy(room_id INTEGER PRIMARY KEY,policy TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_history_access(room_id INTEGER,user_id INTEGER,after_id INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(room_id,user_id));
    CREATE TABLE IF NOT EXISTS chat_personal_notes(id INTEGER PRIMARY KEY,user_id INTEGER,titulo TEXT,texto TEXT,atualizado TEXT);
    CREATE TABLE IF NOT EXISTS chat_saved(user_id INTEGER,message_id INTEGER,criado TEXT NOT NULL,PRIMARY KEY(user_id,message_id));
    CREATE TABLE IF NOT EXISTS chat_tasks(id INTEGER PRIMARY KEY,message_id INTEGER,creator_id INTEGER,assignee_id INTEGER,titulo TEXT,due TEXT,processo TEXT,status TEXT,criado TEXT);
    CREATE TABLE IF NOT EXISTS chat_ack_requests(message_id INTEGER PRIMARY KEY,creator_id INTEGER,criado TEXT);
    CREATE TABLE IF NOT EXISTS chat_ack_targets(message_id INTEGER,user_id INTEGER,confirmed_at TEXT,PRIMARY KEY(message_id,user_id));
    CREATE INDEX IF NOT EXISTS chat_tasks_assignee ON chat_tasks(assignee_id,status,due);
    ''')


def cutoff(db, uid, rid):
    row=db.execute('SELECT after_id FROM chat_history_access WHERE room_id=? AND user_id=?',(rid,uid)).fetchone()
    return row[0] if row else 0


def visible(db, uid, rid, mid):
    return mid>cutoff(db,uid,rid)


def history(store,actor,rid,body=None):
    import chat_interno as chat
    import chat_recursos as features
    with store.lock,store.connect() as db:
        chat.schema(db);room=chat.access(store,db,actor,rid)
        if room['tipo'] not in ('grupo','comunicado'):raise legal.AppError('Esta regra é para grupos e avisos restritos.')
        if body is not None:
            if actor['id']!=features.owner(db):raise legal.AppError('Só o proprietário define o histórico de novos integrantes.',403)
            if body.get('politica') not in ('completo','apos_entrada'):raise legal.AppError('Política de histórico inválida.')
            db.execute('INSERT OR REPLACE INTO chat_history_policy VALUES(?,?)',(rid,body['politica']))
            store.audit(db,actor,'politica_historico_chat','chat',rid,after=body)
        row=db.execute('SELECT policy FROM chat_history_policy WHERE room_id=?',(rid,)).fetchone()
        return {'politica':row[0] if row else 'completo','apos_evento':cutoff(db,actor['id'],rid)}


def new_members(db,rid,old_ids,new_ids):
    policy=db.execute('SELECT policy FROM chat_history_policy WHERE room_id=?',(rid,)).fetchone()
    boundary=db.execute('SELECT COALESCE(MAX(id),0) FROM chat_messages WHERE room_id=?',(rid,)).fetchone()[0]
    for uid in set(new_ids)-set(old_ids):
        value=boundary if policy and policy[0]=='apos_entrada' else 0
        db.execute('INSERT OR REPLACE INTO chat_history_access VALUES(?,?,?)',(rid,uid,value))
        # Old unread messages must not appear in launcher, notification feed or previews.
        if value:db.execute('INSERT OR REPLACE INTO chat_read_baseline VALUES(?,?,?)',(rid,uid,value))


def message(store,actor,mid,body):
    import chat_recursos as features
    import chat_interno as chat
    with store.lock,store.connect() as db:
        chat.schema(db);m=features.message(db,actor,mid);action=body.get('acao')
        if action=='salvar':
            db.execute('INSERT OR IGNORE INTO chat_saved VALUES(?,?,?)',(actor['id'],mid,legal.now()))
        elif action=='remover_salvo':db.execute('DELETE FROM chat_saved WHERE user_id=? AND message_id=?',(actor['id'],mid))
        elif action=='demanda':
            chat.editor(actor);uid=body.get('responsavel_id');due=str(body.get('prazo',''));title=str(body.get('titulo','')).strip();process=str(body.get('processo','')).strip()
            if type(uid)is not int or not db.execute('SELECT 1 FROM chat_members cm JOIN users u ON u.id=cm.user_id WHERE cm.room_id=? AND cm.user_id=? AND u.ativo=1',(m['room_id'],uid)).fetchone():raise legal.AppError('Escolha um responsável participante desta conversa.')
            try:dt.date.fromisoformat(due)
            except ValueError:raise legal.AppError('Informe a data do prazo.')
            if not title or len(title)>200 or len(process)>100:raise legal.AppError('Título ou processo inválido.')
            tid=db.execute("INSERT INTO chat_tasks(message_id,creator_id,assignee_id,titulo,due,processo,status,criado) VALUES(?,?,?,?,?,?,'pendente',?)",(mid,actor['id'],uid,title,due,process,legal.now())).lastrowid
            store.audit(db,actor,'criar_demanda_chat','chat_demanda',tid,after={'mensagem_id':mid,'responsavel_id':uid,'prazo':due})
            return {'ok':True,'id':tid}
        elif action=='solicitar_ciencia':
            chat.editor(actor)
            if not features.manager(db,actor['id']) or m['tipo'] not in ('geral','comunicado'):raise legal.AppError('A ciência é solicitada pela administração em avisos e no geral.',403)
            created=db.execute('INSERT OR IGNORE INTO chat_ack_requests VALUES(?,?,?)',(mid,actor['id'],legal.now())).rowcount
            if created:
                for r in db.execute('SELECT cm.user_id FROM chat_members cm JOIN users u ON u.id=cm.user_id WHERE cm.room_id=? AND u.ativo=1 AND cm.user_id!=?',(m['room_id'],actor['id'])).fetchall():
                    if visible(db,r[0],m['room_id'],mid):db.execute('INSERT INTO chat_ack_targets VALUES(?,?,NULL)',(mid,r[0]))
            store.audit(db,actor,'solicitar_ciencia_chat','chat',mid)
        elif action=='ciente':
            if not db.execute('SELECT 1 FROM chat_ack_targets WHERE message_id=? AND user_id=?',(mid,actor['id'])).fetchone():raise legal.AppError('Você não é destinatário desta confirmação.',403)
            db.execute('UPDATE chat_ack_targets SET confirmed_at=COALESCE(confirmed_at,?) WHERE message_id=? AND user_id=?',(legal.now(),mid,actor['id']))
            store.audit(db,actor,'confirmar_ciencia_chat','chat',mid)
        else:raise legal.AppError('Ação inválida.')
    return {'ok':True}


def enrich(db,actor,d):
    if not db.execute('SELECT 1 FROM chat_ack_requests WHERE message_id=?',(d['id'],)).fetchone():return
    rows=[dict(r) for r in db.execute('SELECT t.user_id,u.nome,t.confirmed_at FROM chat_ack_targets t JOIN users u ON u.id=t.user_id WHERE t.message_id=?',(d['id'],))]
    mine=next((r for r in rows if r['user_id']==actor['id']),None)
    import chat_recursos as features
    d['ciencia']={'total':len(rows),'confirmados':sum(bool(r['confirmed_at']) for r in rows),'solicitada_para_mim':mine is not None,'minha_confirmacao':mine['confirmed_at'] if mine else None}
    if features.manager(db,actor['id']):d['ciencia']['pessoas']=rows


def list_items(store,actor,kind,filters=None):
    import chat_interno as chat
    import chat_recursos as features
    filters=filters or {}
    with store.lock,store.connect() as db:
        chat.schema(db)
        args=[actor['id']];query='''SELECT m.id,m.room_id,m.sender_id,m.texto,m.criado,u.nome,r.titulo FROM chat_messages m JOIN chat_members cm ON cm.room_id=m.room_id AND cm.user_id=? JOIN chat_rooms r ON r.id=m.room_id JOIN users u ON u.id=m.sender_id WHERE m.id>COALESCE((SELECT ha.after_id FROM chat_history_access ha WHERE ha.room_id=m.room_id AND ha.user_id=cm.user_id),0)'''
        if kind=='salvos':query+=' AND EXISTS(SELECT 1 FROM chat_saved s WHERE s.message_id=m.id AND s.user_id=cm.user_id)'
        elif kind!='busca':raise legal.AppError('Lista inválida.')
        for key,column in [('pessoa','m.sender_id'),('conversa','m.room_id')]:
            value=filters.get(key)
            if value:
                try:value=int(value)
                except (ValueError,TypeError):raise legal.AppError('Filtro inválido.')
                query+=' AND '+column+'=?';args.append(value)
        for key,op in [('inicio','>='),('fim','<=')]:
            value=filters.get(key)
            if value:
                try:dt.date.fromisoformat(value)
                except ValueError:raise legal.AppError('Data inválida.')
                query+=' AND substr(m.criado,1,10)'+op+'?';args.append(value)
        if filters.get('inicio') and filters.get('fim') and filters['inicio']>filters['fim']:raise legal.AppError('A data inicial deve ser anterior à final.')
        term=str(filters.get('texto','')).strip()
        if term:
            query+=' AND (instr(lower(m.texto),lower(?))>0 OR EXISTS(SELECT 1 FROM chat_files f WHERE f.message_id=m.id AND instr(lower(f.nome),lower(?))>0))';args.extend([term[:200],term[:200]])
        if filters.get('anexos')=='1':query+=' AND EXISTS(SELECT 1 FROM chat_files f WHERE f.message_id=m.id)'
        rows=db.execute(query+' ORDER BY m.id DESC LIMIT 101',args).fetchall();items=[]
        for row in rows[:100]:
            d=dict(row);d['anexos']=[dict(f) for f in db.execute('SELECT id,nome FROM chat_files WHERE message_id=?',(d['id'],))];items.append(d)
        return {'itens':items,'tem_mais':len(rows)>100}


def tasks(store,actor,body=None):
    import chat_interno as chat
    import chat_recursos as features
    with store.lock,store.connect() as db:
        chat.schema(db)
        if body is not None:
            chat.editor(actor);tid=body.get('id');status=body.get('status')
            task=db.execute('SELECT * FROM chat_tasks WHERE id=?',(tid,)).fetchone()
            if not task:raise legal.AppError('Demanda inexistente.',404)
            features.message(db,actor,task['message_id'])
            if actor['id'] not in (task['creator_id'],task['assignee_id']):raise legal.AppError('Somente solicitante ou responsável altera a demanda.',403)
            if status not in ('pendente','concluida'):raise legal.AppError('Situação inválida.')
            db.execute('UPDATE chat_tasks SET status=? WHERE id=?',(status,tid));store.audit(db,actor,'atualizar_demanda_chat','chat_demanda',tid,after={'status':status})
        rows=db.execute('SELECT t.*,u.nome AS responsavel FROM chat_tasks t JOIN users u ON u.id=t.assignee_id WHERE t.creator_id=? OR t.assignee_id=? ORDER BY t.status DESC,t.due,t.id DESC',(actor['id'],actor['id'])).fetchall();result=[]
        for row in rows:
            try:source=features.message(db,actor,row['message_id'])
            except legal.AppError:continue
            result.append({**dict(row),'room_id':source['room_id'],'contexto':source['texto']})
        return {'itens':result}


def notes(store,actor,body=None):
    """Bloco pessoal no servidor; nunca listado para colegas ou administradores."""
    import chat_interno as chat
    with store.lock,store.connect() as db:
        chat.schema(db)
        if body is not None:
            title=str(body.get('titulo','')).strip();text=str(body.get('texto','')).strip();nid=body.get('id')
            if nid is not None and (type(nid)is not int or not db.execute('SELECT 1 FROM chat_personal_notes WHERE id=? AND user_id=?',(nid,actor['id'])).fetchone()):raise legal.AppError('Nota indisponível.',403)
            if body.get('remover') is True:
                db.execute('DELETE FROM chat_personal_notes WHERE id=? AND user_id=?',(nid,actor['id']))
            else:
                if not title or len(title)>200 or not text or len(text)>10000:raise legal.AppError('Informe título (até 200) e texto (até 10 mil caracteres).')
                if nid is None:db.execute('INSERT INTO chat_personal_notes(user_id,titulo,texto,atualizado) VALUES(?,?,?,?)',(actor['id'],title,text,legal.now()))
                else:db.execute('UPDATE chat_personal_notes SET titulo=?,texto=?,atualizado=? WHERE id=? AND user_id=?',(title,text,legal.now(),nid,actor['id']))
            store.audit(db,actor,'alterar_nota_pessoal_chat','chat_nota',nid or 'nova')
        return {'itens':[dict(r) for r in db.execute('SELECT id,titulo,texto,atualizado FROM chat_personal_notes WHERE user_id=? ORDER BY atualizado DESC,id DESC',(actor['id'],))]}
