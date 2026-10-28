"""Extrator do formato efetivamente observado na coleta TJRS de 26/10/2026.
Só utiliza rótulos, colunas, registros profissionais e datas explícitos.
"""
import hashlib
import json
import re
import unicodedata
import juridico as legal
import planilhas
import eproc_tribunais as tribunais

ROLE_LABELS={'AUTOR','RÉU','EXEQUENTE','EXECUTADO','REQUERENTE','REQUERIDO','PERITO','MINISTÉRIO PÚBLICO','INTIMADO','INTERESSADO','TERCEIRO INTERESSADO','TESTEMUNHA AUTOR','TESTEMUNHA RÉU','EMBARGANTE','EMBARGADO','REPRESENTANTE LEGAL','AGÊNCIA DA PREVIDÊNCIA SOCIAL','HERDEIRO','TESTEMUNHA','RECORRENTE','RECORRIDO','UNIDADE EXTERNA','CÔNJUGE','CURADOR ESPECIAL','CONCILIADOR/JUIZ LEIGO','NÃO CONSTA','CONFRONTANTE','DEPRECANTE','ADMINISTRADOR'}
DOCUMENT=re.compile(r'\((\d[\d.\-/]{9,20})\)')
EVENT_HEADER=['Evento','Data/Hora','Descrição','Usuário','Documentos']

def clean(value):return ' '.join(str(value or '').replace('\xa0',' ').split())
def role(value):return '_'.join(planilhas.norm(value).split())
def digest(value):return hashlib.sha256(legal.dumps(value).encode()).hexdigest()
def date(value):
    try:return planilhas.date(clean(value))
    except ValueError:return ''


def listing(pages):
    out=[]
    for pi,page in enumerate(pages,1):
        for table in page.get('tabelas',[]):
            rows=table.get('linhas',[])
            if not rows or not {'Processo','Evento e Prazo','Final Prazo'}<=set(rows[0]):continue
            headers=rows[0];idx={v:headers.index(v) for v in headers}
            for ri,row in enumerate(rows[1:],2):
                def field(k):return str(row[idx[k]]) if k in idx and idx[k]<len(row) else ''
                match=legal.CNJ.search(field('Processo'))
                if not match:continue
                juizo=re.search(r'Juízo:\s*([^\n]+)',field('Processo'))
                out.append({'numero':match.group(),'classe':clean(field('Classe')),'assunto':clean(field('Assunto')),'juizo_codigo':clean(juizo.group(1)) if juizo else '',
                    'descricao':field('Evento e Prazo').strip(),'envio':date(field('Data envio requisição')),'data_inicio':date(field('Início Prazo')),
                    'vencimento':date(field('Final Prazo')),'pagina':pi,'linha':ri,'partes_texto':field('Processo')})
    return out


def parse_cell(cell,label):
    lines=[clean(x) for x in str(cell).splitlines() if clean(x)]
    if not lines:return []
    first=lines[0]
    doc=DOCUMENT.search(first)
    name=first[:doc.start()].strip() if doc else re.split(r'\s+-\s+(?:Pessoa|Entidade)',first)[0].strip()
    if not name or name in ROLE_LABELS:return []
    party={'nome':name,'papel':role(label),'documento':re.sub(r'\D','',doc.group(1)) if doc else '',
           'tipo_pessoa':'pessoa_juridica' if 'Pessoa Jurídica' in first or 'Entidade' in first else 'pessoa_fisica' if 'Pessoa Física' in first else 'outro','origem':'eproc','representa_indice':None}
    result=[party]
    professional=re.compile(r'^(.*?)\s+((?:[A-Z]{2}\d{3,8}[A-Z]?)|(?:DPE-\d+))(?:\s+\(.*)?\s*$')
    for i,line in enumerate(lines[1:],1):
        m=professional.match(line)
        if not m:continue
        name=clean(re.sub(r'^(?:Procurador\(es\):\s*)','',m.group(1)))
        name=re.sub(r'\s*\(DPE\)\s*$','',name).strip()
        if not name:continue
        registry=m.group(2);kind=''
        if i+1<len(lines) and lines[i+1].startswith('Tipo de Usuário:'):kind=lines[i+1].split(':',1)[1].strip()
        if registry.startswith('DPE-'):paper='defensor'
        elif 'ADVOGADO' in kind:paper='advogado'
        elif 'PROCURADOR' in kind:paper='procurador'
        else:paper='representante'
        result.append({'nome':name,'papel':paper,'papel_origem':kind,'registro':registry,'uf':registry[:2] if not registry.startswith('DPE') else '',
            'oab':registry[2:] if paper=='advogado' else '', 'origem':'eproc','representa_indice':0,'documento':'','tipo_pessoa':'advogado' if paper=='advogado' else 'pessoa_fisica'})
    return result


