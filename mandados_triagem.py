"""Consulta local de ações de busca e apreensão e representação por CPF."""
import json
import re

import eproc_estruturado
import eproc_tribunais
import juridico as legal
from mandados import normalize, number
from origem_registros import provenance


PAGE_SIZE = 25
LAWYER_ROLES = {'advogado', 'advogada'}
DEFENDANT_ROLES = {'reu', 'requerido', 'executado', 'demandado', 'embargado'}
NO_LAWYER = {
    'sem advogado', 'sem advogados', 'nao possui advogado',
    'nenhum advogado cadastrado', 'nenhum advogado vinculado',
}


def cpf_value(value):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if not re.fullmatch(r'[0-9]{11}|[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}', value):
        return ''
    return re.sub(r'\D', '', value)


def lawyer(data):
    return {key: data.get(key, '') for key in ('nome', 'oab', 'uf', 'registro')}


def explicit_absence(detail, cpf):
    for table in detail.get('tabelas', []):
        if table.get('titulo') != 'Partes e Representantes':
            continue
        for row in table.get('linhas', []):
            for cell in row:
                lines = [eproc_estruturado.clean(line) for line in str(cell).splitlines() if line.strip()]
                if not lines:
                    continue
                doc = eproc_estruturado.DOCUMENT.search(lines[0])
                if doc and cpf_value(doc.group(1)) == cpf:
                    for line in lines[1:]:
                        if eproc_estruturado.DOCUMENT.search(line):
                            break
                        if normalize(line).rstrip('.:') in NO_LAWYER:
                            return True
    return False


def representation(db, case_id, cnj, cpf, local_lawyers):
    captured = db.execute("""SELECT e.payload, i.data FROM evidence e
        JOIN imports i ON i.id=e.import_id
        WHERE e.case_id=? AND e.source LIKE 'detalhes:%'
        ORDER BY i.data DESC, e.id DESC LIMIT 1""", (case_id,)).fetchone()
    if captured:
        if not cpf:
            return 'a_conferir', [], captured['data']
        raw = json.loads(captured['payload'])
        parsed = eproc_estruturado.detail({'processo': cnj, 'detalhes': raw})
        parties = parsed['partes']
        matched = {i for i, p in enumerate(parties)
                   if p['representa_indice'] is None and cpf_value(p.get('documento')) == cpf}
        linked = [lawyer(p) for p in parties
                  if p['representa_indice'] in matched and p['papel'] in LAWYER_ROLES]
        status = 'com_advogado' if linked else (
            'sem_advogado' if len(matched) == 1 and explicit_absence(raw, cpf) else 'a_conferir')
        return status, linked, captured['data']
    return ('com_advogado' if local_lawyers else 'a_conferir'), local_lawyers, ''


def parties_for_cases(db, cases, cpf):
    if not cases:
        return {}, {}
    sql = """SELECT p.id,p.case_id,p.data,person.data AS person_data
        FROM records p LEFT JOIN records person
        ON person.id=json_extract(p.data,'$.pessoa_id') AND person.kind='pessoas'
        WHERE p.kind='partes'"""
    # Without a CPF filter, only the visible page needs party and representation details.
    selected = () if cpf else tuple(cases)
    if selected:
        sql += ' AND p.case_id IN (' + ','.join('?' for _ in selected) + ')'
    clients, lawyers = {}, {}
    for row in db.execute(sql + ' ORDER BY p.id', selected):
        case_id = row['case_id']
        if case_id not in cases:
            continue
        party = json.loads(row['data'])
        parent = party.get('representa_id')
        role = normalize(str(party.get('papel') or ''))
        if parent:
            if role in LAWYER_ROLES:
                lawyers.setdefault((case_id, str(parent)), []).append(lawyer(party))
            continue
        if role in LAWYER_ROLES or (not cpf and role not in DEFENDANT_ROLES):
            continue
        person = json.loads(row['person_data']) if row['person_data'] else {}
        document = cpf_value(party.get('documento') or person.get('documento'))
        if cpf and document != cpf:
            continue
        name = party.get('nome') or person.get('nome') or ''
        clients.setdefault(case_id, []).append((str(row['id']), name, role, document))
    return clients, lawyers


def search(store, query, page):
    raw_cpf = query.get('cpf', '')
    cpf = cpf_value(raw_cpf)
    if raw_cpf and not cpf:
        raise legal.AppError('Informe um CPF com 11 dígitos.')
    raw_cnj = query.get('numero', '')
    cnj = number(raw_cnj) if raw_cnj else ''
    if raw_cnj and not cnj:
        raise legal.AppError('Informe o número CNJ completo do processo.')
    with store.lock, store.connect() as db:
        cases = {}
        clause = "json_extract(data,'$.numero')=?" if cnj else "json_extract(data,'$.numero') LIKE ?"
        for row in db.execute("SELECT id,data FROM records WHERE kind='processos' AND "+clause+" ORDER BY atualizado DESC,id DESC", (cnj or '%.8.21.%',)):
            data = json.loads(row['data'])
            if eproc_tribunais.from_number(data.get('numero','')) == 'TJRS' and re.search(
                    r'\bbusca\s+e\s+apreensao\b', normalize(str(data.get('classe') or ''))):
                cases[row['id']] = data
        if cpf:
            clients, lawyers = parties_for_cases(db, cases, cpf)
            cases = {key: data for key, data in cases.items() if key in clients}
        total = len(cases)
        visible = list(cases)[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
        if not cpf:
            clients, lawyers = parties_for_cases(db, visible, '')
        items = []
        for key in visible:
            data = cases[key]
            status, attorneys, observed = 'cpf_nao_informado', [], ''
            entries = clients.get(key, [])
            if cpf:
                local = [attorney for party_id, *_ in entries for attorney in lawyers.get((key,party_id),[])]
                status, attorneys, observed = representation(db, key, data['numero'], cpf, local)
            parties = []
            for party_id, name, role, document in entries:
                state, linked, date = (status, attorneys, observed) if cpf else representation(
                    db, key, data['numero'], document, lawyers.get((key, party_id), []))
                parties.append({'nome':name,'papel':role,'representacao':state,'advogados':linked,'importado_em':date})
            names = list(dict.fromkeys(p['nome'] for p in parties if p['nome'])) if cpf else []
            items.append({'case_id':key,'numero':data['numero'],'classe':data['classe'],'clientes':names,
                          'representacao':status,'advogados':attorneys,'importado_em':observed,
                          'partes':parties,
                          'origem':provenance(data,case_id=key)})
    return {'itens':items,'total':total,'pagina':page,'limite':PAGE_SIZE}
