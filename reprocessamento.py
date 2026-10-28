"""Reestrutura os dados de origem já guardados. Não acessa a internet."""
import json
import re
import uuid
import juridico as legal
import gestao
import eproc_estruturado as eproc

HEADERS=['','Processo','Classe','Assunto','Evento e Prazo','Data envio requisição','Início Prazo','Final Prazo']


def sources(db,case):
    number=json.loads(case['data'])['numero']
    rows=db.execute("SELECT e.*,i.data AS importado_em FROM evidence e LEFT JOIN imports i ON i.id=e.import_id WHERE e.case_id=? ORDER BY e.id DESC",(case['id'],)).fetchall()
    detail=None;cells=[];list_import=None;source_id=None;date=None
    for row in rows:
        payload=json.loads(row['payload'])
        if detail is None and isinstance(payload,dict) and isinstance(payload.get('texto'),str) and isinstance(payload.get('tabelas'),list):
            parsed=eproc.detail({'processo':number,'detalhes':payload})
            if parsed['validado']:
                detail=payload;source_id=row['id'];date=row['importado_em']
        if row['source'].startswith('lista:') and isinstance(payload,dict) and isinstance(payload.get('celulas'),list):
            if list_import is None:list_import=row['import_id']
            cell=payload['celulas']
            if row['import_id']==list_import and len(cell)==8 and number in str(cell[1]):cells.append(cell)
    return {'detalhes':detail,'linhas':list(reversed(cells)),'evidencia_id':source_id,'importado_em':date}


def diagnose(store,rid):
    with store.lock,store.connect() as db:
        case=db.execute("SELECT * FROM records WHERE kind='processos' AND id=?",(rid,)).fetchone()
        if not case:raise legal.AppError('Processo não encontrado.',404)
        raw=sources(db,case);data=json.loads(case['data'])
        parsed=eproc.detail({'processo':data['numero'],'detalhes':raw['detalhes']}) if raw['detalhes'] else None
        missing=[k for k in ('tribunal','orgao','classe','competencia','autuacao') if not data.get(k)]
        return {'numero':data['numero'],'campos_vazios':missing,'origem_detalhada_disponivel':bool(raw['detalhes']),
                'linhas_lista_disponiveis':len(raw['linhas']),'evidencia_id':raw['evidencia_id'],'origem_importada_em':raw['importado_em'],
                'partes_na_origem':len(parsed['partes']) if parsed else 0,'eventos_na_origem':len(parsed['eventos']) if parsed else 0,
                'mensagem':'Há dados de origem válidos para preencher a ficha sem nova coleta.' if raw['detalhes'] else 'Não há página de detalhes válida guardada para este processo. Importe o ZIP da coleta ou faça uma consulta individual.'}


def repair(store,actor,rid=None):
    if actor['role']=='leitor':raise legal.AppError('Seu perfil permite apenas leitura.',403)
    with store.lock,store.connect() as db:
        gestao.schema(db)
        if rid:
            cases=db.execute("SELECT * FROM records WHERE kind='processos' AND id=?",(rid,)).fetchall()
            if not cases:raise legal.AppError('Processo não encontrado.',404)
        else:
            cases=db.execute("SELECT * FROM records WHERE kind='processos' AND (COALESCE(json_extract(data,'$.orgao'),'')='' OR COALESCE(json_extract(data,'$.classe'),'')='' OR json_extract(data,'$.titulo')='Processo importado do eproc')").fetchall()
        records=[];cells=[];unavailable=[]
        for case in cases:
            raw=sources(db,case);number=json.loads(case['data'])['numero']
            if raw['detalhes']:records.append({'processo':number,'detalhes':raw['detalhes'],'situacao':'reprocessado_da_origem_guardada'})
            else:unavailable.append(number)
            cells.extend(raw['linhas'])
        if not records and not cells:raise legal.AppError('Não há origem guardada para reprocessar. Importe o ZIP original em Coleta eproc ou faça uma consulta individual.',409)
        iid='reprocessamento:'+uuid.uuid4().hex
        db.execute('INSERT INTO imports VALUES(?,?,?,?)',(iid,legal.now(),actor['id'],'{}'))
        payload={'processos':records,'paginas_da_lista':[{'tabelas':[{'titulo':'Lista de origem guardada','linhas':[HEADERS,*cells]}]}]}
        result=eproc.enrich(store,db,payload,actor,iid)
        for case in cases:gestao.ensure_review(store,db,db.execute('SELECT * FROM records WHERE id=?',(case['id'],)).fetchone(),actor)
        result={**result,'processos_selecionados':len(cases),'sem_detalhes':unavailable,'consulta_tribunal_realizada':False}
        db.execute('UPDATE imports SET resumo=? WHERE id=?',(legal.dumps(result),iid))
        store.audit(db,actor,'reprocessar_origem_guardada','processos' if rid else 'sistema',rid or '',after=result)
        return result
