"""Controladoria local: fila persistente de recuperação e indicadores operacionais."""
import json
import threading
import uuid
import datetime as dt
import juridico as legal
import reprocessamento


def schema(db):
    db.executescript('''
    CREATE INDEX IF NOT EXISTS ix_evidence_case ON evidence(case_id,id);
    CREATE TABLE IF NOT EXISTS control_jobs(id TEXT PRIMARY KEY,criado TEXT NOT NULL,atualizado TEXT NOT NULL,estado TEXT NOT NULL,actor_id INTEGER NOT NULL,actor_name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS control_items(job_id TEXT REFERENCES control_jobs(id),case_id INTEGER REFERENCES records(id),numero TEXT NOT NULL,estado TEXT NOT NULL DEFAULT 'pendente',resultado TEXT NOT NULL DEFAULT '{}',atualizado TEXT,PRIMARY KEY(job_id,case_id));
    CREATE TABLE IF NOT EXISTS control_settings(chave TEXT PRIMARY KEY,valor TEXT NOT NULL);
    ''')


def report(store):
    today=legal.now()[:10];week=(dt.date.fromisoformat(today)+dt.timedelta(days=7)).isoformat()
    with store.lock,store.connect() as db:
        records=db.execute("SELECT id,kind,case_id,data FROM records WHERE kind IN ('processos','prazos','tarefas')").fetchall()
        result={'data':today,'processos':0,'fichas_incompletas':0,'sem_responsavel':0,'oficiais_vencidos':0,'oficiais_hoje':0,'oficiais_7_dias':0,'revisoes_vencidas':0,'tarefas_atrasadas':0,'equipe':[]}
        people={str(r['id']):r['nome'] for r in db.execute('SELECT id,nome FROM users')};groups={}
        for row in records:
            d=json.loads(row['data']);kind=row['kind'];uid=d.get('responsavel_id') or 0
            g=groups.setdefault(str(uid),{'responsavel':people.get(str(uid),'Sem responsável'),'processos':0,'prazos_vencidos':0,'tarefas_atrasadas':0})
            if kind=='processos':
                result['processos']+=1;g['processos']+=1
                result['sem_responsavel']+=not bool(uid)
                result['fichas_incompletas']+=not all(d.get(k) for k in ('tribunal','orgao','classe'))
            elif kind=='prazos' and d.get('status') in ('pendente','conferir_origem') and d.get('escopo')!='todas_as_partes':
                date=str(d.get('data_fatal') or d.get('vencimento') or '')[:10]
                if not date:continue
                if d.get('origem')=='revisao_interna':result['revisoes_vencidas']+=date<today
                else:
                    result['oficiais_vencidos']+=date<today;result['oficiais_hoje']+=date==today
                    result['oficiais_7_dias']+=today<date<=week;g['prazos_vencidos']+=date<today
            elif kind=='tarefas' and d.get('status') not in ('concluida','cancelada'):
                date=str(d.get('vencimento') or '')[:10]
                if date and date<today:
                    if d.get('origem')=='revisao_interna':result['revisoes_vencidas']+=1
                    else:result['tarefas_atrasadas']+=1;g['tarefas_atrasadas']+=1
        result['equipe']=sorted(groups.values(),key=lambda g:(-g['prazos_vencidos'],-g['tarefas_atrasadas'],g['responsavel']))
        return result