def detail(record):
    raw=record.get('detalhes') or {};text=raw.get('texto','');number=record.get('processo','')
    main=re.search(r'Nº do processo\s*('+legal.CNJ.pattern.removeprefix(r'\b').removesuffix(r'\b')+')',text)
    if not main or main.group(1)!=number:return {'validado':False,'numero':number,'campos':{},'partes':[],'eventos':[],'prazos':[],'avisos':['Página não confirmou o número principal do processo.']}
    def between(start,end):
        m=re.search(start+r'\s*(.*?)\s*'+end,text,re.S)
        return clean(m.group(1)) if m else ''
    fields={'numero':number,'tribunal':tribunais.from_number(number),'classe':between('Classe da ação:',r'Competência'),
        'competencia':between('Competência',r'Data de autuação:'),'autuacao':date(between('Data de autuação:',r'Situação')),
        'situacao_origem':between('Situação',r'Órgão Julgador:'),'orgao':between('Órgão Julgador:',r'Juiz\(a\):'),
        'juiz':between(r'Juiz\(a\):',r'(?:Processos relacionados:|Lembretes|Assuntos)')}
    parties=[];events=[];deadlines=[];warnings=[]
    for table in raw.get('tabelas',[]):
        rows=table.get('linhas',[])
        if table.get('titulo')=='Partes e Representantes':
            roles=[]
            for row in rows:
                labels=[clean(x) for x in row]
                if labels and all(x in ROLE_LABELS for x in labels):roles=labels;continue
                if len(row)!=len(roles):
                    if any(clean(x) for x in row):warnings.append('Linha de partes com estrutura diferente dos cabeçalhos, mantida na origem.')
                    continue
                for col,cell in enumerate(row):
                    parsed=parse_cell(cell,roles[col]);offset=len(parties)
                    for person in parsed:
                        if person['representa_indice'] is not None:person['representa_indice']+=offset
                        parties.append(person)
        if rows and rows[0]==EVENT_HEADER:
            for row in rows[1:]:
                if len(row)!=5:continue
                eventid=clean(row[0]);description=str(row[2]).strip()
                if not eventid.isdigit():continue
                event={'numero':eventid,'data':date(row[1]),'descricao':description,'usuario_origem':str(row[3]).strip(),'documentos_referencias':str(row[4]).strip()}
                events.append(event)
                quantity=re.search(r'Prazo:\s*(\d+)\s+dias?',description)
                status=re.search(r'(?:Status do Prazo:|Status:)\s*([^\n(]+)',description)
                if not status:continue
                end=re.search(r'Data final:\s*([^\n]+)',description);start=re.search(r'Data inicial da contagem do prazo:\s*([^\n]+)',description)
                recipient=re.search(r'\n\(([^\n]+)\)',description)
                source_status=clean(status.group(1))
                state='pendente' if source_status=='ABERTO' else 'aguardando_abertura' if source_status=='AGUARD. ABERTURA' else 'encerrado_na_origem' if source_status=='FECHADO' else 'conferir_origem'
                deadlines.append({'evento':eventid,'titulo':clean(description.split('\n')[0]),'data_inicio':date(start.group(1)) if start else '',
                    'vencimento':date(end.group(1)) if end else '', 'quantidade_dias':int(quantity.group(1)) if quantity else None,'status':state,'status_origem':source_status,
                    'destinatario':recipient.group(1) if recipient else '', 'escopo':'todas_as_partes','origem':'eproc','fonte':'eproc / evento '+eventid,'conferido':0})
    # Publication dates belong to the referenced intimation event, not the whole process.
    byid={d['evento']:d for d in deadlines}
    for e in events:
        ref=re.search(r'Refer\. aos? Eventos?:\s*([\d, e]+)',e['descricao'])
        if not ref:continue
        when=re.search(r'no dia\s+(\d{2}/\d{2}/\d{4})',e['descricao'])
        if not when:continue
        for number in re.findall(r'\d+',ref.group(1)):
            if number not in byid:continue
            if e['descricao'].startswith('Publicado no DJEN'):byid[number]['publicacao']=date(when.group(1))
            elif e['descricao'].startswith('Disponibilizado no DJEN'):byid[number]['disponibilizacao']=date(when.group(1))
    return {'validado':True,'numero':number,'campos':{k:v for k,v in fields.items() if v},'partes':parties,'eventos':events,'prazos':deadlines,'avisos':list(dict.fromkeys(warnings))}


