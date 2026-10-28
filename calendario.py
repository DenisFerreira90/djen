"""Calendários pessoais e compartilhados com delegação explícita por usuário/setor."""
import datetime as dt
import json
import juridico as legal

RANK={'ver':1,'agendar':2,'gerenciar':3}

def schema(db):
    import chat_interno
    chat_interno.schema(db)
    db.executescript('''CREATE TABLE IF NOT EXISTS calendars(id INTEGER PRIMARY KEY,nome TEXT NOT NULL,owner_id INTEGER UNIQUE,criado TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS calendar_grants(calendar_id INTEGER,tipo TEXT,principal_id INTEGER,papel TEXT,PRIMARY KEY(calendar_id,tipo,principal_id));
    CREATE TABLE IF NOT EXISTS calendar_events(id INTEGER PRIMARY KEY,calendar_id INTEGER NOT NULL,titulo TEXT NOT NULL,inicio TEXT NOT NULL,fim TEXT NOT NULL,responsavel_id INTEGER NOT NULL,cliente TEXT NOT NULL,contato TEXT NOT NULL,processo TEXT NOT NULL,local TEXT NOT NULL,observacoes TEXT NOT NULL,status TEXT NOT NULL,criado_por INTEGER NOT NULL,atualizado_por INTEGER NOT NULL,atualizado TEXT NOT NULL,versao INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS calendar_date ON calendar_events(calendar_id,inicio,fim);
    ''')
    for u in db.execute('SELECT id,nome FROM users WHERE ativo=1').fetchall():db.execute('INSERT OR IGNORE INTO calendars(nome,owner_id,criado) VALUES(?,?,?)',('Agenda de '+u['nome'],u['id'],legal.now()))


def role(db,actor,cid):
    calendar=db.execute('SELECT * FROM calendars WHERE id=?',(cid,)).fetchone()
    if not calendar:raise legal.AppError('Calendário não encontrado.',404)
    if actor['role']=='administrador' or calendar['owner_id']==actor['id']:return 'gerenciar'
    grants=db.execute("SELECT papel FROM calendar_grants g WHERE calendar_id=? AND ((tipo='usuario' AND principal_id=?) OR (tipo='setor' AND EXISTS(SELECT 1 FROM chat_members m WHERE m.room_id=g.principal_id AND m.user_id=?)))",(cid,actor['id'],actor['id'])).fetchall()
    return max((r[0] for r in grants),key=lambda p:RANK[p],default=None)


def require(db,actor,cid,minimum):
    permission=role(db,actor,cid)
    if not permission or RANK[permission]<RANK[minimum]:raise legal.AppError('Você não tem permissão para esta agenda.',403)
    if minimum!='ver' and actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
    return permission


def calendars(store,actor):
    with store.lock,store.connect() as db:
        schema(db);out=[]
        for c in db.execute('SELECT * FROM calendars ORDER BY nome').fetchall():
            p=role(db,actor,c['id'])
            if p:out.append({**dict(c),'permissao':'ver' if actor['role']=='leitor' else p})
        return out


def create(store,actor,name):
    if actor['role']!='administrador':raise legal.AppError('Só administradores criam calendários compartilhados.',403)
    name=str(name).strip()
    if not 1<=len(name)<=120:raise legal.AppError('Informe o nome do calendário.')
    with store.lock,store.connect() as db:
        schema(db);cur=db.execute('INSERT INTO calendars(nome,criado) VALUES(?,?)',(name,legal.now()));cid=cur.lastrowid;store.audit(db,actor,'criar_calendario','calendario',cid,after={'nome':name})
    return {'id':cid}


def grants(store,actor,cid,items=None):
    with store.lock,store.connect() as db:
        schema(db);require(db,actor,cid,'gerenciar')
        if items is not None:
            if not isinstance(items,list) or len(items)>200:raise legal.AppError('Permissões inválidas.')
            parsed=[]
            for item in items:
                typ=item.get('tipo');uid=item.get('principal_id');permission=item.get('papel')
                if typ not in ('usuario','setor') or type(uid)is not int or permission not in RANK:raise legal.AppError('Permissão inválida.')
                valid=db.execute('SELECT 1 FROM users WHERE id=? AND ativo=1' if typ=='usuario' else "SELECT 1 FROM chat_rooms WHERE id=? AND tipo='grupo'",(uid,)).fetchone()
                if not valid:raise legal.AppError('Usuário ou setor não encontrado.')
                parsed.append((cid,typ,uid,permission))
            if len({(i[1],i[2]) for i in parsed})!=len(parsed):raise legal.AppError('Permissão duplicada para o mesmo usuário ou setor.')
            db.execute('DELETE FROM calendar_grants WHERE calendar_id=?',(cid,));db.executemany('INSERT INTO calendar_grants VALUES(?,?,?,?)',parsed);store.audit(db,actor,'delegar_agenda','calendario',cid,after={'permissoes':items})
        return {'permissoes':[dict(r) for r in db.execute('SELECT * FROM calendar_grants WHERE calendar_id=?',(cid,))],'setores':[dict(r) for r in db.execute("SELECT id,titulo FROM chat_rooms WHERE tipo='grupo' ORDER BY titulo")]}


