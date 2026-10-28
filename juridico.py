"""Núcleo jurídico local: SQLite, contas individuais e auditoria transacional."""
from __future__ import annotations
import base64
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parent
CNJ = re.compile(r'\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b')
KINDS = {'processos', 'pessoas', 'partes', 'prazos', 'tarefas', 'anotacoes', 'financeiro', 'documentos'}
ROLES = {'administrador', 'equipe', 'leitor'}
FIELDS = {
 'processos': {'numero','titulo','tribunal','orgao','classe','area','status','responsavel_id','observacoes','revisao','categoria','disponibilizacao','publicacao','trabalho','competencia','autuacao','situacao_origem','juiz','assunto','juizo_codigo'},
 'pessoas': {'nome','tipo','documento','email','telefone','endereco','observacoes'},
 'partes': {'nome','pessoa_id','papel','representa_id','oab','uf','observacoes','origem','documento','registro','papel_origem'},
 'prazos': {'titulo','data_inicio','vencimento','data_fatal','status','responsavel_id','fonte','observacoes','conferido','origem','evento','conclusao','concluido_em','concluido_por','quantidade_dias','status_origem','destinatario','escopo','publicacao','disponibilizacao','data_envio','ocorrencia_lista'},
 'tarefas': {'titulo','vencimento','status','prioridade','responsavel_id','observacoes','origem','conclusao','concluido_em','concluido_por'},
 'anotacoes': {'titulo','texto'},
 'financeiro': {'titulo','natureza','valor_centavos','vencimento','status','categoria','pessoa_id','responsavel_id','observacoes'},
 'documentos': {'titulo','categoria','referencia','status','responsavel_id','observacoes'},
}

def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).isoformat(timespec='seconds')

def dumps(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))

class AppError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message); self.code = code

