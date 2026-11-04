"""Owner-managed TOTP vault. Secrets stay encrypted on the server; codes are POST-only."""
import base64,contextlib,hashlib,hmac,json,os,re,sqlite3,struct,threading,time
from urllib.parse import urlsplit,parse_qs,unquote
import juridico as legal
from email_alertas import crypt
LOCK=threading.RLock()


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS twofa_owner(id INTEGER PRIMARY KEY CHECK(id=1),user_id INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS twofa_grants(user_id INTEGER PRIMARY KEY,allowed INTEGER NOT NULL,granted_by INTEGER,updated TEXT)')
    if not db.execute('SELECT 1 FROM twofa_owner WHERE id=1').fetchone():
        prior=db.execute("SELECT 1 FROM sqlite_master WHERE name='chat_control'").fetchone()
        row=db.execute('SELECT owner_id FROM chat_control WHERE id=1').fetchone() if prior else None
        row=row or db.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()
        if row:db.execute('INSERT INTO twofa_owner VALUES(1,?)',(row[0],))


def permission(store,actor):
    with store.lock,store.connect() as db:
        schema(db);owner=db.execute('SELECT user_id FROM twofa_owner WHERE id=1').fetchone()
        owned=bool(owner and owner[0]==actor['id'])
        allowed=owned or bool(db.execute('SELECT 1 FROM twofa_grants WHERE user_id=? AND allowed=1',(actor['id'],)).fetchone())
    return {'proprietario':owned,'permitido':allowed,'protecao_disponivel':os.name=='nt'}


def require(store,actor,owner=False):
    access=permission(store,actor)
    if not access['proprietario' if owner else 'permitido']:
        raise legal.AppError('Acesso ao 2FA não autorizado pela conta proprietária.',403)
    return access


def vault_path(store):return store.path.parent/'2fa'/'cofre.sqlite3'


@contextlib.contextmanager
def vault(store):
    path=vault_path(store);path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=10);c.row_factory=sqlite3.Row
    try:
        c.execute('CREATE TABLE IF NOT EXISTS tokens(id INTEGER PRIMARY KEY,nome TEXT NOT NULL,conta TEXT NOT NULL,secret BLOB NOT NULL,digits INTEGER NOT NULL,period INTEGER NOT NULL,algorithm TEXT NOT NULL,ativo INTEGER NOT NULL DEFAULT 1,criado TEXT NOT NULL)')
        with c:yield c
    finally:c.close()


def parse_secret(value):
    value=str(value).strip()
    digits,period,algorithm=6,30,'SHA1'
    if value.lower().startswith('otpauth://'):
        url=urlsplit(value)
        if url.scheme!='otpauth' or url.netloc!='totp':raise legal.AppError('Somente autenticadores TOTP são aceitos.')
        query=parse_qs(url.query)
        if any(len(v)!=1 for v in query.values()):raise legal.AppError('Cadastro TOTP inválido.')
        value=query.get('secret',[''])[0]
        try:digits=int(query.get('digits',['6'])[0]);period=int(query.get('period',['30'])[0])
        except ValueError:raise legal.AppError('Parâmetros do autenticador inválidos.')
        algorithm=query.get('algorithm',['SHA1'])[0].upper()
    secret=re.sub(r'\s+','',value).upper().rstrip('=')
    if not re.fullmatch('[A-Z2-7]{16,256}',secret) or digits not in (6,8) or period not in (30,60) or algorithm not in ('SHA1','SHA256','SHA512'):raise legal.AppError('Informe a chave Base32 do autenticador ou URI otpauth TOTP válida; não o código temporário.')
    try:raw=base64.b32decode(secret+'='*((-len(secret))%8))
    except Exception:raise legal.AppError('Chave do autenticador inválida.')
    return raw,digits,period,algorithm


