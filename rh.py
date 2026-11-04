"""RH restrito por área, com dados e auditoria fora da base jurídica."""
import json, sqlite3, datetime as dt, io, zipfile, tempfile, uuid
from contextlib import contextmanager
from pathlib import Path
import juridico as legal
SCOPES={'colaboradores':'Colaboradores','demandas':'Demandas','agenda':'Agenda e cronograma','ausencias':'Faltas e afastamentos','entrevistas':'Entrevistas','desligamentos':'Desligamentos','notas':'Notas e comunicados'}
FIELDS={'titulo','pessoa','setor','unidade','inicio','fim','status','prioridade','responsavel_id','observacoes','tipo'}
STATES={'aberto','em_andamento','concluido','cancelado','ativo','inativo','agendado','realizado','justificada','nao_justificada','em_analise'}
def path(store):return store.path.parent/'rh'/'rh.sqlite3'
def _open(store):
 with store.connect() as main:
  main.execute('CREATE TABLE IF NOT EXISTS rh_identity(id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL)')
  main.execute('INSERT OR IGNORE INTO rh_identity VALUES(1,?)',(uuid.uuid4().hex,))
  identity=main.execute('SELECT token FROM rh_identity WHERE id=1').fetchone()[0]
 p=path(store);p.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(p,timeout=15);db.row_factory=sqlite3.Row
 db.executescript('''CREATE TABLE IF NOT EXISTS rh_meta(id INTEGER PRIMARY KEY CHECK(id=1),owner_id INTEGER NOT NULL,identity TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS rh_grants(user_id INTEGER,scope TEXT,level TEXT,PRIMARY KEY(user_id,scope));
 CREATE TABLE IF NOT EXISTS rh_items(id INTEGER PRIMARY KEY,scope TEXT NOT NULL,data TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,created TEXT NOT NULL,updated TEXT NOT NULL,actor_id INTEGER NOT NULL);
 CREATE INDEX IF NOT EXISTS rh_items_scope ON rh_items(scope,id);
 CREATE TABLE IF NOT EXISTS rh_audit(id INTEGER PRIMARY KEY,created TEXT,actor_id INTEGER,actor_name TEXT,action TEXT,item_id INTEGER,before TEXT,after TEXT);
 CREATE TRIGGER IF NOT EXISTS rh_audit_no_update BEFORE UPDATE ON rh_audit BEGIN SELECT RAISE(ABORT,'Auditoria somente inclusão'); END;
 CREATE TRIGGER IF NOT EXISTS rh_audit_no_delete BEFORE DELETE ON rh_audit BEGIN SELECT RAISE(ABORT,'Auditoria somente inclusão'); END;
 ''')
 if not db.execute('SELECT 1 FROM rh_meta').fetchone():
  with store.connect() as main:owner=main.execute("SELECT id FROM users WHERE role='administrador' ORDER BY id LIMIT 1").fetchone()
  if not owner:db.close();raise legal.AppError('Configure o administrador antes do RH.',403)
  db.execute('INSERT OR IGNORE INTO rh_meta VALUES(1,?,?)',(owner[0],identity));db.commit()
 if db.execute('SELECT identity FROM rh_meta WHERE id=1').fetchone()[0]!=identity:
  db.close();raise legal.AppError('A base do RH não corresponde à base de contas. Restaure os backups do mesmo ambiente.',403)
 return db

@contextmanager
def connect(store):
 db=_open(store)
 try:
  with db:yield db
 finally:db.close()

def caps(db,actor):
 owner=db.execute('SELECT owner_id FROM rh_meta WHERE id=1').fetchone()[0]==actor['id']
 grants={r['scope']:r['level'] for r in db.execute('SELECT scope,level FROM rh_grants WHERE user_id=?',(actor['id'],))}
 return {'proprietario':owner,'areas':{s:('editar' if owner else grants.get(s,'')) for s in SCOPES},'rotulos':SCOPES}
def require(db,actor,scope=None,write=False,owner=False):
 permissions=caps(db,actor)
 if owner:
  if not permissions['proprietario']:raise legal.AppError('Somente o proprietário do RH pode administrar esta ação.',403)
 elif scope not in SCOPES:raise legal.AppError('Área de RH inválida.')
 elif not permissions['areas'].get(scope) or (write and (permissions['areas'][scope]!='editar' or actor['role']=='leitor')):raise legal.AppError('Você não tem permissão para esta área do RH.',403)
 return permissions

