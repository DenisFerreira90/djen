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
    if re.search(r'negativ|nao expedid|nao cumprid|indefer|revog|suspend|cancelad|recolhim',t):return 'revisar_negativa_ou_alteracao'
    if re.search(r'\b(?:pedido|requerimento|solicitacao|requer\w*)\b.{0,55}(?:mandad[oa]s?|busca e apreensao)|\bmandad[oa]s?\s+solicitad',t):return 'possivel_pedido'
    if re.search(r'cumprid|apreendid',t):return 'possivel_cumprimento'
    if re.search(r'expedid|expedicao',t):return 'possivel_expedicao'
    return 'revisar_mencao'


def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS mandate_alerts(id INTEGER PRIMARY KEY,event_id INTEGER UNIQUE,case_id INTEGER,numero TEXT,evento TEXT,data_evento TEXT,trecho TEXT,categoria TEXT,criado TEXT,revisado TEXT,revisor TEXT);
    CREATE TABLE IF NOT EXISTS mandate_watchlist(numero TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS mandate_state(chave TEXT PRIMARY KEY,valor TEXT);''')

    if not db.execute("SELECT 1 FROM mandate_state WHERE chave='classificacao_v2'").fetchone():
        for row in db.execute('SELECT id,trecho FROM mandate_alerts').fetchall():
            category=classify(row['trecho'])
            if category:db.execute('UPDATE mandate_alerts SET categoria=? WHERE id=?',(category,row['id']))
        db.execute("INSERT INTO mandate_state VALUES('classificacao_v2','1')")


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


def case_summaries(db, watched_only=False):
    from mandados_resumo import summarize
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='source_events'").fetchone():return []
    cases={}
    sql='SELECT e.*,r.data AS case_data FROM source_events e JOIN records r ON r.id=e.case_id ORDER BY e.id'
    watched={r[0] for r in db.execute('SELECT numero FROM mandate_watchlist')}
    for r in db.execute(sql):
        number=json.loads(r['case_data']).get('numero','')
        if watched_only and number not in watched:continue
        from origem_registros import provenance
        case=cases.setdefault(r['case_id'],{'numero':number,'case_id':r['case_id'],'origem':provenance(json.loads(r['case_data']),case_id=r['case_id']),'events':[]})
        event=json.loads(r['payload']);event['numero']=r['numero'];event['data']=r['data'];case['events'].append(event)
    import mandados_documentos
    result=[]
    for case in cases.values():
        summary={**{k:v for k,v in case.items() if k!='events'},**summarize(case['events'])}
        for mandate in summary['mandados']:
            for event in mandate['eventos']:
                event['documentos']=[{'nome':label,'disponivel':mandados_documentos.available(case['numero'],event['evento'],label)} for label in event['documentos']]
        observed=db.execute('SELECT MAX(i.data) FROM imports i JOIN source_events e ON e.import_id=i.id WHERE e.case_id=?',(case['case_id'],)).fetchone() if 'import_id' in {r[1] for r in db.execute('PRAGMA table_info(source_events)')} else None
        summary['coletado_em']=observed[0] if observed else None
        result.append(summary)
    return result


def status(store):
    with store.lock,store.connect() as db:
        schema(db)
        state=dict(db.execute('SELECT chave,valor FROM mandate_state'))
        scope=state.get('somente_lista')=='1'
        where=" WHERE numero IN (SELECT numero FROM mandate_watchlist)" if scope else ''
        numbers=[r[0] for r in db.execute('SELECT numero FROM mandate_watchlist ORDER BY numero')]
        known={json.loads(r[0]).get('numero') for r in db.execute("SELECT data FROM records WHERE kind='processos'")}
        from origem_registros import provenance
        origins={r['id']:provenance(json.loads(r['data']),case_id=r['id']) for r in db.execute("SELECT id,data FROM records WHERE kind='processos'")}
        return {'itens':[{**dict(r),'origem':origins.get(r['case_id'],{})} for r in db.execute('SELECT * FROM mandate_alerts'+where+' ORDER BY revisado IS NOT NULL,id DESC LIMIT 200')],
                'pendentes':db.execute('SELECT COUNT(*) FROM mandate_alerts'+where+(' AND ' if scope else ' WHERE ')+'revisado IS NULL').fetchone()[0],
                'resumos':case_summaries(db, watched_only=scope),'estado':state,'numeros':numbers,'sem_cadastro':[n for n in numbers if n not in known],
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
    import email_alertas
    email_alertas.prepare(store)
    stop=threading.Event()
    def run():
        while not stop.is_set():
            try:
                scan(store)
                import email_alertas
                email_alertas.process_mandates(store)
                email_alertas.process(store)
            except Exception:
                import logging;logging.exception('Falha na triagem de mandados')
            stop.wait(60)
    threading.Thread(target=run,daemon=True,name='triagem-mandados').start()
    return stop


def valid_check_digits(digits):
    return bool(re.fullmatch(r'[0-9]{20}',digits)) and int(digits[7:9])==98-int(digits[:7]+digits[9:]+'00')%97


def number(value):
    value=str(value).strip()
    if re.fullmatch(r'[0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4}',value):return value
    if re.fullmatch(r'[0-9]{20}',value):digits=value
    elif re.fullmatch(r'[0-9.\-\s]+',value):
        digits=re.sub(r'\D','',value)
        if not valid_check_digits(digits):return None
    else:return None
    if len(digits)!=20:return None
    return f'{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:]}'


def extract_watchlist(data,filename):
    import planilhas
    parsed=planilhas.parse(data,filename);numbers=set();invalid=[];normalized=[];contexts=[];rows=0
    for sheet in parsed['abas']:
        lines=sheet['linhas'];header=None
        for i,line in enumerate(lines[:30]):
            cols=[j for j,v in enumerate(line) if planilhas.norm(v) in ('n processo','no processo','numero processo','numero do processo','processo','numero cnj')]
            if len(cols)==1:header=(i,cols[0]);break
        if header is None:raise legal.AppError('Não identifiquei a coluna de processo na aba '+sheet['nome']+'. Use o cabeçalho Processo.')
        hi,ci=header
        labels=[planilhas.norm(v) for v in lines[hi]]
        client_col=next((j for j,v in enumerate(labels) if v in ('cliente','nome do cliente','nome cliente')),None)
        contact_cols=[j for j,v in enumerate(labels) if v in ('telefone','celular','whatsapp','contato','email','e mail','telefone cliente','telefone do cliente','contato do cliente')]
        for ri,row in enumerate(lines[hi+1:],hi+2):
            raw=row[ci] if ci<len(row) else ''
            if not str(raw).strip():continue
            rows+=1;n=number(raw)
            if n and valid_check_digits(re.sub(r'\D','',n)):
                numbers.add(n)
                name=str(row[client_col]).strip()[:240] if client_col is not None and len(row)>client_col else ''
                contacts=' | '.join(str(lines[hi][j])+': '+str(row[j]).strip() for j in contact_cols if len(row)>j and str(row[j]).strip())[:500]
                if name or contacts:contexts.append({'numero':n,'nome_cliente':name,'contato':contacts,'origem':sheet['nome']+', linha '+str(ri)})
                if str(raw).strip()!=n:normalized.append({'aba':sheet['nome'],'linha':ri,'original':str(raw)[:100],'numero':n})
            else:
                reason='Número armazenado como valor numérico longo no Excel; os dígitos não são confiáveis.' if '[número Excel sem precisão]' in str(raw) or re.search(r'[0-9][eE][+-]?[0-9]+',str(raw)) else 'Dígito verificador inválido.' if n else 'Formato incompleto ou não reconhecido.'
                invalid.append({'aba':sheet['nome'],'linha':ri,'valor':str(raw)[:100],'motivo':reason})
    return {'numeros':sorted(numbers),'invalidos':invalid,'linhas':rows,'normalizados':normalized,'contexto':contexts,'avisos':parsed.get('avisos',[])}


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
