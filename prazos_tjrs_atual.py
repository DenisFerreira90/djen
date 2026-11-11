"""Última lista completa de prazos em aberto da extensão do TJRS."""
import datetime as dt
import json
import re
import unicodedata

import eproc_estruturado
import juridico as legal

CAPTION = re.compile(
    r'Lista de Citacoes e Intimacoes Pendentes\s*\(([\d.]+)\s+registros?'
    r'(?:\s*[-–—:]\s*([\d.]+)\s+a\s+([\d.]+))?\)\s*:?$', re.I,
)


def validate(payload):
    execution = payload.get('execucao', {})
    if not isinstance(execution, dict):
        raise legal.AppError('Metadados de execução inválidos.')
    if execution.get('fonte_coleta') != 'extensao_tjrs':
        return None
    pages = payload.get('paginas_da_lista', [])
    pagination = execution.get('paginacao_lista', {})
    total = execution.get('registros_html')
    error = 'A lista atual do TJRS exige uma coleta completa e conferida da extensão.'
    if (execution.get('tribunal') != 'TJRS' or execution.get('sistema') != 'eproc'
        or execution.get('grau') != 1 or execution.get('escopo') != 'html_listas'
        or execution.get('cobertura_listas_conferida') is not True
        or payload.get('processos') != [] or not 1 <= len(pages) <= 200
        or type(total) is not int or total < 0 or execution.get('paginas_html') != len(pages)
        or not isinstance(pagination, dict) or pagination.get('completo') is not True
        or pagination.get('esperados') != total or pagination.get('registros') != total
        or pagination.get('paginas') != len(pages)):
        raise legal.AppError(error)
    try:
        timestamp = dt.datetime.fromisoformat(execution['fim'])
        if timestamp.utcoffset() is None:
            raise ValueError
        if timestamp > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=2):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise legal.AppError('Horário da captura do TJRS inválido. Confira o relógio do computador.') from None
    read = 0
    for number, page in enumerate(pages, 1):
        if (not isinstance(page, dict) or page.get('pagina_origem') != number
            or page.get('tribunal') != 'TJRS' or page.get('origem_relatorio')):
            raise legal.AppError(error)
        tables = page.get('tabelas')
        if not isinstance(tables, list) or len(tables) != 1 or not isinstance(tables[0], dict):
            raise legal.AppError(error)
        table = tables[0]
        title = unicodedata.normalize('NFKD', str(table.get('titulo', '')).replace('–', '-').replace('—', '-')).encode('ascii', 'ignore').decode()
        match = CAPTION.fullmatch(title)
        rows = table.get('linhas')
        if (not match or not isinstance(rows, list) or not rows
            or any(not isinstance(row, list) or any(not isinstance(cell, str) for cell in row) for row in rows)
            or not {'Processo', 'Evento e Prazo', 'Final Prazo'} <= set(rows[0])):
            raise legal.AppError(error)
        count, first, last = (int(part.replace('.', '')) if part and part.replace('.', '').isdigit() else None for part in match.groups())
        if first is None and last is None and len(pages) == 1:
            first, last = 1, total
        if (count != total or first != read + 1 or last != read + len(rows) - 1
            or (len(rows) == 1 and (total or len(pages) != 1))):
            raise legal.AppError(error)
        read = last
    entries = eproc_estruturado.listing(pages)
    if read != total or len(entries) != total or any('.8.21.' not in entry['numero'] for entry in entries):
        raise legal.AppError(error)
    return timestamp.astimezone(dt.timezone.utc), total


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS tjrs_lista_atual (
        singleton INTEGER PRIMARY KEY CHECK (singleton=1), capturado TEXT NOT NULL,
        assinatura TEXT NOT NULL, prazos TEXT NOT NULL, registros INTEGER NOT NULL,
        resumo TEXT NOT NULL
    )''')


def latest(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tjrs_lista_atual'").fetchone():
        return db.execute('SELECT * FROM tjrs_lista_atual WHERE singleton=1').fetchone()


def save(db, timestamp, signature, ids, total, summary):
    db.execute('INSERT OR REPLACE INTO tjrs_lista_atual VALUES(1,?,?,?,?,?)',
               (timestamp.isoformat(), signature, json.dumps(ids), total, legal.dumps(summary)))