def audit(db,actor,action,item=None,before=None,after=None):
 db.execute('INSERT INTO rh_audit(created,actor_id,actor_name,action,item_id,before,after) VALUES(?,?,?,?,?,?,?)',(legal.now(),actor['id'],actor['nome'],action,item,legal.dumps(before) if before is not None else None,legal.dumps(after) if after is not None else None))

def access(store,actor):
 with store.lock,connect(store) as db:return caps(db,actor)

def permissions(store,actor,body=None):
 with store.lock,connect(store) as db:
  require(db,actor,owner=True)
  with store.connect() as main:users=[dict(r) for r in main.execute('SELECT id,nome,role,ativo FROM users ORDER BY nome')]
  if body is not None:
   if set(body)!={'usuario_id','areas'} or type(body['usuario_id']) is not int or not isinstance(body['areas'],dict):raise legal.AppError('Permissões inválidas.')
   uid=body['usuario_id'];values=body['areas']
   user=next((u for u in users if u['id']==uid and u['ativo']),None)
   if not user or uid==db.execute('SELECT owner_id FROM rh_meta').fetchone()[0]:raise legal.AppError('Selecione outro usuário ativo.')
   if any(s not in SCOPES or v not in ('','ver','editar') or (user['role']=='leitor' and v=='editar') for s,v in values.items()):raise legal.AppError('Área ou nível de acesso inválido.')
   before=[dict(r) for r in db.execute('SELECT scope,level FROM rh_grants WHERE user_id=?',(uid,))]
   db.execute('DELETE FROM rh_grants WHERE user_id=?',(uid,))
   for scope,level in values.items():
    if level:db.execute('INSERT INTO rh_grants VALUES(?,?,?)',(uid,scope,level))
   audit(db,actor,'alterar_permissoes',uid,before,values)
  return {'usuarios':users,'permissoes':[dict(r) for r in db.execute('SELECT * FROM rh_grants')],'rotulos':SCOPES,'owner_id':db.execute('SELECT owner_id FROM rh_meta').fetchone()[0]}

def validate(data,store):
 if not isinstance(data,dict) or set(data)-FIELDS:raise legal.AppError('Campos de RH inválidos.')
 result={}
 for key,value in data.items():
  if key=='responsavel_id':
   if value in ('',None):result[key]=None;continue
   if type(value)is not int:raise legal.AppError('Responsável inválido.')
   with store.connect() as main:u=main.execute('SELECT id FROM users WHERE id=? AND ativo=1',(value,)).fetchone()
   if not u:raise legal.AppError('Responsável não está ativo.')
  else:
   if not isinstance(value,str):raise legal.AppError('Texto inválido.')
   value=value.strip()
   if len(value)>(12000 if key=='observacoes' else 240):raise legal.AppError('Campo excede o tamanho permitido.')
   if key in ('inicio','fim') and value:
    try:
     parsed=dt.datetime.fromisoformat(value)
     if 'T' not in value or parsed.tzinfo is None or parsed.utcoffset()!=dt.timedelta(hours=-3):raise ValueError()
    except ValueError:raise legal.AppError('Informe data e hora com fuso de Brasília.')
   if key=='status' and value not in STATES:raise legal.AppError('Situação inválida.')
   if key=='prioridade' and value not in ('baixa','normal','alta','urgente'):raise legal.AppError('Prioridade inválida.')
  result[key]=value
 if not result.get('titulo'):raise legal.AppError('Informe o título.')
 if result.get('fim') and not result.get('inicio'):raise legal.AppError('Informe o início antes do fim.')
 if result.get('inicio') and result.get('fim') and result['fim']<result['inicio']:raise legal.AppError('O fim deve ser posterior ou igual ao início.')
 return result