class Store:
    def __init__(self, path=BASE / 'dados_juridico' / 'juridico.sqlite3'):
        self.path = Path(path)
        self.lock = threading.RLock()

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, nome TEXT NOT NULL, login TEXT NOT NULL UNIQUE COLLATE NOCASE,
          password TEXT NOT NULL, role TEXT NOT NULL, ativo INTEGER NOT NULL DEFAULT 1, criado TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY, failures INTEGER NOT NULL, until_time REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS records (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL, case_id INTEGER REFERENCES records(id),
          data TEXT NOT NULL, criado TEXT NOT NULL, atualizado TEXT NOT NULL,
          criado_por INTEGER REFERENCES users(id), atualizado_por INTEGER REFERENCES users(id), version INTEGER NOT NULL DEFAULT 1);
        CREATE INDEX IF NOT EXISTS ix_records_kind_case ON records(kind,case_id);
        CREATE UNIQUE INDEX IF NOT EXISTS ix_case_number ON records(json_extract(data,'$.numero')) WHERE kind='processos';
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY, data TEXT NOT NULL, actor_id INTEGER REFERENCES users(id), actor_name TEXT NOT NULL,
          acao TEXT NOT NULL, entidade TEXT NOT NULL, entidade_id TEXT NOT NULL, antes TEXT, depois TEXT, ip TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'Auditoria somente inclusão'); END;
        CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Auditoria somente inclusão'); END;
        CREATE TABLE IF NOT EXISTS imports (id TEXT PRIMARY KEY, data TEXT NOT NULL, actor_id INTEGER REFERENCES users(id), resumo TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence (
          id INTEGER PRIMARY KEY, import_id TEXT REFERENCES imports(id), case_id INTEGER REFERENCES records(id),
          source TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(import_id,case_id,source));
        ''')
        return db

    @staticmethod
    def public_user(row):
        return {k: row[k] for k in ('id','nome','login','role','ativo')}

    @staticmethod
    def password(value, encoded=None):
        if encoded:
            try:
                salt, expected = encoded.split(':')
                got = hashlib.pbkdf2_hmac('sha256', value.encode(), bytes.fromhex(salt), 600000).hex()
                return hmac.compare_digest(got, expected)
            except (ValueError, TypeError):
                return False
        salt = secrets.token_bytes(16)
        return salt.hex() + ':' + hashlib.pbkdf2_hmac('sha256', value.encode(), salt, 600000).hex()

    def audit(self, db, actor, action, entity='', entity_id='', before=None, after=None, ip='127.0.0.1'):
        db.execute('INSERT INTO audit(data,actor_id,actor_name,acao,entidade,entidade_id,antes,depois,ip) VALUES(?,?,?,?,?,?,?,?,?)',
                   (now(),actor['id'] if actor else None,actor['nome'] if actor else 'Não autenticado', action,entity,str(entity_id),
                    dumps(before) if before is not None else None,dumps(after) if after is not None else None,ip))

    def setup_needed(self):
        with self.lock, self.connect() as db:
            return db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0

    def create_user(self, payload, actor=None, setup=False):
        with self.lock, self.connect() as db:
            if setup:
                if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
                    raise AppError('Administrador já cadastrado.',409)
            elif not actor or actor['role'] != 'administrador':
                raise AppError('Somente o administrador pode cadastrar usuários.',403)
            name, login = (str(payload.get(k,'')).strip() for k in ('nome','login'))
            password = str(payload.get('senha',''))
            role = 'administrador' if setup else payload.get('role','equipe')
            if not name or len(name)>120 or not re.fullmatch(r'[\w.@-]{3,80}',login) or not 10<=len(password)<=256 or role not in ROLES:
                raise AppError('Informe nome, login com 3 a 80 caracteres e senha com pelo menos 10 caracteres.')
            try:
                cur = db.execute('INSERT INTO users(nome,login,password,role,criado) VALUES(?,?,?,?,?)',(name,login,self.password(password),role,now()))
            except sqlite3.IntegrityError:
                raise AppError('Este login já está cadastrado.',409)
            user = self.public_user(db.execute('SELECT * FROM users WHERE id=?',(cur.lastrowid,)).fetchone())
            self.audit(db,actor or user,'criar_usuario','usuarios',user['id'],after=user)
            return user

    def login(self, login, password, ip='127.0.0.1'):
        import time
        key = hashlib.sha256((str(login).casefold()+'|'+ip).encode()).hexdigest()
        with self.lock, self.connect() as db:
            attempt=db.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone()
            if attempt and attempt['failures']>=5 and attempt['until_time']>time.time():
                raise AppError('Muitas tentativas. Aguarde 5 minutos.',429)
            row=db.execute('SELECT * FROM users WHERE login=? COLLATE NOCASE',(str(login),)).fetchone()
            valid = self.password(str(password),row['password']) if row else self.password(str(password),'00'*16+':'+'00'*32)
            if not row or not row['ativo'] or not valid:
                failures = (attempt['failures'] if attempt and attempt['until_time']>time.time() else 0)+1
                db.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)',(key,failures,time.time()+300))
                self.audit(db,None,'login_recusado',after={'login':str(login)[:80]},ip=ip)
                db.commit()
                raise AppError('Login ou senha inválidos.',401)
            user=self.public_user(row)
            token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
            db.execute('DELETE FROM login_attempts WHERE key=?',(key,))
            db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],csrf,time.time()+28800))
            self.audit(db,user,'login',ip=ip)
            return {'usuario':user,'csrf':csrf},token

    def auth(self, token):
        import time
        with self.lock, self.connect() as db:
            row=db.execute('SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.ativo=1',
                           (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if not row: raise AppError('Entre no sistema para continuar.',401)
            return self.public_user(row),row['csrf']

    def logout(self, token, actor):
        with self.lock, self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),))
            self.audit(db,actor,'logout')

    def users(self, actor):
        with self.lock, self.connect() as db:
            rows=db.execute('SELECT * FROM users ORDER BY nome').fetchall()
            if actor['role']=='administrador': return [self.public_user(r) for r in rows]
            return [{'id':r['id'],'nome':r['nome'],'ativo':r['ativo']} for r in rows]

    def update_user(self, uid, payload, actor):
        if actor['role']!='administrador': raise AppError('Acesso restrito ao administrador.',403)
        with self.lock, self.connect() as db:
            row=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            if not row: raise AppError('Usuário não encontrado.',404)
            before=self.public_user(row)
            # Não permitir que outro administrador tome a conta proprietária do chat.
            control=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_control'").fetchone()
            chat_owner=db.execute('SELECT owner_id FROM chat_control WHERE id=1').fetchone() if control else None
            if chat_owner and uid==chat_owner[0] and actor['id']!=uid:
                raise AppError('A conta proprietária do chat só pode ser alterada por ela mesma.',403)
            role=payload.get('role',row['role']);active=payload.get('ativo',row['ativo'])
            if chat_owner and uid==chat_owner[0] and (not active or role!='administrador'):
                raise AppError('Mantenha a conta proprietária ativa e administradora.')
            if role not in ROLES or active not in (0,1,False,True): raise AppError('Perfil ou situação inválidos.')
            if row['role']=='administrador' and row['ativo'] and (role!='administrador' or not active):
                if db.execute("SELECT COUNT(*) FROM users WHERE role='administrador' AND ativo=1").fetchone()[0]<=1:
                    raise AppError('Mantenha ao menos um administrador ativo.')
            pwd=payload.get('senha')
            if pwd and not 10<=len(str(pwd))<=256: raise AppError('A senha deve ter pelo menos 10 caracteres.')
            db.execute('UPDATE users SET role=?,ativo=?,password=? WHERE id=?',(role,int(active),self.password(pwd) if pwd else row['password'],uid))
            db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            after=self.public_user(db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())
            self.audit(db,actor,'alterar_usuario','usuarios',uid,before,{**after,'senha_redefinida':bool(pwd)})
            return after

    @staticmethod
    def record(row):
        return {'id':row['id'],'tipo':row['kind'],'processo_id':row['case_id'],'dados':json.loads(row['data']),
                'criado':row['criado'],'atualizado':row['atualizado'],'criado_por':row['criado_por'],
                'atualizado_por':row['atualizado_por'],'versao':row['version']}

    def list(self, kind, query='', case_id=None, page=1):
        if kind not in KINDS: raise AppError('Cadastro inválido.')
        where=['kind=?'];params=[kind]
        if kind=='prazos' and not case_id:where.append("COALESCE(json_extract(data,'$.escopo'),'')!='todas_as_partes'")
        if query:
            where.append('data LIKE ?');params.append('%'+query[:200]+'%')
        if case_id:
            where.append('case_id=?');params.append(int(case_id))
        with self.lock, self.connect() as db:
            clause=' AND '.join(where)
            total=db.execute('SELECT COUNT(*) FROM records WHERE '+clause,params).fetchone()[0]
            rows=db.execute('SELECT * FROM records WHERE '+clause+' ORDER BY atualizado DESC,id DESC LIMIT 50 OFFSET ?',params+[(max(1,page)-1)*50]).fetchall()
            items=[self.record(r) for r in rows]
            if kind=='processos':
                for item in items:
                    pending=[self.record(x) for x in db.execute("SELECT * FROM records WHERE case_id=? AND kind IN ('prazos','tarefas')",(item['id'],))]
                    due=[x for x in pending if x['dados'].get('escopo')!='todas_as_partes' and x['dados'].get('vencimento') and x['dados'].get('status') in ('pendente','a_fazer','em_andamento','aguardando')]
                    due.sort(key=lambda x:x['dados']['vencimento'])
                    item['proxima_acao']=due[0] if due else None
                    parties=[json.loads(x['data']) for x in db.execute("SELECT data FROM records WHERE kind='partes' AND case_id=? ORDER BY id",(item['id'],))]
                    item['partes_resumo']=[{'nome':p.get('nome',''),'papel':p.get('papel','')} for p in parties if not p.get('representa_id')][:6]
            return {'itens':items,'total':total,'pagina':max(1,page)}

    def detail(self, rid):
        with self.lock, self.connect() as db:
            row=db.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone()
            if not row: raise AppError('Registro não encontrado.',404)
            record=self.record(row)
            if row['kind']=='processos':
                record['vinculos']=[self.record(r) for r in db.execute('SELECT * FROM records WHERE case_id=? ORDER BY kind,id',(rid,))]
                record['evidencias']=[dict(r) for r in db.execute('SELECT id,import_id,source FROM evidence WHERE case_id=? ORDER BY id DESC',(rid,))]
            return record

    def save(self, kind, payload, actor, rid=None):
        if actor['role']=='leitor': raise AppError('Seu perfil permite apenas leitura.',403)
        if kind not in KINDS: raise AppError('Cadastro inválido.')
        data=payload.get('dados',{})
        if rid and isinstance(data,dict):
            previous=self.detail(rid)
            if previous['tipo']!=kind:raise AppError('Tipo de registro incorreto.')
            data={**previous['dados'],**data}
        if not isinstance(data,dict) or set(data)-FIELDS[kind]: raise AppError('Campos de cadastro inválidos.')
        if any(not isinstance(v,(str,int,bool,type(None))) for v in data.values()): raise AppError('Valores de cadastro inválidos.')
        if len(dumps(data))>50000: raise AppError('Registro muito longo.')
        data={k:(v.strip() if isinstance(v,str) else v) for k,v in data.items()}
        required={'processos':'numero','pessoas':'nome','partes':'nome','prazos':'titulo','tarefas':'titulo','anotacoes':'titulo','financeiro':'titulo','documentos':'titulo'}[kind]
        if not data.get(required): raise AppError('Preencha o campo obrigatório: '+required)
        if kind=='processos':
            number=re.sub(r'\D','',str(data['numero']))
            if len(number)!=20: raise AppError('Informe os 20 dígitos do número CNJ.')
            data['numero']=f'{number[:7]}-{number[7:9]}.{number[9:13]}.{number[13]}.{number[14:16]}.{number[16:]}'
        for k in ('data_inicio','vencimento','data_fatal'):
            if data.get(k):
                try:
                    value=str(data[k]);dt.datetime.fromisoformat(value)
                    if len(value)>32: raise ValueError()
                except ValueError: raise AppError('Data inválida: '+k)
        allowed_status={'processos':{'ativo','arquivado','suspenso'},'prazos':{'pendente','cumprido','cancelado','encerrado_na_origem','aguardando_abertura','conferir_origem'},'tarefas':{'a_fazer','em_andamento','aguardando','concluida','cancelada'},'financeiro':{'pendente','pago','cancelado'},'documentos':{'rascunho','em_revisao','finalizado','arquivado'}}
        if kind in allowed_status:
            default={'processos':'ativo','prazos':'pendente','tarefas':'a_fazer','financeiro':'pendente','documentos':'rascunho'}[kind]
            data.setdefault('status',default)
            if data['status'] not in allowed_status[kind]: raise AppError('Situação inválida.')
        if kind=='prazos' and not data.get('vencimento'): raise AppError('Informe o vencimento registrado na fonte.')
        if kind=='financeiro':
            if data.get('natureza') not in ('receber','pagar') or type(data.get('valor_centavos')) is not int or data['valor_centavos']<0 or data['valor_centavos']>10**14:
                raise AppError('Informe a natureza e um valor monetário válido.')
        if kind in ('prazos','tarefas') and data.get('status') in ('cumprido','concluida'):
            if not data.get('conclusao'):raise AppError('Descreva a providência tomada antes de concluir.')
            was_completed=rid and previous['dados'].get('status') in ('cumprido','concluida')
            data['concluido_em']=previous['dados'].get('concluido_em',now()) if was_completed else now()
            data['concluido_por']=previous['dados'].get('concluido_por',actor['id']) if was_completed else actor['id']
        case_id=payload.get('processo_id', previous.get('processo_id') if rid else None) or None
        with self.lock, self.connect() as db:
            import gestao
            gestao.schema(db)
            before=None
            if rid:
                row=db.execute('SELECT * FROM records WHERE id=? AND kind=?',(rid,kind)).fetchone()
                if not row: raise AppError('Registro não encontrado.',404)
                if payload.get('versao')!=row['version']: raise AppError('Outro usuário alterou este registro. Reabra antes de salvar.',409)
                before=self.record(row)
                if kind=='partes' and row['case_id']!=case_id and db.execute("SELECT 1 FROM records WHERE kind='partes' AND json_extract(data,'$.representa_id')=?",(rid,)).fetchone():
                    raise AppError('Esta parte tem representantes vinculados. Ajuste os vínculos antes de mudar o processo.')
            if kind in ('partes','prazos','anotacoes') and not case_id: raise AppError('Vincule o registro a um processo.')
            if case_id and not db.execute("SELECT 1 FROM records WHERE id=? AND kind='processos'",(case_id,)).fetchone(): raise AppError('Processo vinculado não encontrado.')
            if kind=='processos' and case_id: raise AppError('Processo não pode ter processo pai.')
            if data.get('responsavel_id') and not db.execute('SELECT 1 FROM users WHERE id=? AND ativo=1',(data['responsavel_id'],)).fetchone(): raise AppError('Responsável não encontrado ou inativo.')
            if kind in ('partes','financeiro'):
                if data.get('pessoa_id') and not db.execute("SELECT 1 FROM records WHERE id=? AND kind='pessoas'",(data['pessoa_id'],)).fetchone(): raise AppError('Pessoa vinculada não encontrada.')
                if data.get('representa_id') and not db.execute("SELECT 1 FROM records WHERE id=? AND kind='partes' AND case_id=?",(data['representa_id'],case_id)).fetchone(): raise AppError('A parte representada deve pertencer ao mesmo processo.')
            try:
                if rid:
                    db.execute('UPDATE records SET data=?,case_id=?,atualizado=?,atualizado_por=?,version=version+1 WHERE id=?',(dumps(data),case_id,now(),actor['id'],rid))
                else:
                    rid=db.execute('INSERT INTO records(kind,case_id,data,criado,atualizado,criado_por,atualizado_por) VALUES(?,?,?,?,?,?,?)',
                                   (kind,case_id,dumps(data),now(),now(),actor['id'],actor['id'])).lastrowid
            except sqlite3.IntegrityError: raise AppError('Este número de processo já existe.',409)
            after=self.record(db.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone())
            self.audit(db,actor,'alterar' if before else 'criar',kind,rid,before,after)
            if kind=='processos':gestao.ensure_review(self,db,db.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone(),actor)
            elif kind=='prazos' and case_id:gestao.ensure_review(self,db,db.execute('SELECT * FROM records WHERE id=?',(case_id,)).fetchone(),actor)
            return after

    def audits(self, actor, query='', page=1):
        if actor['role']!='administrador': raise AppError('Auditoria restrita ao administrador.',403)
        with self.lock, self.connect() as db:
            params=['%'+query[:200]+'%']*4
            clause='actor_name LIKE ? OR acao LIKE ? OR entidade LIKE ? OR entidade_id LIKE ?'
            total=db.execute('SELECT COUNT(*) FROM audit WHERE '+clause,params).fetchone()[0]
            rows=db.execute('SELECT * FROM audit WHERE '+clause+' ORDER BY id DESC LIMIT 50 OFFSET ?',params+[(max(1,page)-1)*50]).fetchall()
            return {'itens':[dict(r) for r in rows],'total':total,'pagina':max(1,page)}

    def dashboard(self):
        with self.lock, self.connect() as db:
            counts={kind:db.execute('SELECT COUNT(*) FROM records WHERE kind=?',(kind,)).fetchone()[0] for kind in KINDS}
            counts['prazos_historicos']=db.execute("SELECT COUNT(*) FROM records WHERE kind='prazos' AND json_extract(data,'$.escopo')='todas_as_partes'").fetchone()[0]
            counts['prazos']-=counts['prazos_historicos']
            deadlines=[];today=now()[:10]
            for row in db.execute("SELECT * FROM records WHERE kind IN ('prazos','tarefas')"):
                r=self.record(row);d=r['dados']
                if d.get('status') in ('pendente','a_fazer','em_andamento') and d.get('vencimento') and d.get('escopo')!='todas_as_partes': deadlines.append(r)
            deadlines.sort(key=lambda r:r['dados']['vencimento'])
            internos=[r for r in deadlines if r['dados'].get('origem')=='revisao_interna']
            oficiais=[r for r in deadlines if r['tipo']=='prazos' and r['dados'].get('escopo')!='todas_as_partes']
            week=(dt.date.fromisoformat(today)+dt.timedelta(days=7)).isoformat()
            groups=lambda rows:{'vencidos':sum(r['dados']['vencimento'][:10]<today for r in rows),'hoje':sum(r['dados']['vencimento'][:10]==today for r in rows),'semana':sum(today<=r['dados']['vencimento'][:10]<=week for r in rows)}
            return {'oficiais':groups(oficiais),'internas':groups(internos),'sem_responsavel':db.execute("SELECT COUNT(*) FROM records WHERE kind='processos' AND (json_extract(data,'$.responsavel_id') IS NULL OR json_extract(data,'$.responsavel_id')='')").fetchone()[0],'contagens':counts,'pendencias':deadlines[:30],'atrasados':sum(r['dados']['vencimento'][:10]<today for r in deadlines),
                    'revisar':db.execute("SELECT COUNT(*) FROM records WHERE kind='processos' AND json_extract(data,'$.revisao')=1").fetchone()[0]}

    def import_corpus(self, payload, actor):
        if actor['role']=='leitor': raise AppError('Seu perfil permite apenas leitura.',403)
        if not isinstance(payload,dict): raise AppError('Arquivo de coleta inválido.')
        records=payload.get('processos',[]);pages=payload.get('paginas_da_lista',[])
        if not isinstance(records,list) or not isinstance(pages,list): raise AppError('Estrutura de coleta inválida.')
        content=dumps({'processos':records,'paginas_da_lista':pages})
        if len(content)>128*1024*1024: raise AppError('Coleta excede o limite de importação.')
        run=str(payload.get('execucao',{}).get('id') or 'arquivo')[:100]
        iid=run+':'+hashlib.sha256(content.encode()).hexdigest()[:20]+':estruturado-v2'
        gathered={}
        for record in records:
            if not isinstance(record,dict): raise AppError('Registro de processo inválido.')
            match=CNJ.fullmatch(str(record.get('processo','')))
            if match:
                gathered.setdefault(match.group(),[]).append(('detalhes',record.get('detalhes') or {'situacao':record.get('situacao')}))
        for pi,page in enumerate(pages,1):
            if not isinstance(page,dict): raise AppError('Página inválida.')
            for ti,table in enumerate(page.get('tabelas',[]),1):
                for ri,row in enumerate(table.get('linhas',[]),1):
                    if not isinstance(row,list): continue
                    matches=CNJ.findall(' '.join(str(v) for v in row))
                    if matches:
                        # First process in the original row is the source; don't infer parties/dates.
                        gathered.setdefault(matches[0],[]).append((f'lista:{pi}:{ti}:{ri}',{'celulas':row}))
        if not gathered: raise AppError('Nenhum número CNJ foi encontrado nas linhas ou detalhes da coleta.')
        with self.lock,self.connect() as db:
            import gestao
            gestao.schema(db)
            prior=db.execute('SELECT resumo FROM imports WHERE id=?',(iid,)).fetchone()
            if prior:
                old=json.loads(prior['resumo']);self.audit(db,actor,'importacao_repetida','importacoes',iid)
                return {**old,'criados':0,'existentes':old.get('total',0),'repetido':True}
            db.execute('INSERT INTO imports VALUES(?,?,?,?)',(iid,now(),actor['id'],'{}'))
            created=0;existing=0
            for number,evidence in gathered.items():
                row=db.execute("SELECT * FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
                if row: rid=row['id'];existing+=1
                else:
                    from eproc_tribunais import from_number
                    data={'numero':number,'tribunal':from_number(number),'titulo':'Processo importado do eproc','status':'ativo','revisao':1,'observacoes':'Partes e prazos aguardam conferência dos dados de origem.'}
                    rid=db.execute('INSERT INTO records(kind,data,criado,atualizado,criado_por,atualizado_por) VALUES(?,?,?,?,?,?)',('processos',dumps(data),now(),now(),actor['id'],actor['id'])).lastrowid
                    created+=1
                    self.audit(db,actor,'importar_processo','processos',rid,after=data)
                for si,(source,value) in enumerate(evidence):
                    db.execute('INSERT OR IGNORE INTO evidence(import_id,case_id,source,payload) VALUES(?,?,?,?)',(iid,rid,source+':'+str(si),dumps(value)))
            import eproc_estruturado
            structured=eproc_estruturado.enrich(self,db,payload,actor,iid)
            for number in gathered:
                case=db.execute("SELECT * FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
                gestao.ensure_review(self,db,case,actor)
            fingerprints=gestao.fingerprints_from_pages(pages)
            check_time=payload.get('execucao',{}).get('fim') or payload.get('execucao',{}).get('inicio')
            for source_record in records:
                number=source_record.get('processo','');detail=source_record.get('detalhes')
                if not isinstance(detail,dict) or number not in str(detail.get('texto','')) or not detail.get('cobertura_eventos',{}).get('completo',True):
                    if CNJ.fullmatch(number):db.execute('INSERT OR IGNORE INTO sync_state VALUES(?,?,?,?,?,?,?)',(number,fingerprints.get(number,''),None,'falha',None,source_record.get('situacao','falha_na_leitura'),run))
                    continue
                try:
                    check_time_valid=dt.datetime.fromisoformat(check_time)
                    if check_time_valid.tzinfo is None:continue
                except (ValueError,TypeError):continue
                prior_sync=db.execute('SELECT checked_at FROM sync_state WHERE numero=?',(number,)).fetchone()
                if prior_sync and prior_sync['checked_at'] and prior_sync['checked_at']>check_time:continue
                db.execute('INSERT OR REPLACE INTO sync_state VALUES(?,?,?,?,?,?,?)',(number,fingerprints.get(number,''),check_time,'lido',dumps(detail),'',run))
            summary={'id':iid,'criados':created,'existentes':existing,'total':len(gathered),'revisar':True,'estruturado':structured}
            db.execute('UPDATE imports SET resumo=? WHERE id=?',(dumps(summary),iid))
            self.audit(db,actor,'importar_coleta','importacoes',iid,after=summary)
            return summary

    def evidence(self, eid):
        with self.lock,self.connect() as db:
            row=db.execute('SELECT * FROM evidence WHERE id=?',(eid,)).fetchone()
            if not row: raise AppError('Dados de origem não encontrados.',404)
            return {**dict(row),'payload':json.loads(row['payload'])}

    def export(self, actor):
        if actor['role']!='administrador': raise AppError('Exportação integral restrita ao administrador.',403)
        with self.lock,self.connect() as db:
            self.audit(db,actor,'exportar_dados','sistema')
            return {'formato':'juridico-local-v1','exportado':now(),
                    'registros':[self.record(r) for r in db.execute('SELECT * FROM records')],
                    'usuarios':[self.public_user(r) for r in db.execute('SELECT * FROM users')],
                    'auditoria':[dict(r) for r in db.execute('SELECT * FROM audit')],
                    'importacoes':[dict(r) for r in db.execute('SELECT * FROM imports')],
                    'evidencias':[dict(r) for r in db.execute('SELECT * FROM evidence')],
                    'eventos_origem':[dict(r) for r in db.execute('SELECT * FROM source_events')] if db.execute("SELECT 1 FROM sqlite_master WHERE name='source_events'").fetchone() else [],
                    'complementos_origem':[dict(r) for r in db.execute('SELECT * FROM source_complements')] if db.execute("SELECT 1 FROM sqlite_master WHERE name='source_complements'").fetchone() else []}

store=Store()
