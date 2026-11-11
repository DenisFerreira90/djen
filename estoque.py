"""Estoques independentes, saldos exatos e permissões conferidas em cada operação."""
from contextlib import contextmanager
from decimal import Decimal,InvalidOperation
import re
import unicodedata
import juridico as legal

STOCKS={'ti':'TI','escritorio_limpeza':'Escritório e Limpeza'}
LOCATIONS=('Quarto do Harry','Sótão','Arquivo da Cozinha','Sala da TI','Arquivo Puxadinho','RH')
MAX_QTY=10**12  # Milésimos; até um bilhão de unidades.

def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS inventory_grants(user_id INTEGER NOT NULL REFERENCES users(id),stock TEXT NOT NULL,papel TEXT NOT NULL,alterado_por INTEGER,alterado_em TEXT,PRIMARY KEY(user_id,stock));
    CREATE TABLE IF NOT EXISTS inventory_seed(stock TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS inventory_locations(id INTEGER PRIMARY KEY,stock TEXT NOT NULL,nome TEXT NOT NULL,chave TEXT NOT NULL,versao INTEGER NOT NULL DEFAULT 1,excluido INTEGER NOT NULL DEFAULT 0);
    CREATE UNIQUE INDEX IF NOT EXISTS inventory_location_name ON inventory_locations(stock,chave) WHERE excluido=0;
    CREATE TABLE IF NOT EXISTS inventory_items(id INTEGER PRIMARY KEY,stock TEXT NOT NULL,nome TEXT NOT NULL,categoria TEXT NOT NULL,unidade TEXT NOT NULL,codigo TEXT NOT NULL,local_id INTEGER NOT NULL REFERENCES inventory_locations(id),quantidade INTEGER NOT NULL CHECK(quantidade>=0),minimo INTEGER NOT NULL CHECK(minimo>=0),observacoes TEXT NOT NULL,versao INTEGER NOT NULL DEFAULT 1,excluido INTEGER NOT NULL DEFAULT 0,criado TEXT NOT NULL,atualizado TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS inventory_items_stock ON inventory_items(stock,excluido,nome);
    CREATE INDEX IF NOT EXISTS inventory_items_location ON inventory_items(local_id,excluido);
    CREATE TABLE IF NOT EXISTS inventory_moves(id INTEGER PRIMARY KEY,item_id INTEGER NOT NULL REFERENCES inventory_items(id),stock TEXT NOT NULL,tipo TEXT NOT NULL,antes INTEGER NOT NULL,depois INTEGER NOT NULL,local_antes INTEGER,local_depois INTEGER,local_antes_nome TEXT,local_depois_nome TEXT,motivo TEXT NOT NULL,actor_id INTEGER NOT NULL REFERENCES users(id),data TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS inventory_moves_item ON inventory_moves(item_id,id);
    ''')
    columns={r['name'] for r in db.execute('PRAGMA table_info(inventory_moves)')}
    for name in ('local_antes_nome','local_depois_nome'):
        if name not in columns:db.execute('ALTER TABLE inventory_moves ADD COLUMN '+name+' TEXT')
    for stock in STOCKS:
        if not db.execute('SELECT 1 FROM inventory_seed WHERE stock=?',(stock,)).fetchone():
            db.executemany('INSERT INTO inventory_locations(stock,nome,chave) VALUES(?,?,?)',[(stock,name,key(name)) for name in LOCATIONS])
            db.execute('INSERT INTO inventory_seed VALUES(?)',(stock,))

@contextmanager
def connection(store,write=False):
    with store.lock:
        db=store.connect()
        try:
            schema(db);db.commit()
            if write:db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback();raise
        finally:db.close()

def key(value):return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c)).strip()

def text(body,name,limit,required=False):
    value=body.get(name,'')
    if not isinstance(value,str):raise legal.AppError('Campo inválido: '+name+'.')
    value=value.strip()
    if len(value)>limit or (required and not value):raise legal.AppError('Confira o campo '+name+'.')
    return value

def quantity(value):
    if isinstance(value,bool) or not isinstance(value,(str,int,float,Decimal)):raise legal.AppError('Quantidade inválida.')
    raw=str(value).strip().replace(',','.')
    if not re.fullmatch(r'\d{1,10}(?:\.\d{1,3})?',raw):raise legal.AppError('Use quantidade positiva ou zero, com até três casas decimais.')
    try:result=int(Decimal(raw)*1000)
    except (InvalidOperation,ValueError,OverflowError):raise legal.AppError('Quantidade inválida.')
    if not 0<=result<=MAX_QTY:raise legal.AppError('Quantidade excede o limite.')
    return result

def decimal(value):return format(Decimal(value)/1000,'.3f').rstrip('0').rstrip('.') if value else '0'

def require(db,actor,stock,write=False):
    if stock not in STOCKS:raise legal.AppError('Estoque inválido.')
    role='crud' if actor['role']=='administrador' else None
    if role is None:
        row=db.execute('SELECT papel FROM inventory_grants WHERE user_id=? AND stock=?',(actor['id'],stock)).fetchone()
        role=row['papel'] if row else None
    if not role or (write and (role!='crud' or actor['role']=='leitor')):raise legal.AppError('Você não tem permissão para esta operação neste estoque.',403)
    return 'ver' if actor['role']=='leitor' else role

def access(store,actor):
    with connection(store) as db:
        allowed=[]
        for stock,name in STOCKS.items():
            try:permission=require(db,actor,stock)
            except legal.AppError:continue
            allowed.append({'codigo':stock,'nome':name,'permissao':permission})
        return {'estoques':allowed,'gerenciar_permissoes':actor['role']=='administrador'}

def permissions(store,actor,body=None):
    if actor['role']!='administrador':raise legal.AppError('Somente administradores gerenciam permissões de estoque.',403)
    with connection(store,write=body is not None) as db:
        if body is not None:
            uid=body.get('user_id');grants=body.get('permissoes')
            if type(uid)is not int or not isinstance(grants,dict) or set(grants)!=set(STOCKS) or any(v not in ('','ver','crud') for v in grants.values()):raise legal.AppError('Permissões inválidas.')
            user=db.execute('SELECT * FROM users WHERE id=? AND ativo=1',(uid,)).fetchone()
            if not user:raise legal.AppError('Usuário não encontrado.',404)
            if user['role']=='leitor' and 'crud' in grants.values():raise legal.AppError('Perfil Leitor pode receber somente visualização.')
            before=[dict(r) for r in db.execute('SELECT stock,papel FROM inventory_grants WHERE user_id=?',(uid,))]
            db.execute('DELETE FROM inventory_grants WHERE user_id=?',(uid,))
            db.executemany('INSERT INTO inventory_grants VALUES(?,?,?,?,?)',[(uid,s,p,actor['id'],legal.now()) for s,p in grants.items() if p])
            store.audit(db,actor,'permissoes_estoque','usuario',uid,before=before,after=grants)
        users=[]
        for u in db.execute('SELECT id,nome,role FROM users WHERE ativo=1 ORDER BY nome').fetchall():
            granted={s:('crud' if u['role']=='administrador' else '') for s in STOCKS}
            for r in db.execute('SELECT stock,papel FROM inventory_grants WHERE user_id=?',(u['id'],)):
                if u['role']!='administrador':granted[r['stock']]='ver' if u['role']=='leitor' else r['papel']
            users.append({**dict(u),'permissoes':granted})
        return {'usuarios':users,'estoques':STOCKS}

def version(row,body):
    if type(body.get('versao'))is not int or body['versao']!=row['versao']:raise legal.AppError('Este registro mudou. Atualize a tela antes de salvar.',409)

def location(db,stock,lid):
    if type(lid)is not int:raise legal.AppError('Escolha o local de armazenamento.')
    row=db.execute('SELECT * FROM inventory_locations WHERE id=? AND stock=? AND excluido=0',(lid,stock)).fetchone()
    if not row:raise legal.AppError('Local não encontrado neste estoque.',404)
    return row

def locations(store,actor,stock,body=None,lid=None):
    with connection(store,write=body is not None) as db:
        require(db,actor,stock,body is not None)
        if body is not None:
            before=None
            if lid:before=dict(location(db,stock,lid));version(before,body)
            if body.get('excluir') is True:
                if not lid:raise legal.AppError('Local inválido.')
                if db.execute('SELECT 1 FROM inventory_items WHERE local_id=? AND excluido=0',(lid,)).fetchone():raise legal.AppError('Mova ou exclua os materiais deste local antes de removê-lo.',409)
                db.execute('UPDATE inventory_locations SET excluido=1,versao=versao+1 WHERE id=?',(lid,));after={'excluido':True}
            else:
                name=text(body,'nome',100,True);name=' '.join(name.split())
                duplicate=db.execute('SELECT 1 FROM inventory_locations WHERE stock=? AND chave=? AND excluido=0 AND id!=?',(stock,key(name),lid or 0)).fetchone()
                if duplicate:raise legal.AppError('Já existe um local com este nome.',409)
                if lid:db.execute('UPDATE inventory_locations SET nome=?,chave=?,versao=versao+1 WHERE id=?',(name,key(name),lid))
                else:lid=db.execute('INSERT INTO inventory_locations(stock,nome,chave) VALUES(?,?,?)',(stock,name,key(name))).lastrowid
                after=dict(location(db,stock,lid))
            store.audit(db,actor,'excluir_local_estoque' if after.get('excluido') else 'salvar_local_estoque','estoque_local',lid,before=before,after=after)
        return [dict(r) for r in db.execute('SELECT id,nome,versao FROM inventory_locations WHERE stock=? AND excluido=0 ORDER BY nome',(stock,))]

def public(row):
    out=dict(row)
    out['quantidade']=decimal(row['quantidade']);out['minimo']=decimal(row['minimo'])
    out['baixo']=row['quantidade']<=row['minimo']
    return out

def item_row(db,iid):
    row=db.execute('SELECT i.*,l.nome AS local FROM inventory_items i JOIN inventory_locations l ON l.id=i.local_id WHERE i.id=? AND i.excluido=0',(iid,)).fetchone()
    if not row:raise legal.AppError('Material não encontrado.',404)
    return row

def items(store,actor,stock,query='',page=1,lid=None,low=False):
    if type(page)is not int or page<1:raise legal.AppError('Página inválida.')
    with connection(store) as db:
        role=require(db,actor,stock)
        where='i.stock=? AND i.excluido=0';args=[stock]
        query=str(query).strip()[:200]
        if query:
            where+=' AND (i.nome LIKE ? OR i.codigo LIKE ? OR i.categoria LIKE ? OR l.nome LIKE ?)';args += ['%'+query+'%']*4
        if lid is not None:location(db,stock,lid);where+=' AND i.local_id=?';args.append(lid)
        if low:where+=' AND i.quantidade<=i.minimo'
        join=' FROM inventory_items i JOIN inventory_locations l ON l.id=i.local_id WHERE '+where
        total=db.execute('SELECT COUNT(*)'+join,args).fetchone()[0]
        rows=db.execute('SELECT i.*,l.nome AS local'+join+' ORDER BY i.nome COLLATE NOCASE,i.id LIMIT 100 OFFSET ?',(*args,(page-1)*100)).fetchall()
        stats=db.execute('SELECT COUNT(*) AS materiais,COALESCE(SUM(quantidade=0),0) AS sem_saldo,COALESCE(SUM(quantidade<=minimo),0) AS baixos FROM inventory_items WHERE stock=? AND excluido=0',(stock,)).fetchone()
        return {'itens':[public(r) for r in rows],'total':total,'pagina':page,'por_pagina':100,'resumo':dict(stats),'permissao':role}

def move_log(db,actor,row,before,kind,reason):
    db.execute('INSERT INTO inventory_moves(item_id,stock,tipo,antes,depois,local_antes,local_depois,local_antes_nome,local_depois_nome,motivo,actor_id,data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
               (row['id'],row['stock'],kind,before['quantidade'] if before else 0,row['quantidade'],before['local_id'] if before else None,row['local_id'],before.get('local') if before else None,row.get('local'),reason,actor['id'],legal.now()))

def save(store,actor,stock,body,iid=None):
    with connection(store,True) as db:
        require(db,actor,stock,True);before=None
        if iid:
            before=dict(item_row(db,iid))
            if before['stock']!=stock:raise legal.AppError('Material não encontrado neste estoque.',404)
            version(before,body)
        name=text(body,'nome',160,True);category=text(body,'categoria',80);unit=text(body,'unidade',24,True)
        code=text(body,'codigo',80);notes=text(body,'observacoes',4000)
        lid=body.get('local_id');location(db,stock,lid)
        qty=quantity(body.get('quantidade','0'));minimum=quantity(body.get('minimo','0'))
        reason=text(body,'motivo',500,False)
        if before and (qty!=before['quantidade'] or lid!=before['local_id']) and not reason:raise legal.AppError('Informe o motivo da alteração de saldo ou local.')
        if iid:
            db.execute('UPDATE inventory_items SET nome=?,categoria=?,unidade=?,codigo=?,local_id=?,quantidade=?,minimo=?,observacoes=?,versao=versao+1,atualizado=? WHERE id=?',(name,category,unit,code,lid,qty,minimum,notes,legal.now(),iid))
        else:
            iid=db.execute('INSERT INTO inventory_items(stock,nome,categoria,unidade,codigo,local_id,quantidade,minimo,observacoes,criado,atualizado) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(stock,name,category,unit,code,lid,qty,minimum,notes,legal.now(),legal.now())).lastrowid
        after=dict(item_row(db,iid));move_log(db,actor,after,before,'edicao' if before else 'cadastro',reason or 'Cadastro e saldo inicial')
        store.audit(db,actor,'alterar_material' if before else 'cadastrar_material','estoque',iid,before=before,after=after)
        return public(after)

def movement(store,actor,iid,body):
    with connection(store,True) as db:
        before=dict(item_row(db,iid));require(db,actor,before['stock'],True);version(before,body)
        kind=body.get('tipo');amount=quantity(body.get('quantidade'));reason=text(body,'motivo',500,True)
        if kind not in ('entrada','saida') or amount<=0:raise legal.AppError('Informe entrada ou saída e uma quantidade maior que zero.')
        qty=before['quantidade']+(amount if kind=='entrada' else -amount)
        if qty<0:raise legal.AppError('Saldo insuficiente para esta saída.',409)
        if qty>MAX_QTY:raise legal.AppError('Saldo excede o limite.')
        db.execute('UPDATE inventory_items SET quantidade=?,versao=versao+1,atualizado=? WHERE id=?',(qty,legal.now(),iid))
        after=dict(item_row(db,iid));move_log(db,actor,after,before,kind,reason)
        store.audit(db,actor,'estoque_'+kind,'estoque',iid,before=before,after=after)
        return public(after)

def delete(store,actor,iid,body):
    with connection(store,True) as db:
        before=dict(item_row(db,iid));require(db,actor,before['stock'],True);version(before,body)
        reason=text(body,'motivo',500,True)
        if before['quantidade']:raise legal.AppError('Registre a saída ou ajuste para saldo zero antes de excluir o material.',409)
        db.execute('UPDATE inventory_items SET excluido=1,versao=versao+1,atualizado=? WHERE id=?',(legal.now(),iid))
        move_log(db,actor,before,before,'exclusao',reason)
        store.audit(db,actor,'excluir_material','estoque',iid,before=before,after={'excluido':True,'motivo':reason})
        return {'excluido':True}

def history(store,actor,iid,page=1):
    with connection(store) as db:
        row=item_row(db,iid);require(db,actor,row['stock'])
        total=db.execute('SELECT COUNT(*) FROM inventory_moves WHERE item_id=?',(iid,)).fetchone()[0]
        moves=[]
        for r in db.execute('SELECT m.*,u.nome AS usuario FROM inventory_moves m JOIN users u ON u.id=m.actor_id WHERE m.item_id=? ORDER BY m.id DESC LIMIT 100 OFFSET ?',(iid,(page-1)*100)):
            value=dict(r);value['antes']=decimal(r['antes']);value['depois']=decimal(r['depois']);moves.append(value)
        return {'item':public(row),'itens':moves,'total':total,'pagina':page,'por_pagina':100}