class Queue:
    def __init__(self):self.lock=threading.RLock();self.thread=None
    def active(self):return bool(self.thread and self.thread.is_alive())
    def status(self,store):
        with self.lock,store.lock,store.connect() as db:
            schema(db)
            if not self.active():db.execute("UPDATE control_jobs SET estado='interrompido',atualizado=? WHERE estado='executando'",(legal.now(),))
            job=db.execute('SELECT * FROM control_jobs ORDER BY criado DESC,id DESC LIMIT 1').fetchone()
            if not job:return {'execucao':None,'historico':[]}
            job=dict(job);counts={r[0]:r[1] for r in db.execute('SELECT estado,COUNT(*) FROM control_items WHERE job_id=? GROUP BY estado',(job['id'],))}
            job['contagens']=counts;job['total']=sum(counts.values());job['processados']=job['total']-counts.get('pendente',0)
            job['pendencias']=[dict(r) for r in db.execute("SELECT numero,estado,resultado FROM control_items WHERE job_id=? AND estado IN ('sem_origem','erro') ORDER BY numero LIMIT 100",(job['id'],))]
            return {'execucao':job,'historico':[dict(r) for r in db.execute('SELECT * FROM control_jobs ORDER BY criado DESC LIMIT 10')]}
    def start(self,store,actor,automatic=False):
        if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
        with self.lock:
            if self.active():return self.status(store)
            with store.lock,store.connect() as db:
                schema(db)
                pending=db.execute("SELECT * FROM control_jobs WHERE estado IN ('executando','interrompido') ORDER BY criado DESC LIMIT 1").fetchone()
                paused=db.execute("SELECT id FROM control_jobs WHERE estado='pausado' LIMIT 1").fetchone()
                if automatic and paused:return self.status(store)
                if automatic and not pending and db.execute("SELECT 1 FROM control_settings WHERE chave='preenchimento_v8'").fetchone():return self.status(store)
                if pending:
                    jid=pending['id']
                elif paused:
                    jid=paused['id']
                else:
                    jid=uuid.uuid4().hex
                    db.execute('INSERT INTO control_jobs VALUES(?,?,?,?,?,?)',(jid,legal.now(),legal.now(),'executando',actor['id'],actor['nome']))
                    cases=db.execute("SELECT id,json_extract(data,'$.numero') AS numero FROM records WHERE kind='processos' AND (COALESCE(json_extract(data,'$.orgao'),'')='' OR COALESCE(json_extract(data,'$.classe'),'')='' OR COALESCE(json_extract(data,'$.tribunal'),'')='' OR json_extract(data,'$.titulo')='Processo importado do eproc')").fetchall()
                    db.executemany('INSERT INTO control_items(job_id,case_id,numero) VALUES(?,?,?)',[(jid,c['id'],c['numero']) for c in cases])
                db.execute("UPDATE control_jobs SET estado='executando',actor_id=?,actor_name=?,atualizado=? WHERE id=?",(actor['id'],actor['nome'],legal.now(),jid))
                db.execute("INSERT OR REPLACE INTO control_settings VALUES('preenchimento_v8','iniciado')")
                store.audit(db,actor,'iniciar_preenchimento_lote','controladoria',jid,after={'automatico':automatic})
            self.thread=threading.Thread(target=self.run,args=(store,jid,actor),daemon=True);self.thread.start()
            return self.status(store)
    def pause(self,store,actor):
        if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
        with store.lock,store.connect() as db:
            schema(db);db.execute("UPDATE control_jobs SET estado='pausado',atualizado=? WHERE estado IN ('executando','interrompido')",(legal.now(),))
            store.audit(db,actor,'pausar_preenchimento_lote','controladoria')
        return self.status(store)
    def run(self,store,jid,actor):
        try:
            while True:
                with store.lock,store.connect() as db:
                    schema(db)
                    job=db.execute('SELECT estado FROM control_jobs WHERE id=?',(jid,)).fetchone()
                    if not job or job['estado']!='executando':return
                    user=db.execute('SELECT role,ativo FROM users WHERE id=?',(actor['id'],)).fetchone()
                    if not user or not user['ativo'] or user['role']=='leitor':
                        db.execute("UPDATE control_jobs SET estado='pausado' WHERE id=?",(jid,));return
                    item=db.execute("SELECT case_id FROM control_items WHERE job_id=? AND estado='pendente' ORDER BY case_id LIMIT 1",(jid,)).fetchone()
                    if not item:
                        db.execute("UPDATE control_jobs SET estado='concluido',atualizado=? WHERE id=?",(legal.now(),jid))
                        store.audit(db,actor,'concluir_preenchimento_lote','controladoria',jid);return
                try:
                    info=reprocessamento.diagnose(store,item['case_id'])
                    if not info['origem_detalhada_disponivel'] and not info['linhas_lista_disponiveis']:
                        state='sem_origem';result={'mensagem':'Importe o ZIP da coleta ou consulte as pendências no eproc.'}
                    else:
                        result=reprocessamento.repair(store,actor,item['case_id']);state='preenchido' if info['origem_detalhada_disponivel'] else 'parcial'
                except Exception as exc:
                    state='erro';result={'mensagem':str(exc) if isinstance(exc,legal.AppError) else 'Falha local ao estruturar a ficha; consulte a origem e tente novamente.'}
                with store.lock,store.connect() as db:
                    db.execute('UPDATE control_items SET estado=?,resultado=?,atualizado=? WHERE job_id=? AND case_id=?',(state,legal.dumps(result),legal.now(),jid,item['case_id']))
                    db.execute('UPDATE control_jobs SET atualizado=? WHERE id=?',(legal.now(),jid))
        except Exception:
            # A pending item is retained; next explicit start resumes it.
            with store.lock,store.connect() as db:
                schema(db);db.execute("UPDATE control_jobs SET estado='interrompido',atualizado=? WHERE id=?",(legal.now(),jid))

queue=Queue()
