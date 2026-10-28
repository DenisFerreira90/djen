"""Organização, revisão interna, importação tabular e exportação por entidade."""
import datetime as dt
import hashlib
import json
import re
import unicodedata
import juridico as legal
import planilhas


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS imported_keys (key TEXT PRIMARY KEY, record_id INTEGER REFERENCES records(id))')
    db.execute('CREATE TABLE IF NOT EXISTS sync_state(numero TEXT PRIMARY KEY, fingerprint TEXT, checked_at TEXT, situacao TEXT, detalhes TEXT, erro TEXT, execucao TEXT)')


def insert(store,db,kind,data,actor,case_id=None,key=None):
    if key:
        prior=db.execute('SELECT record_id FROM imported_keys WHERE key=?',(key,)).fetchone()
        if prior:return prior[0],False
    rid=db.execute('INSERT INTO records(kind,case_id,data,criado,atualizado,criado_por,atualizado_por) VALUES(?,?,?,?,?,?,?)',
        (kind,case_id,legal.dumps(data),legal.now(),legal.now(),actor['id'],actor['id'])).lastrowid
    if key:db.execute('INSERT INTO imported_keys VALUES(?,?)',(key,rid))
    store.audit(db,actor,'importar' if key else 'criar',kind,rid,after=data)
    return rid,True


def ensure_review(store,db,case,actor):
    """One review per case. Its original date never drifts with synchronization."""
    rid=case['id']
    key='revisao-interna:'+str(rid)
    if db.execute("SELECT 1 FROM records WHERE kind='prazos' AND case_id=? AND json_extract(data,'$.status')='pendente' AND COALESCE(json_extract(data,'$.escopo'),'')!='todas_as_partes'",(rid,)).fetchone():
        prior=db.execute('SELECT r.* FROM records r JOIN imported_keys k ON k.record_id=r.id WHERE k.key=?',(key,)).fetchone()
        if prior:
            before=json.loads(prior['data'])
            if before.get('status') in ('a_fazer','em_andamento','aguardando'):
                after={**before,'status':'cancelada','conclusao':'Revisão interna substituída por vencimento oficial cadastrado; conferir o prazo na fonte.'}
                db.execute('UPDATE records SET data=?,version=version+1,atualizado=?,atualizado_por=? WHERE id=?',(legal.dumps(after),legal.now(),actor['id'],prior['id']))
                store.audit(db,actor,'substituir_revisao_interna','tarefas',prior['id'],before,after)
        return False
    if db.execute('SELECT 1 FROM imported_keys WHERE key=?',(key,)).fetchone():return False
    due=(dt.datetime.fromisoformat(case['criado']).date()+dt.timedelta(days=5)).isoformat()
    insert(store,db,'tarefas',{'titulo':'Revisar processo sem vencimento oficial','vencimento':due,'status':'a_fazer','prioridade':'normal',
        'origem':'revisao_interna','observacoes':'Meta interna de cinco dias corridos após o primeiro cadastro; não é prazo judicial.'},actor,rid,key)
    return True


def organize(store,actor):
    if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
    with store.lock,store.connect() as db:
        schema(db)
        count=sum(ensure_review(store,db,row,actor) for row in db.execute("SELECT * FROM records WHERE kind='processos' AND COALESCE(json_extract(data,'$.status'),'ativo')!='arquivado'").fetchall())
        store.audit(db,actor,'organizar_revisoes','sistema',after={'criadas':count})
        return {'criadas':count}