def record(row):return {'id':row['id'],'area':row['scope'],'dados':json.loads(row['data']),'versao':row['version'],'criado':row['created'],'atualizado':row['updated']}
def items(store,actor,scope,search='',page=1,start='',end=''):
 with store.lock,connect(store) as db:
  require(db,actor,scope)
  try:page=int(page)
  except (ValueError,TypeError):raise legal.AppError('Página inválida.')
  if not 1<=page<=100000:raise legal.AppError('Página inválida.')
  query='SELECT * FROM rh_items WHERE scope=?';args=[scope]
  if search:query+=' AND data LIKE ?';args.append('%'+str(search)[:200]+'%')
  for value in (start,end):
   if value:
    try:dt.date.fromisoformat(value)
    except ValueError:raise legal.AppError('Filtro de data inválido.')
  if start:query+=" AND substr(COALESCE(NULLIF(json_extract(data,'$.fim'),''),json_extract(data,'$.inicio')),1,10)>=?";args.append(start)
  if end:query+=" AND substr(json_extract(data,'$.inicio'),1,10)<=?";args.append(end)
  total=db.execute('SELECT COUNT(*) FROM ('+query+')',args).fetchone()[0]
  rows=db.execute(query+" ORDER BY COALESCE(NULLIF(json_extract(data,'$.inicio'),''),updated),id LIMIT 50 OFFSET ?",[*args,(page-1)*50]).fetchall()
  return {'itens':[record(r) for r in rows],'total':total,'pagina':page}

def save(store,actor,scope,body,rid=None):
 if not isinstance(body,dict) or set(body)-{'dados','versao'}:raise legal.AppError('Registro inválido.')
 with store.lock,connect(store) as db:
  require(db,actor,scope,write=True)
  db.execute('BEGIN IMMEDIATE')
  old=db.execute('SELECT * FROM rh_items WHERE id=? AND scope=?',(rid,scope)).fetchone() if rid else None
  if rid and not old:raise legal.AppError('Registro não encontrado.',404)
  if old and (type(body.get('versao'))is not int or body['versao']!=old['version']):raise legal.AppError('Registro alterado por outra pessoa. Reabra antes de salvar.',409)
  data=validate(body.get('dados'),store)
  if scope=='agenda' and not data.get('inicio'):raise legal.AppError('Informe a data e hora do compromisso.')
  if old:
   db.execute('UPDATE rh_items SET data=?,version=version+1,updated=?,actor_id=? WHERE id=?',(legal.dumps(data),legal.now(),actor['id'],rid))
  else:
   rid=db.execute('INSERT INTO rh_items(scope,data,created,updated,actor_id) VALUES(?,?,?,?,?)',(scope,legal.dumps(data),legal.now(),legal.now(),actor['id'])).lastrowid
  audit(db,actor,'editar_'+scope if old else 'criar_'+scope,rid,json.loads(old['data']) if old else None,data)
  return record(db.execute('SELECT * FROM rh_items WHERE id=?',(rid,)).fetchone())

def history(store,actor):
 with store.lock,connect(store) as db:
  require(db,actor,owner=True)
  return [dict(r) for r in db.execute('SELECT * FROM rh_audit ORDER BY id DESC LIMIT 200')]

def backup(store,actor):
 with store.lock,connect(store) as db:
  require(db,actor,owner=True);audit(db,actor,'backup_rh');db.commit()
  with tempfile.TemporaryDirectory() as tmp:
   dest=Path(tmp)/'rh.sqlite3';target=sqlite3.connect(dest)
   try:db.backup(target)
   finally:target.close()
   data=dest.read_bytes()
  out=io.BytesIO()
  with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
   z.writestr('rh.sqlite3',data);z.writestr('LEIA-ME.txt','Backup exclusivo do RH. Preserve também a base jurídica que contém as contas e seus IDs. Restauração deve ser feita com o servidor parado e conferência das contas. Não substitua a base jurídica por este arquivo.')
  return out.getvalue()

def save_general(store,actor,body):
 with store.lock,connect(store) as db:require(db,actor,'notas',write=True)
 mid=body.get('mensagem_id')
 if type(mid)is not int:raise legal.AppError('Mensagem inválida.')
 with store.connect() as db:
  try:
   row=db.execute("SELECT m.*,u.nome FROM chat_messages m JOIN chat_rooms r ON r.id=m.room_id JOIN users u ON u.id=m.sender_id WHERE m.id=? AND r.tipo='geral' AND EXISTS(SELECT 1 FROM chat_members cm WHERE cm.room_id=r.id AND cm.user_id=?)",(mid,actor['id'])).fetchone()
  except sqlite3.OperationalError:row=None
  if not row:raise legal.AppError('Mensagem do Geral não disponível nesta base.',404)
  content='Origem: chat Geral | mensagem '+str(mid)+' | '+row['nome']+' | '+row['criado']+'\n\n'+row['texto']
 return save(store,actor,'notas',{'dados':{'titulo':'Comunicado do Geral #'+str(mid),'tipo':'comunicado','status':'aberto','prioridade':'normal','observacoes':content}})