def timestamp(value):
    try:
        d=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if d.tzinfo is None:raise ValueError()
        return d.astimezone(dt.timezone.utc).isoformat(timespec='seconds')
    except (ValueError,TypeError):raise legal.AppError('Informe data e horário com fuso horário.')


def events(store,actor,cid,start,end):
    start=timestamp(start);end=timestamp(end)
    if end<=start or dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(start)>dt.timedelta(days=93):raise legal.AppError('Consulte um intervalo de até 93 dias.')
    with store.lock,store.connect() as db:
        schema(db);require(db,actor,cid,'ver')
        rows=db.execute('SELECT e.*,u.nome AS responsavel FROM calendar_events e JOIN users u ON u.id=e.responsavel_id WHERE calendar_id=? AND inicio<? AND fim>? ORDER BY inicio LIMIT 1001',(cid,end,start)).fetchall()
        return {'itens':[dict(r) for r in rows[:1000]],'limite_atingido':len(rows)>1000}


def save(store,actor,cid,body,eid=None):
    start=timestamp(body.get('inicio'));end=timestamp(body.get('fim'))
    if end<=start or dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(start)>dt.timedelta(days=7):raise legal.AppError('O fim precisa ser posterior ao início, com duração de até sete dias.')
    title=str(body.get('titulo','')).strip();uid=body.get('responsavel_id');state=body.get('status','marcado')
    if not 1<=len(title)<=200 or type(uid)is not int or state not in ('marcado','confirmado','realizado','cancelado'):raise legal.AppError('Confira título, responsável e situação.')
    extra={k:str(body.get(k,'')).strip() for k in ('cliente','contato','processo','local','observacoes')}
    if any(len(v)>4000 for v in extra.values()):raise legal.AppError('Campo excede o limite de 4 mil caracteres.')
    with store.lock,store.connect() as db:
        schema(db);db.commit();db.execute('BEGIN IMMEDIATE');require(db,actor,cid,'agendar');before=None
        if eid:
            row=db.execute('SELECT * FROM calendar_events WHERE id=? AND calendar_id=?',(eid,cid)).fetchone()
            if not row:raise legal.AppError('Compromisso não encontrado.',404)
            before=dict(row)
            if type(body.get('versao'))is not int or body['versao']!=row['versao']:raise legal.AppError('Este compromisso mudou. Reabra antes de salvar.',409)
        user=db.execute('SELECT * FROM users WHERE id=? AND ativo=1',(uid,)).fetchone()
        if not user:raise legal.AppError('Responsável inválido.')
        if not role(db,dict(user),cid):raise legal.AppError('O responsável precisa ter acesso a este calendário.')
        overlap=db.execute("SELECT id FROM calendar_events WHERE responsavel_id=? AND status IN ('marcado','confirmado') AND inicio<? AND fim>? AND id!=?",(uid,end,start,eid or 0)).fetchone()
        if state in ('marcado','confirmado') and overlap:raise legal.AppError('O responsável já tem compromisso nesse horário. Escolha outro horário.',409)
        values=(title,start,end,uid,extra['cliente'],extra['contato'],extra['processo'],extra['local'],extra['observacoes'],state,actor['id'],legal.now())
        if eid:db.execute('UPDATE calendar_events SET titulo=?,inicio=?,fim=?,responsavel_id=?,cliente=?,contato=?,processo=?,local=?,observacoes=?,status=?,atualizado_por=?,atualizado=?,versao=versao+1 WHERE id=?',(*values,eid))
        else:
            cur=db.execute('INSERT INTO calendar_events(calendar_id,titulo,inicio,fim,responsavel_id,cliente,contato,processo,local,observacoes,status,atualizado_por,atualizado,criado_por) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,*values,actor['id']));eid=cur.lastrowid
        after=dict(db.execute('SELECT * FROM calendar_events WHERE id=?',(eid,)).fetchone());store.audit(db,actor,'alterar_compromisso' if before else 'marcar_compromisso','calendario',eid,before=before,after=after)
        return after