def agenda(store,filters=None,page=1):
    f=filters or {};today=legal.now()[:10];end=(dt.date.fromisoformat(today)+dt.timedelta(days=7)).isoformat()
    with store.lock,store.connect() as db:
        cases={r['id']:store.record(r) for r in db.execute("SELECT * FROM records WHERE kind='processos'")}
        items=[]
        for row in db.execute("SELECT * FROM records WHERE kind IN ('tarefas','prazos')"):
            r=store.record(row);d=r['dados']
            if d.get('escopo')=='todas_as_partes' and f.get('escopo')!='todas_as_partes':continue
            r['processo']=cases.get(r['processo_id'],{}).get('dados',{}).get('numero','')
            if f.get('responsavel') and str(d.get('responsavel_id') or '')!=str(f['responsavel']):continue
            if f.get('status') and d.get('status')!=f['status']:continue
            if f.get('origem')=='interna' and d.get('origem')!='revisao_interna':continue
            if f.get('origem')=='oficial' and r['tipo']!='prazos':continue
            value=(d.get('vencimento') or '')[:10]
            if f.get('de') and (not value or value<f['de']):continue
            if f.get('ate') and (not value or value>f['ate']):continue
            if f.get('periodo')=='vencidos' and (not value or value>=today):continue
            if f.get('periodo')=='hoje' and value!=today:continue
            if f.get('periodo')=='semana' and (not value or not today<=value<=end):continue
            if f.get('abertas') and d.get('status') not in ('pendente','a_fazer','em_andamento','aguardando'):continue
            items.append(r)
        items.sort(key=lambda r:(r['dados'].get('vencimento') or '9999',r['id']))
        return {'itens':items[(page-1)*50:page*50],'total':len(items),'pagina':page}


def attention(store,filters=None,page=1):
    f=filters or {};items=[]
    with store.lock,store.connect() as db:
        for row in db.execute("SELECT * FROM records WHERE kind='processos'"):
            r=store.record(row);d=r['dados'];reasons=[]
            if d.get('status')=='arquivado':continue
            if d.get('revisao'):reasons.append('Conferência pendente')
            if not d.get('responsavel_id'):reasons.append('Sem responsável')
            if not db.execute("SELECT 1 FROM records WHERE kind='prazos' AND case_id=? AND json_extract(data,'$.status')='pendente' AND COALESCE(json_extract(data,'$.escopo'),'')!='todas_as_partes'",(r['id'],)).fetchone():reasons.append('Sem prazo oficial pendente')
            if f.get('responsavel') and str(d.get('responsavel_id') or '')!=str(f['responsavel']):continue
            if f.get('q') and f['q'].lower() not in legal.dumps(d).lower():continue
            if reasons:r['motivos']=reasons;items.append(r)
        return {'itens':items[(page-1)*50:page*50],'total':len(items),'pagina':page}


def timeline(store,rid):
    with store.lock,store.connect() as db:
        linked=[r[0] for r in db.execute('SELECT id FROM records WHERE case_id=?',(rid,))]+[rid]
        marks=','.join('?' for _ in linked)
        events=[dict(r) for r in db.execute(f'SELECT id,data,actor_name,acao,entidade,entidade_id,antes,depois FROM audit WHERE entidade_id IN ({marks}) ORDER BY id DESC',list(map(str,linked))) if r['entidade'] in legal.KINDS]
        return events


def normalized_rows(sheet,header_index,mapping):
    rows=sheet['linhas'];errors=[];valid=[]
    if not isinstance(mapping,dict) or set(mapping)-set(planilhas.FIELDS):raise legal.AppError('Mapeamento inválido.')
    if 'numero' not in mapping:raise legal.AppError('Selecione a coluna do número do processo.')
    indexes=[v for v in mapping.values() if v is not None]
    if any(type(v) is not int or v<0 or v>=200 for v in indexes):raise legal.AppError('Índice de coluna inválido.')
    for index,row in enumerate(rows[header_index+1:],header_index+2):
        if not any(str(v).strip() for v in row):continue
        try:
            data={k:str(row[v]).strip() if v is not None and v<len(row) else '' for k,v in mapping.items()}
            raw=data['numero']
            if not (legal.CNJ.fullmatch(raw) or re.fullmatch(r'\d{20}',raw)):raise ValueError('Número CNJ inválido; mantenha o processo como texto no Excel.')
            digits=re.sub(r'\D','',raw)
            data['numero']=f'{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:]}'
            for field in ('disponibilizacao','publicacao','vencimento','data_fatal','data_envio','data_inicio'):
                if data.get(field):data[field]=planilhas.date(data[field],sheet.get('epoca','1899-12-30'))
            if data.get('data_fatal') and not data.get('vencimento'):data['vencimento']=data['data_fatal']
            if data.get('partes_texto'):
                from eproc_estruturado import flat_parties
                data['partes_identificadas']=flat_parties(data['partes_texto'])
                if not data['partes_identificadas']:raise ValueError('A célula de partes não contém papéis e nomes reconhecíveis. Confira o mapeamento.')
            valid.append({'linha':index,'dados':data,'original':row})
        except (ValueError,KeyError) as exc:errors.append({'linha':index,'erro':str(exc)})
    return valid,errors


