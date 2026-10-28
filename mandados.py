"""Triagem indicativa de eventos; nunca substitui leitura do documento judicial."""
import json
import re
import threading
import unicodedata
import juridico as legal


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.lower()) if not unicodedata.combining(c))


def classify(text):
    t=normalize(text)
    if not re.search(r'\bmandad[oa]s?\b|busca e apreensao|restricao.*(?:veicul|renajud)',t):return None
    if re.search(r'\bmandato\b',t) and not re.search(r'mandado|busca e apreensao|renajud',t):return None
    if re.search(r'nao expedid|nao cumprid|indefer|revog|suspend|cancelad|recolhim',t):return 'revisar_negativa_ou_alteracao'
    if re.search(r'cumprid|apreendid',t):return 'possivel_cumprimento'
    if re.search(r'expedid|expedicao',t):return 'possivel_expedicao'
    return 'revisar_mencao'


def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS mandate_alerts(id INTEGER PRIMARY KEY,event_id INTEGER UNIQUE,case_id INTEGER,numero TEXT,evento TEXT,data_evento TEXT,trecho TEXT,categoria TEXT,criado TEXT,revisado TEXT,revisor TEXT);
    CREATE TABLE IF NOT EXISTS mandate_watchlist(numero TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS mandate_state(chave TEXT PRIMARY KEY,valor TEXT);''')


def scan(store):
    with store.lock,store.connect() as db:
        schema(db); added=0
        scoped=(db.execute("SELECT valor FROM mandate_state WHERE chave='somente_lista'").fetchone() or ['0'])[0]=='1'
        watched={r[0] for r in db.execute('SELECT numero FROM mandate_watchlist')}
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='source_events'").fetchone()
        cursor=int((db.execute("SELECT valor FROM mandate_state WHERE chave='cursor'").fetchone() or ['0'])[0])
        if exists:
            for row in db.execute('SELECT e.*,r.data AS case_data FROM source_events e JOIN records r ON r.id=e.case_id WHERE e.id>? ORDER BY e.id',(cursor,)).fetchall():
                payload=json.loads(row['payload']);text=str(payload.get('descricao',''));category=classify(text)
                if category and (not scoped or json.loads(row['case_data']).get('numero','') in watched):
                    number=json.loads(row['case_data']).get('numero','')
                    cur=db.execute('INSERT OR IGNORE INTO mandate_alerts(event_id,case_id,numero,evento,data_evento,trecho,categoria,criado) VALUES(?,?,?,?,?,?,?,?)',(row['id'],row['case_id'],number,row['numero'],row['data'],text,category,legal.now()));added+=cur.rowcount
                cursor=row['id']
        db.execute("INSERT OR REPLACE INTO mandate_state VALUES('cursor',?)",(str(cursor),))
        db.execute("INSERT OR REPLACE INTO mandate_state VALUES('ultima_varredura',?)",(legal.now(),))
        return {'novos':added}


def status(store):
    with store.lock,store.connect() as db:
        schema(db)
        state=dict(db.execute('SELECT chave,valor FROM mandate_state'))
        scope=state.get('somente_lista')=='1'
        where=" WHERE numero IN (SELECT numero FROM mandate_watchlist)" if scope else ''
        numbers=[r[0] for r in db.execute('SELECT numero FROM mandate_watchlist ORDER BY numero')]
        known={json.loads(r[0]).get('numero') for r in db.execute("SELECT data FROM records WHERE kind='processos'")}
        return {'itens':[dict(r) for r in db.execute('SELECT * FROM mandate_alerts'+where+' ORDER BY revisado IS NOT NULL,id DESC LIMIT 200')],
                'pendentes':db.execute('SELECT COUNT(*) FROM mandate_alerts'+where+(' AND ' if scope else ' WHERE ')+'revisado IS NULL').fetchone()[0],
                'estado':state,'numeros':numbers,'sem_cadastro':[n for n in numbers if n not in known],
                'cobertura':'Eventos importados. Documentos não lidos; ausência de alerta não comprova ausência de mandado. A varredura local não consulta o tribunal.'}



def review(store,actor,ident):
    if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
    with store.lock,store.connect() as db:
        schema(db)
        if not db.execute('SELECT 1 FROM mandate_alerts WHERE id=?',(ident,)).fetchone():raise legal.AppError('Alerta não encontrado.',404)
        db.execute('UPDATE mandate_alerts SET revisado=?,revisor=? WHERE id=?',(legal.now(),actor['nome'],ident))
        store.audit(db,actor,'revisar_alerta','mandados',ident)
    return status(store)


def start(store):
    stop=threading.Event()
    def run():
        while not stop.is_set():
            try:
                scan(store)
                import email_alertas
                email_alertas.process(store)
            except Exception:
                import logging;logging.exception('Falha na triagem de mandados')
            stop.wait(60)
    threading.Thread(target=run,daemon=True,name='triagem-mandados').start()
    return stop


def number(value):
    value=str(value).strip()
    if re.fullmatch(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}',value):return value
    if re.fullmatch(r'\d{20}',value):return f'{value[:7]}-{value[7:9]}.{value[9:13]}.{value[13]}.{value[14:16]}.{value[16:]}'
    return None


def extract_watchlist(data,filename):
    import planilhas
    parsed=planilhas.parse(data,filename);numbers=set();invalid=[];rows=0
    for sheet in parsed['abas']:
        lines=sheet['linhas'];header=None
        for i,line in enumerate(lines[:30]):
            cols=[j for j,v in enumerate(line) if planilhas.norm(v) in ('n processo','no processo','numero processo','numero do processo','processo','numero cnj')]
            if len(cols)==1:header=(i,cols[0]);break
        if header is None:raise legal.AppError('Não identifiquei a coluna de processo na aba '+sheet['nome']+'. Use o cabeçalho Processo.')
        hi,ci=header
        for ri,row in enumerate(lines[hi+1:],hi+2):
            raw=row[ci] if ci<len(row) else ''
            if not str(raw).strip():continue
            rows+=1;n=number(raw)
            if n:numbers.add(n)
            else:invalid.append({'aba':sheet['nome'],'linha':ri,'valor':str(raw)[:100]})
    return {'numeros':sorted(numbers),'invalidos':invalid,'linhas':rows,'avisos':parsed.get('avisos',[])}


def set_scope(store,actor,numbers,enabled=True):
    if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
    if not isinstance(numbers,list) or len(numbers)>20000:raise legal.AppError('Lista inválida.')
    normalized={number(n) for n in numbers}
    if None in normalized:raise legal.AppError('Confira os números dos processos.')
    if enabled and not normalized:raise legal.AppError('Informe pelo menos um processo válido.')
    with store.lock,store.connect() as db:
        schema(db)
        db.execute('DELETE FROM mandate_watchlist')
        db.executemany('INSERT INTO mandate_watchlist VALUES(?)',[(n,) for n in sorted(normalized)])
        db.execute("INSERT OR REPLACE INTO mandate_state VALUES('somente_lista',?)",('1' if enabled else '0',))
        db.execute("INSERT OR REPLACE INTO mandate_state VALUES('cursor','0')")
        store.audit(db,actor,'definir_lista_monitoramento','mandados',after={'quantidade':len(normalized),'somente_lista':enabled})
    scan(store)
    return status(store)
