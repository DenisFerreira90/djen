"""Agenda local autorizada pelo administrador, sem armazenar senha de login."""
import datetime as dt
import json
import threading
import juridico as legal


def schema(db):db.execute('CREATE TABLE IF NOT EXISTS collection_schedule(id INTEGER PRIMARY KEY CHECK(id=1),config TEXT NOT NULL)')


def configure(store,actor,hour=6,enabled=True):
    if actor['role']!='administrador':raise legal.AppError('Agendamento restrito ao administrador.',403)
    if type(hour)is not int or not 0<=hour<=23:raise legal.AppError('Hora inválida.')
    current=dt.datetime.fromisoformat(legal.now());start=current.date()+dt.timedelta(days=int(current.hour>=hour))
    config={'ativo':enabled,'hora':hour,'actor_id':actor['id'],'inicio':start.isoformat(),'ultima_tentativa':None}
    with store.lock,store.connect() as db:
        schema(db);db.execute('INSERT OR REPLACE INTO collection_schedule VALUES(1,?)',(legal.dumps(config),));store.audit(db,actor,'configurar_agendamento','coleta',after=config)
    return config


def tick(store,collector):
    now=dt.datetime.fromisoformat(legal.now());today=now.date().isoformat()
    with store.lock,store.connect() as db:
        schema(db);row=db.execute('SELECT config FROM collection_schedule WHERE id=1').fetchone()
        if not row:return
        c=json.loads(row[0])
        frequency=c.get('frequencia','diaria')
        if not c['ativo'] or today<c['inicio']:return
        if frequency=='horaria':
            slot=now.isoformat()[:13]
        elif frequency=='manha_tarde':
            if now.hour<6:return
            slot=today+('T13' if now.hour>=13 else 'T06')
        else:
            if now.hour<c['hora']:return
            slot=today
        if c.get('ultima_janela')==slot or (frequency=='diaria' and c.get('ultima_tentativa')==today):return
        if collector.thread and collector.thread.is_alive():return
        user=db.execute('SELECT * FROM users WHERE id=? AND ativo=1',(c['actor_id'],)).fetchone()
        if not user or user['role']!='administrador':return
        c['ultima_tentativa']=today;c['ultima_janela']=slot;db.execute('UPDATE collection_schedule SET config=? WHERE id=1',(legal.dumps(c),));actor=store.public_user(user)
        store.audit(db,actor,'iniciar_coleta_agendada','coleta',after={'data':today,'modo':'incremental','complementos':False})
    options={'modo':'incremental','descobrir_consultas':c.get('detalhada',False),'automatico':True}
    if 'limite_minutos' in c:options['limite_minutos']=c['limite_minutos']
    collector.start(actor=actor,options=options)


def start(store,collector):
    def run():
        while True:
            try:tick(store,collector)
            except Exception:
                import logging;logging.exception('Falha no agendamento local')
            threading.Event().wait(30)
    threading.Thread(target=run,daemon=True,name='coleta-agendada').start()


def configure_service(store,actor,body):
    if actor['role']!='administrador':raise legal.AppError('Serviço restrito ao administrador.',403)
    mode=body.get('frequencia','diaria');budget=body.get('limite_minutos',50)
    if mode not in ('diaria','manha_tarde','horaria') or type(budget)is not int or not 10<=budget<=55:raise legal.AppError('Escolha frequência válida e orçamento entre 10 e 55 minutos.')
    c={'ativo':body.get('ativo') is True,'hora':6,'actor_id':actor['id'],'inicio':legal.now()[:10],'ultima_tentativa':None,'ultima_janela':legal.now()[:13],'frequencia':mode,'limite_minutos':budget,'detalhada':body.get('detalhada') is True}
    with store.lock,store.connect() as db:
        schema(db);db.execute('INSERT OR REPLACE INTO collection_schedule VALUES(1,?)',(legal.dumps(c),));store.audit(db,actor,'configurar_servico_coleta','coleta',after=c)
    return c