def import_table(store,sheet,header,mapping,actor,filename='planilha',preview=False):
    if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
    valid,errors=normalized_rows(sheet,header,mapping)
    summary={'validas':len(valid),'invalidas':len(errors),'erros':errors,'amostra':valid[:10],'processos_unicos':len({r['dados']['numero'] for r in valid})}
    if preview:return summary
    if errors:raise legal.AppError('Há linhas inválidas. Corrija a planilha antes de confirmar. Nenhuma linha desta importação foi gravada.')
    if not valid:raise legal.AppError('Nenhuma linha válida encontrada.')
    iid='planilha:'+hashlib.sha256(legal.dumps({'rows':sheet['linhas'],'mapping':mapping,'header':header}).encode()).hexdigest()
    with store.lock,store.connect() as db:
        schema(db)
        previous=db.execute('SELECT resumo FROM imports WHERE id=?',(iid,)).fetchone()
        if previous:
            old=json.loads(previous[0]);store.audit(db,actor,'importacao_repetida','importacoes',iid)
            return {**old,'criados':0,'partes':0,'prazos':0,'revisoes':0,'campos_preenchidos':0,'conflitos_de_prazo':0,'intimacoes_reconciliadas':0,'repetido':True}
        db.execute('INSERT INTO imports VALUES(?,?,?,?)',(iid,legal.now(),actor['id'],'{}'))
        created=parts=deadlines=reviews=filled=conflicts=reconciled=0
        deadline_occurrences={}
        for row in valid:
            data=row['dados'];number=data['numero']
            existing=db.execute("SELECT * FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(number,)).fetchone()
            cdata={k:data[k] for k in ('numero','titulo','tribunal','orgao','classe','categoria','disponibilizacao','publicacao','observacoes','assunto','juizo_codigo') if data.get(k)}
            if data.get('partes_identificadas') and not cdata.get('titulo'):
                names=[p['nome'] for p in data['partes_identificadas'][:2]]
                cdata['titulo']=' × '.join(names)
            if existing:
                rid=existing['id'];old=json.loads(existing['data']);merged={**old}
                for k,v in cdata.items():
                    if not merged.get(k) or (k=='titulo' and merged[k]=='Processo importado do eproc'):merged[k]=v
                if merged!=old:
                    db.execute('UPDATE records SET data=?,version=version+1,atualizado=?,atualizado_por=? WHERE id=?',(legal.dumps(merged),legal.now(),actor['id'],rid))
                    store.audit(db,actor,'preencher_campos_vazios','processos',rid,before=old,after=merged);filled+=1
            else:
                rid,_=insert(store,db,'processos',{'status':'ativo','revisao':1,**cdata},actor,key='processo:'+number);created+=1
            for role in ('autor','reu','advogado','defensor'):
                for name in re.split(r'[;\n]+',data.get(role,'')):
                    name=name.strip()
                    if not name:continue
                    key=f'parte:{rid}:{role}:'+planilhas.norm(name)
                    _,new=insert(store,db,'partes',{'nome':name,'papel':role,'origem':'planilha','observacoes':'Importado por coluna explicitamente mapeada; representação deve ser conferida.'},actor,rid,key);parts+=new
            for person in data.get('partes_identificadas',[]):
                document=person.get('documento','');identity=document or f'{number}:{person["papel"]}:'+planilhas.norm(person['nome'])
                pid,_=insert(store,db,'pessoas',{'nome':person['nome'],'documento':document,'tipo':'pessoa_juridica' if len(document)==14 else 'pessoa_fisica' if len(document)==11 else 'outro','observacoes':'Extraído de papel e documento explícitos no XLS do eproc.'},actor,key='pessoa:eproc:'+identity)
                _,new=insert(store,db,'partes',{**person,'pessoa_id':pid},actor,rid,f'parte:eproc:{rid}:{person["papel"]}:{identity}:');parts+=new
            if data.get('nome_parte'):
                role=data.get('papel','outro') or 'outro'
                key=f'parte:{rid}:{role}:'+planilhas.norm(data['nome_parte'])
                _,new=insert(store,db,'partes',{'nome':data['nome_parte'],'papel':role,'oab':data.get('oab',''),'uf':data.get('uf',''),'origem':'planilha'},actor,rid,key);parts+=new
            if data.get('vencimento'):
                key='prazo:'+str(rid)+':'+(data.get('evento') or hashlib.sha256(legal.dumps({k:data.get(k,'') for k in ('vencimento','data_fatal','prazo_titulo','publicacao')}).encode()).hexdigest())
                if not data.get('evento'):
                    deadline_occurrences[key]=deadline_occurrences.get(key,0)+1
                    key+=':ocorrencia:'+str(deadline_occurrences[key])
                if data.get('partes_texto') and not data.get('evento') and not db.execute('SELECT 1 FROM imported_keys WHERE key=?',(key,)).fetchone():
                    description=' '.join((data.get('prazo_titulo') or '').split())
                    possible=[r for r in db.execute("SELECT id,data FROM records WHERE kind='prazos' AND case_id=? AND json_extract(data,'$.vencimento')=? AND json_extract(data,'$.escopo')='lista_da_conta' ORDER BY id",(rid,data['vencimento'])) if ' '.join(json.loads(r['data']).get('titulo','').split())==description]
                    occurrence=deadline_occurrences.get(key.rsplit(':ocorrencia:',1)[0],1)
                    if len(possible)>=occurrence:
                        reconciled+=1
                        db.execute('INSERT INTO imported_keys VALUES(?,?)',(key,possible[occurrence-1]['id']))
                        store.audit(db,actor,'vincular_planilha_a_intimacao','prazos',possible[occurrence-1]['id'],after={'arquivo':filename,'linha':row['linha']})
                previous_deadline=db.execute('SELECT r.data FROM records r JOIN imported_keys k ON k.record_id=r.id WHERE k.key=?',(key,)).fetchone()
                if previous_deadline and json.loads(previous_deadline[0]).get('vencimento')!=data['vencimento']:
                    conflicts+=1
                    old_due=json.loads(previous_deadline[0]).get('vencimento')
                    insert(store,db,'anotacoes',{'titulo':'Divergência de vencimento na importação','texto':f'Evento {data.get("evento","")}: cadastro anterior {old_due}; novo arquivo {data["vencimento"]}. Data anterior preservada. Conferir fonte antes de corrigir.'},actor,rid,key+':divergencia:'+data['vencimento'])
                    current=db.execute('SELECT data FROM records WHERE id=?',(rid,)).fetchone();before=json.loads(current[0]);after={**before,'revisao':1}
                    db.execute('UPDATE records SET data=?,version=version+1,atualizado=?,atualizado_por=? WHERE id=?',(legal.dumps(after),legal.now(),actor['id'],rid))
                    store.audit(db,actor,'divergencia_de_prazo','processos',rid,before,after)
                _,new=insert(store,db,'prazos',{'titulo':data.get('prazo_titulo') or 'Prazo importado — conferir','vencimento':data['vencimento'],
                    'data_fatal':data.get('data_fatal',''),'status':'pendente','fonte':'Planilha: '+filename[:150], 'conferido':0,'origem':'eproc_planilha' if data.get('partes_texto') else 'planilha','evento':data.get('evento',''),'data_inicio':data.get('data_inicio',''),'data_envio':data.get('data_envio',''),'escopo':'lista_da_conta' if data.get('partes_texto') else 'cadastro_da_equipe'},actor,rid,key);deadlines+=new
            db.execute('INSERT INTO evidence(import_id,case_id,source,payload) VALUES(?,?,?,?)',(iid,rid,'planilha:linha:'+str(row['linha']),legal.dumps({'arquivo':filename,'campos':data,'celulas':row['original']})))
        for ridrow in db.execute("SELECT * FROM records WHERE kind='processos'").fetchall():reviews+=ensure_review(store,db,ridrow,actor)
        result={'criados':created,'partes':parts,'prazos':deadlines,'revisoes':reviews,'campos_preenchidos':filled,'conflitos_de_prazo':conflicts,'intimacoes_reconciliadas':reconciled,'processos_unicos':len({r['dados']['numero'] for r in valid}),'linhas':len(valid),'metadados_fonte':sheet.get('metadados',{}),'id':iid}
        db.execute('UPDATE imports SET resumo=? WHERE id=?',(legal.dumps(result),iid))
        store.audit(db,actor,'importar_planilha','importacoes',iid,after=result)
        return result


def export_sheets(store,actor):
    with store.lock,store.connect() as db:
        records=[store.record(r) for r in db.execute('SELECT * FROM records ORDER BY id')]
        users={r['id']:r['nome'] for r in db.execute('SELECT * FROM users')}
        cases={r['id']:r['dados']['numero'] for r in records if r['tipo']=='processos'}
        result=[]
        columns={
          'processos':['numero','titulo','tribunal','orgao','classe','categoria','situacao_origem','competencia','autuacao','juiz','assunto','juizo_codigo','status','responsavel_id','disponibilizacao','publicacao','revisao','observacoes'],
          'partes':['nome','papel','representa_id','oab','uf','documento','registro','papel_origem','origem','observacoes'],
          'prazos':['titulo','vencimento','data_fatal','status','responsavel_id','fonte','conferido','evento','escopo','destinatario','status_origem','quantidade_dias','publicacao','disponibilizacao','conclusao'],
          'tarefas':['titulo','vencimento','status','prioridade','responsavel_id','origem','conclusao','observacoes'],
          'pessoas':['nome','tipo','documento','email','telefone','endereco','observacoes'],
          'financeiro':['titulo','natureza','valor_centavos','vencimento','status','categoria','observacoes'],
          'documentos':['titulo','categoria','referencia','status','observacoes']}
        for kind,fields in columns.items():
            if kind=='processos':fields=[f for f in fields if f!='numero']
            titles={**planilhas.FIELDS,'status':'Situação','responsavel_id':'Responsável','revisao':'Conferência pendente','nome':'Nome','papel':'Papel','representa_id':'Parte representada (ID)','oab':'OAB','uf':'UF','conferido':'Conferido','origem':'Origem','conclusao':'Providência tomada','prioridade':'Prioridade','documento':'CPF / CNPJ','email':'E-mail','telefone':'Telefone','endereco':'Endereço','tipo':'Tipo','natureza':'Receber / pagar','valor_centavos':'Valor (R$)','referencia':'Referência do documento'}
            rows=[['ID','Processo',*[('Descrição do prazo' if kind=='prazos' and f=='titulo' else 'Vencimento financeiro' if kind=='financeiro' and f=='vencimento' else 'Vencimento da tarefa' if kind=='tarefas' and f=='vencimento' else titles.get(f,f)) for f in fields],'Criado em','Atualizado em','Alterado por']]
            for r in records:
                if r['tipo']!=kind:continue
                if kind=='prazos' and r['dados'].get('escopo')=='todas_as_partes':continue
                values=[]
                for f in fields:
                    v=r['dados'].get(f,'')
                    if f=='responsavel_id':v=users.get(v,'')
                    elif f=='valor_centavos' and v!='':v=v/100
                    elif f in ('vencimento','data_fatal','disponibilizacao','publicacao') and v:
                        try:v=dt.datetime.fromisoformat(v)
                        except ValueError:pass
                    values.append(v)
                rows.append([r['id'],cases.get(r['processo_id'],'') if kind!='processos' else r['dados']['numero'],*values,dt.datetime.fromisoformat(r['criado']),dt.datetime.fromisoformat(r['atualizado']),users.get(r['atualizado_por'],'')])
            result.append((kind.title(),rows))
        historical=[['ID','Processo','Evento','Destinatário','Vencimento','Início','Situação na origem','Prazo em dias','Publicação','Disponibilização']]
        for r in records:
            if r['tipo']!='prazos' or r['dados'].get('escopo')!='todas_as_partes':continue
            d=r['dados'];dates=[]
            for k in ('vencimento','data_inicio','publicacao','disponibilizacao'):
                v=d.get(k,'')
                try:v=dt.datetime.fromisoformat(v)
                except ValueError:pass
                dates.append(v)
            historical.append([r['id'],cases.get(r['processo_id'],''),d.get('evento',''),d.get('destinatario',''),dates[0],dates[1],d.get('status_origem',''),d.get('quantidade_dias',''),dates[2],dates[3]])
        if len(historical)>1:result.append(('Historico prazos',historical))
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='source_events'").fetchone():
            event_rows=[['ID','Processo','Evento','Data / hora','Descrição','Usuário no eproc','Referências de documentos','Importação']]
            for item in db.execute('SELECT * FROM source_events ORDER BY case_id,CAST(numero AS INTEGER) DESC'):
                event=json.loads(item['payload']);when=event.get('data','')
                try:when=dt.datetime.fromisoformat(when)
                except ValueError:pass
                event_rows.append([item['id'],cases.get(item['case_id'],''),event['numero'],when,event['descricao'],event['usuario_origem'],event['documentos_referencias'],item['import_id']])
            result.append(('Eventos eproc',event_rows))
        if actor['role']=='administrador':
            rows=[['ID','Data','Usuário','Ação','Cadastro','Registro','Antes','Depois']]
            rows.extend([[r['id'],dt.datetime.fromisoformat(r['data']),r['actor_name'],r['acao'],r['entidade'],r['entidade_id'],r['antes'] or '',r['depois'] or ''] for r in db.execute('SELECT * FROM audit ORDER BY id')])
            result.append(('Auditoria',rows))
        store.audit(db,actor,'exportar_excel','sistema',after={'abas':len(result)})
        return result


def sync_plan(store,number,fingerprint,mode='incremental'):
    with store.lock,store.connect() as db:
        schema(db);row=db.execute('SELECT * FROM sync_state WHERE numero=?',(number,)).fetchone()
        if mode in ('completa','individual'):return True,'Consulta solicitada'
        if not row:return True,'Processo novo ou sem leitura confirmada'
        if row['situacao']!='lido':return True,'Leitura anterior pendente ou com falha'
        if mode=='falhas':return False,'Leitura anterior concluída'
        if not fingerprint or row['fingerprint']!=fingerprint:return True,'Linha da lista alterada ou sem marcador'
        if not row['checked_at'] or (dt.datetime.fromisoformat(legal.now())-dt.datetime.fromisoformat(row['checked_at'])).total_seconds()>=7*86400:return True,'Revisão periódica de sete dias'
        return False,'Sem alteração identificada na lista; detalhes lidos há menos de sete dias'


def sync_save(store,number,fingerprint,record,run):
    with store.lock,store.connect() as db:
        schema(db)
        ok=record.get('detalhes') is not None and record.get('gravado_no_sistema',True) and (record.get('detalhes') or {}).get('cobertura_eventos',{}).get('completo',True)
        db.execute('INSERT OR REPLACE INTO sync_state VALUES(?,?,?,?,?,?,?)',(number,fingerprint,legal.now() if ok else None,'lido' if ok else 'falha',legal.dumps(record.get('detalhes')) if ok else None,'' if ok else record.get('situacao','falha'),run))


def sync_rows(store):
    with store.lock,store.connect() as db:
        schema(db);return [dict(r) for r in db.execute('SELECT numero,checked_at,situacao,erro,execucao FROM sync_state ORDER BY checked_at DESC')]


def fingerprints_from_pages(pages):
    values={}
    for page in pages:
        report=bool(page.get('origem_relatorio'))
        for table in page.get('tabelas',[]):
            for row in table.get('linhas',[]):
                if report and row and legal.CNJ.search(str(row[0])):
                    number=legal.CNJ.search(str(row[0])).group();values.setdefault(number,set()).add(legal.dumps(row));continue
                text=' '.join(str(v) for v in row)
                numbers=legal.CNJ.findall(text)
                # Exclude layout rows containing an entire nested table.
                if len(set(numbers))!=1:continue
                values.setdefault(numbers[0],set()).add(' '.join(text.split()))
    return {k:hashlib.sha256('\n'.join(sorted(v)).encode()).hexdigest() for k,v in values.items()}


def backup(store,actor):
    import io,sqlite3,tempfile,zipfile
    if actor['role']!='administrador':raise legal.AppError('Backup restrito ao administrador.',403)
    with store.lock,store.connect() as db:
        store.audit(db,actor,'gerar_backup','sistema');db.commit()
        with tempfile.TemporaryDirectory() as temp:
            path=__import__('pathlib').Path(temp)/'juridico.sqlite3'
            target=sqlite3.connect(path)
            try:
                db.backup(target);target.execute('DELETE FROM sessions');target.commit()
            finally:target.close()
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
                archive.write(path,'juridico.sqlite3')
                archive.writestr('manifesto.json',legal.dumps({'formato':'ara-backup-v1','data':legal.now(),'inclui':'Cadastros, usuários, auditoria, evidências e controle incremental. Não inclui a sessão do eproc nem arquivos da pasta dados_eproc.'}))
            return out.getvalue()


def restore(store,data,actor):
    import io,sqlite3,tempfile,zipfile
    from pathlib import Path
    if actor['role']!='administrador':raise legal.AppError('Restauração restrita ao administrador.',403)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest=json.loads(archive.read('manifesto.json'))
            info=archive.getinfo('juridico.sqlite3')
            if manifest.get('formato')!='ara-backup-v1' or info.file_size>128*1024*1024:raise ValueError()
            content=archive.read(info)
    except (ValueError,KeyError,zipfile.BadZipFile):raise legal.AppError('Backup inválido. Use um ZIP gerado por este sistema.')
    with tempfile.TemporaryDirectory() as temp,store.lock:
        path=Path(temp)/'incoming.sqlite3';path.write_bytes(content)
        src=sqlite3.connect(path)
        try:
            if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise legal.AppError('O banco do backup está corrompido.')
            tables={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'users','records','audit','sessions','evidence','imports'}<=tables:raise legal.AppError('Estrutura de backup incompatível.')
            previous=backup(store,actor)
            directory=store.path.parent/'backups';directory.mkdir(exist_ok=True)
            saved=directory/('antes-restauracao-'+__import__('uuid').uuid4().hex+'.zip');saved.write_bytes(previous)
            target=store.connect()
            try:
                src.backup(target)
                target.execute('DELETE FROM sessions')
                user=target.execute('SELECT id,nome FROM users WHERE login=?',(actor['login'],)).fetchone()
                who={'id':user[0] if user else None,'nome':actor['nome']}
                store.audit(target,who,'restaurar_backup','sistema',after={'backup_data':manifest.get('data'),'backup_anterior':saved.name,'solicitado_por':actor['login']})
                target.commit()
            finally:target.close()
            return {'restaurado':True,'backup_anterior':saved.name,'reentrar':True}
        except sqlite3.DatabaseError:raise legal.AppError('Não foi possível ler o banco do backup.')
        finally:src.close()


def compare_sources(store,rid):
    import difflib
    with store.lock,store.connect() as db:
        groups=db.execute('SELECT import_id,MAX(id) AS latest FROM evidence WHERE case_id=? GROUP BY import_id ORDER BY latest DESC LIMIT 2',(rid,)).fetchall()
        if len(groups)<2:return {'disponivel':False,'mensagem':'São necessárias duas importações com dados de origem para comparar.'}
        def source(iid):
            entries=[json.loads(r[0]) for r in db.execute('SELECT payload FROM evidence WHERE case_id=? AND import_id=? ORDER BY source',(rid,iid))]
            return json.dumps(entries,ensure_ascii=False,indent=2).splitlines()
        older,newer=groups[1]['import_id'],groups[0]['import_id']
        changes=list(difflib.unified_diff(source(older),source(newer),fromfile=older,tofile=newer,lineterm=''))
        return {'disponivel':True,'antes':older,'depois':newer,'linhas':changes[:1000],'truncado':len(changes)>1000,'alterado':bool(changes)}
