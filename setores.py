"""Office sector registry, private sector groups and explicit secretariat capability."""
import unicodedata
import juridico as legal

SETORES=(('contratacao','Contratação'),('arquivo','Arquivo'),('acordos','Acordos'),('financeiro','Financeiro'),('cobranca','Cobrança'),('previdenciario','Previdenciário'),('controladoria','Controladoria'),('consignados','Consignados'),('bancario','Bancário'),('civel','Cível'),('relacionamento','Relacionamento'),('secretarias','Secretarias'),('rh','RH'),('gerencia','Gerência'),('ti','TI'))

def normalized(value):return ''.join(c for c in unicodedata.normalize('NFKD',str(value).lower()) if c.isalnum())

def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS office_sectors(codigo TEXT PRIMARY KEY,nome TEXT NOT NULL,room_id INTEGER UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS office_capabilities(user_id INTEGER PRIMARY KEY,secretaria INTEGER NOT NULL DEFAULT 0,alterado_por INTEGER,alterado_em TEXT);
    CREATE TABLE IF NOT EXISTS calendar_sectors(calendar_id INTEGER PRIMARY KEY,codigo TEXT NOT NULL,criado_por INTEGER);
    CREATE TABLE IF NOT EXISTS office_defaults(chave TEXT PRIMARY KEY,valor TEXT NOT NULL);''')

def can_create_db(db,actor):
    if actor['role']=='administrador':return True
    if actor['role']=='leitor':return False
    return bool(db.execute('SELECT 1 FROM office_capabilities WHERE user_id=? AND secretaria=1',(actor['id'],)).fetchone())

def bootstrap(store,with_calendar=True):
    import chat_interno as chat,chat_recursos as features
    with store.lock,store.connect() as db:
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():return
        chat.schema(db);schema(db);owner=features.owner(db)
        existing={normalized(r['titulo']):r['id'] for r in db.execute("SELECT id,titulo FROM chat_rooms WHERE tipo='grupo' ORDER BY id DESC")}
        aliases={'rh':['rh','recursoshumanos'],'secretarias':['secretarias','secretaria']}
        for code,name in SETORES:
            if db.execute('SELECT 1 FROM office_sectors WHERE codigo=?',(code,)).fetchone():continue
            room=next((existing[k] for k in aliases.get(code,[normalized(name)]) if k in existing),None)
            if room is None:
                room=db.execute("INSERT INTO chat_rooms(titulo,tipo,owner_id,criado) VALUES(?,'grupo',?,?)",(name,owner,legal.now())).lastrowid
                db.execute('INSERT INTO chat_members(room_id,user_id) VALUES(?,?)',(room,owner))
            db.execute('INSERT INTO office_sectors VALUES(?,?,?)',(code,name,room))
            db.execute('INSERT OR IGNORE INTO chat_room_office(room_id,office_id,setor) VALUES(?,NULL,1)',(room,))
            db.execute('UPDATE chat_room_office SET setor=1 WHERE room_id=?',(room,))
        if with_calendar:
            import calendario
            calendario.schema(db)
            if not db.execute("SELECT 1 FROM office_defaults WHERE chave='agenda_relacionamento'").fetchone():
                row=db.execute("SELECT id FROM calendars WHERE owner_id IS NULL AND nome='Relacionamento — Agendamentos' ORDER BY id LIMIT 1").fetchone()
                cid=row[0] if row else db.execute('INSERT INTO calendars(nome,criado) VALUES(?,?)',('Relacionamento — Agendamentos',legal.now())).lastrowid
                db.execute('INSERT OR IGNORE INTO calendar_sectors VALUES(?,?,?)',(cid,'relacionamento',owner))
                # Only seed grants on a new agenda; do not reset access to an existing one.
                if not row:
                    for code,permission in [('relacionamento','ver'),('secretarias','agendar')]:
                        room=db.execute('SELECT room_id FROM office_sectors WHERE codigo=?',(code,)).fetchone()[0]
                        db.execute('INSERT OR IGNORE INTO calendar_grants VALUES(?,?,?,?)',(cid,'setor',room,permission))
                db.execute('INSERT INTO office_defaults VALUES(?,?)',('agenda_relacionamento',str(cid)))

def access(store,actor):
    bootstrap(store)
    with store.lock,store.connect() as db:return {'pode_criar_agenda_relacionamento':can_create_db(db,actor),'administrador':actor['role']=='administrador'}

def directory(store,actor):
    import chat_recursos as features
    bootstrap(store)
    with store.lock,store.connect() as db:
        owner=actor['id']==features.owner(db)
        rows=[]
        for r in db.execute('SELECT s.*,r.titulo,r.owner_id AS proprietario_id FROM office_sectors s JOIN chat_rooms r ON r.id=s.room_id ORDER BY s.nome'):
            item=dict(r)
            if owner:item['membros']=[p[0] for p in db.execute('SELECT user_id FROM chat_members WHERE room_id=?',(r['room_id'],))]
            rows.append(item)
        result={'setores':rows,'pode_organizar_grupos':owner and actor['role']!='leitor','pode_gerenciar_permissoes':actor['role']=='administrador'}
        if owner or actor['role']=='administrador':result['usuarios']=[dict(r) for r in db.execute('SELECT u.id,u.nome,u.role,COALESCE(c.secretaria,0) AS secretaria FROM users u LEFT JOIN office_capabilities c ON c.user_id=u.id WHERE u.ativo=1 ORDER BY u.nome')]
        return result

def grant(store,actor,body):
    if actor['role']!='administrador':raise legal.AppError('Só administradores concedem a permissão de secretaria.',403)
    uid=body.get('user_id');enabled=body.get('secretaria')
    if type(uid)is not int or type(enabled)is not bool:raise legal.AppError('Permissão inválida.')
    with store.lock,store.connect() as db:
        schema(db)
        if not db.execute('SELECT 1 FROM users WHERE id=? AND ativo=1',(uid,)).fetchone():raise legal.AppError('Usuário não encontrado.',404)
        db.execute('INSERT OR REPLACE INTO office_capabilities VALUES(?,?,?,?)',(uid,int(enabled),actor['id'],legal.now()))
        store.audit(db,actor,'permissao_secretaria','usuario',uid,after={'secretaria':enabled})
    return {'ok':True}

def members(store,actor,code,ids):
    import chat_recursos as features,chat_interno as chat
    bootstrap(store)
    with store.lock,store.connect() as db:
        if actor['id']!=features.owner(db) or actor['role']=='leitor':raise legal.AppError('Só o proprietário do chat organiza os integrantes dos setores.',403)
        row=db.execute('SELECT room_id FROM office_sectors WHERE codigo=?',(code,)).fetchone()
        if not row:raise legal.AppError('Setor não encontrado.',404)
        rid=row[0]
    return chat.members(store,actor,rid,ids)