def totp(secret,at,digits=6,period=30,algorithm='SHA1'):
    digest=hmac.new(secret,struct.pack('>Q',int(at)//period),getattr(hashlib,algorithm.lower())).digest()
    offset=digest[-1]&15;value=(struct.unpack('>I',digest[offset:offset+4])[0]&0x7fffffff)%(10**digits)
    return str(value).zfill(digits)


def settings(store,actor):
    require(store,actor,True)
    with store.lock,store.connect() as db:
        schema(db);users=[dict(r) for r in db.execute('SELECT u.id,u.nome,COALESCE(g.allowed,0) AS autorizado FROM users u LEFT JOIN twofa_grants g ON g.user_id=u.id WHERE u.ativo=1 ORDER BY u.nome')]
        owner=db.execute('SELECT user_id FROM twofa_owner WHERE id=1').fetchone()[0]
    with LOCK,vault(store) as c:tokens=[dict(r) for r in c.execute('SELECT id,nome,conta,ativo FROM tokens ORDER BY nome')]
    return {'usuarios':users,'owner_id':owner,'autenticadores':tokens}


def grant(store,actor,body):
    require(store,actor,True);uid=body.get('user_id');allowed=body.get('autorizado')
    if type(uid)is not int or type(allowed)is not bool:raise legal.AppError('Permissão 2FA inválida.')
    with store.lock,store.connect() as db:
        schema(db)
        if uid==actor['id']:raise legal.AppError('A conta proprietária mantém seu acesso.')
        if not db.execute('SELECT 1 FROM users WHERE id=? AND ativo=1',(uid,)).fetchone():raise legal.AppError('Usuário não encontrado.',404)
        db.execute('INSERT OR REPLACE INTO twofa_grants VALUES(?,?,?,?)',(uid,int(allowed),actor['id'],legal.now()))
        store.audit(db,actor,'permissao_2fa','usuario',uid,after={'autorizado':allowed})
    return {'ok':True}


def add(store,actor,body):
    require(store,actor,True)
    name=str(body.get('nome','')).strip();account=str(body.get('conta','')).strip()
    if not 1<=len(name)<=100 or not 1<=len(account)<=100:raise legal.AppError('Informe tribunal e identificação da conta, até 100 caracteres cada.')
    raw,digits,period,algorithm=parse_secret(body.get('chave',''))
    current=time.time();code=str(body.get('confirmacao','')).strip()
    if not re.fullmatch(r'\d{'+str(digits)+'}',code) or not any(hmac.compare_digest(totp(raw,current+delta*period,digits,period,algorithm),code) for delta in (-1,0,1)):raise legal.AppError('Código de confirmação não confere. Verifique a chave e o relógio do servidor.')
    # Fail closed: DPAPI refuses storage outside the supported Windows account.
    encrypted=crypt(raw)
    with LOCK,vault(store) as c:
        if c.execute('SELECT COUNT(*) FROM tokens WHERE ativo=1').fetchone()[0]>=100:raise legal.AppError('Limite de 100 autenticadores ativos.')
        key=c.execute('INSERT INTO tokens(nome,conta,secret,digits,period,algorithm,criado) VALUES(?,?,?,?,?,?,?)',(name,account,encrypted,digits,period,algorithm,legal.now())).lastrowid
    with store.lock,store.connect() as db:store.audit(db,actor,'cadastrar_autenticador','2fa',key,after={'tribunal':name})
    return {'id':key}


def disable(store,actor,key):
    require(store,actor,True)
    with LOCK,vault(store) as c:c.execute('UPDATE tokens SET ativo=0,secret=? WHERE id=?',(b'',key))
    with store.lock,store.connect() as db:store.audit(db,actor,'desativar_autenticador','2fa',key)
    return {'ok':True}


def codes(store,actor):
    require(store,actor)
    current=time.time();items=[]
    with LOCK,vault(store) as c:
        for row in c.execute('SELECT * FROM tokens WHERE ativo=1 ORDER BY nome'):
            try:
                secret=crypt(bytes(row['secret']),True)
                items.append({'id':row['id'],'nome':row['nome'],'conta':row['conta'],'codigo':totp(secret,current,row['digits'],row['period'],row['algorithm']),'expira_em':(int(current)//row['period']+1)*row['period']})
            except Exception:items.append({'id':row['id'],'nome':row['nome'],'conta':row['conta'],'erro':'Não foi possível abrir este autenticador na conta Windows do servidor.'})
    with store.lock,store.connect() as db:store.audit(db,actor,'visualizar_codigos_2fa','2fa',after={'autenticadores':[r['id'] for r in items]})
    return {'servidor_agora':current,'itens':items}