def enrich(store,db,payload,actor,import_id):
    import gestao
    db.execute('CREATE TABLE IF NOT EXISTS source_events(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES records(id),numero TEXT,data TEXT,payload TEXT,signature TEXT,import_id TEXT,UNIQUE(case_id,numero,signature))')
    db.execute('CREATE TABLE IF NOT EXISTS source_complements(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES records(id),tipo TEXT,payload TEXT,signature TEXT,import_id TEXT,UNIQUE(case_id,tipo,signature))')
    rows=listing(payload.get('paginas_da_lista',[]));bycase={}
    for row in rows:bycase.setdefault(row['numero'],[]).append(row)
    summary={'registros_lista':len(rows),'processos_lista':len(bycase),'detalhes_validos':0,'partes':0,'pessoas':0,'eventos':0,'prazos':0,'sem_data_lista':0,'avisos_estrutura':0,'complementos':0}
    for record in payload.get('processos',[]):
        parsed=detail(record);number=record.get('processo','')
        if not parsed['validado']:continue
        case=db.execute("SELECT * FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
        if not case:continue
        rid=case['id'];before=json.loads(case['data']);after={**before}
        for k,v in parsed['campos'].items():
            if not after.get(k):after[k]=v
        if after.get('titulo')=='Processo importado do eproc' or not after.get('titulo'):
            primary=' × '.join(p['nome'] for p in [p for p in parsed['partes'] if p['representa_indice'] is None][:2]) or number
            after['titulo']=primary
        if after!=before:
            db.execute('UPDATE records SET data=?,version=version+1,atualizado=?,atualizado_por=? WHERE id=?',(legal.dumps(after),legal.now(),actor['id'],rid))
            store.audit(db,actor,'estruturar_dados_eproc','processos',rid,before,after)
        summary['detalhes_validos']+=1;summary['avisos_estrutura']+=len(parsed['avisos'])
        linked=[]
        for party in parsed['partes']:
            parent=linked[party['representa_indice']] if party['representa_indice'] is not None else None
            identity=party.get('documento') or party.get('registro') or f"{number}:{party['papel']}:{planilhas.norm(party['nome'])}"
            person_key='pessoa:eproc:'+identity
            person_data={'nome':party['nome'],'tipo':party['tipo_pessoa'],'documento':party.get('documento',''),'observacoes':'Cadastro extraído de rótulo explícito no eproc; vínculo de cliente não presumido.'}
            pid,new=gestao.insert(store,db,'pessoas',person_data,actor,key=person_key);summary['pessoas']+=new
            data={k:v for k,v in party.items() if k not in ('representa_indice','tipo_pessoa')};data.update(pessoa_id=pid,representa_id=parent)
            key=f'parte:eproc:{rid}:{party["papel"]}:{identity}:{parent or ""}'
            part_id,new=gestao.insert(store,db,'partes',data,actor,rid,key);summary['partes']+=new;linked.append(part_id)
        for event in parsed['eventos']:
            cur=db.execute('INSERT OR IGNORE INTO source_events(case_id,numero,data,payload,signature,import_id) VALUES(?,?,?,?,?,?)',(rid,event['numero'],event['data'],legal.dumps(event),digest(event),import_id))
            summary['eventos']+=cur.rowcount
        for complement in (record.get('detalhes') or {}).get('complementos',[]):
            if not isinstance(complement,dict) or complement.get('tipo') not in ('pericias','audiencias','documentos','alvaras','custas','depositos','mapa_consultas'):continue
            cur=db.execute('INSERT OR IGNORE INTO source_complements(case_id,tipo,payload,signature,import_id) VALUES(?,?,?,?,?)',(rid,complement['tipo'],legal.dumps(complement),digest(complement),import_id))
            summary['complementos']+=cur.rowcount
        for deadline in parsed['prazos']:
            # All-party history is separate from the account's pending work queue.
            key=f'prazo:eproc:evento:{rid}:{deadline["evento"]}:'+digest(deadline)
            _,new=gestao.insert(store,db,'prazos',deadline,actor,rid,key);summary['prazos']+=new
        for warning in parsed['avisos']:
            gestao.insert(store,db,'anotacoes',{'titulo':'Conferência da estrutura eproc','texto':warning},actor,rid,'aviso:eproc:'+str(rid)+':'+digest(warning))
    valid_numbers={r['processo'] for r in payload.get('processos',[]) if r.get('detalhes') and re.search(r'Nº do processo\s*'+re.escape(r['processo']),r['detalhes'].get('texto',''))}
    for number,entries in bycase.items():
        case=db.execute("SELECT * FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
        if not case:continue
        rid=case['id'];before=json.loads(case['data']);after={**before}
        for field in ('classe','assunto','juizo_codigo'):
            if not after.get(field) and entries[0].get(field):after[field]=entries[0][field]
        if after!=before:
            db.execute('UPDATE records SET data=?,version=version+1,atualizado=?,atualizado_por=? WHERE id=?',(legal.dumps(after),legal.now(),actor['id'],rid))
            store.audit(db,actor,'estruturar_lista_eproc','processos',rid,before,after)
        # The list already exposes party roles/names/documents; no need to wait for all details.
        parents=flat_parties(entries[0]['partes_texto'])
        for person in parents:
            document=person.get('documento','');identity=document or f'{number}:{person["papel"]}:'+planilhas.norm(person['nome'])
            pid,new=gestao.insert(store,db,'pessoas',{'nome':person['nome'],'documento':document,'tipo':'pessoa_juridica' if len(document)==14 else 'pessoa_fisica' if len(document)==11 else 'outro','observacoes':'Papel e documento explícitos na lista do eproc.'},actor,key='pessoa:eproc:'+identity);summary['pessoas']+=new
            _,new=gestao.insert(store,db,'partes',{**person,'pessoa_id':pid},actor,rid,f'parte:eproc:{rid}:{person["papel"]}:{identity}:');summary['partes']+=new
        if parents and (not after.get('titulo') or after['titulo']=='Processo importado do eproc'):
            latest=json.loads(db.execute('SELECT data FROM records WHERE id=?',(rid,)).fetchone()[0]);filled={**latest,'titulo':' × '.join(p['nome'] for p in parents[:2])}
            db.execute('UPDATE records SET data=?,version=version+1,atualizado=?,atualizado_por=? WHERE id=?',(legal.dumps(filled),legal.now(),actor['id'],rid))
            store.audit(db,actor,'preencher_titulo_da_lista','processos',rid,latest,filled)
        occurrences={}
        for entry in entries:
            if not entry['vencimento']:summary['sem_data_lista']+=1;continue
            data={'titulo':clean(entry['descricao']),'data_inicio':entry['data_inicio'],'vencimento':entry['vencimento'],'data_envio':entry['envio'],
                'status':'pendente','escopo':'lista_da_conta','fonte':'eproc / lista de citações e intimações pendentes da conta','origem':'eproc','conferido':0,
                'observacoes':'Registro da lista da conta. A associação ao evento detalhado exige conferência quando não há identificador explícito.'}
            signature=digest({k:v for k,v in entry.items() if k not in ('pagina','linha','partes_texto')})
            occurrences[signature]=occurrences.get(signature,0)+1
            data['ocorrencia_lista']=occurrences[signature]
            key='prazo:eproc:lista:'+str(rid)+':'+signature+':'+str(occurrences[signature])
            _,new=gestao.insert(store,db,'prazos',data,actor,rid,key);summary['prazos']+=new
        gestao.ensure_review(store,db,db.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone(),actor)
    import eproc_relatorios
    summary['relatorios']=eproc_relatorios.save_reports(store,db,payload,import_id)
    return summary


def flat_parties(text):
    """Roles and documents explicitly separated by CR/LF in the eproc XLS export."""
    result=[];label=None;name=[]
    def flush(document=''):
        nonlocal name
        value=clean(' '.join(name))
        if label and value:
            result.append({'nome':value,'papel':role(label),'documento':re.sub(r'\D','',document),'origem':'eproc_planilha'})
        name=[]
    normalized={planilhas.norm(k):k for k in ROLE_LABELS}
    for raw in str(text or '').splitlines():
        line=clean(raw)
        if not line:continue
        key=planilhas.norm(line.rstrip(':'))
        if key in normalized:flush();label=normalized[key];continue
        if line=='X':flush();label=None;continue
        if not label:continue
        doc=DOCUMENT.fullmatch(line)
        if doc:flush(doc.group(1));continue
        embedded=DOCUMENT.search(line)
        if embedded:
            name.append(line[:embedded.start()]);flush(embedded.group(1))
        else:name.append(line)
    flush()
    return result
