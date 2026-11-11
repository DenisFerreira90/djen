"""Seleção e identificação persistente das novidades de mandados para o Gmail."""
import hashlib
import json
import re

import juridico as legal
import mandados

LABELS = {
    'possivel_pedido': 'Pedido identificado',
    'possivel_expedicao': 'Possível expedição',
    'possivel_cumprimento': 'Possível cumprimento',
    'revisar_negativa_ou_alteracao': 'Negativa ou alteração para conferir',
}


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS email_mandate_events(
        chave TEXT PRIMARY KEY, delivery_id INTEGER
    )''')


def fingerprint(row):
    payload = json.loads(row['payload'] or '{}')
    text = ' '.join(str(row['trecho']).split())
    refs = str(payload.get('documentos_referencias') or '')
    # Compare references by label. Links and tokens can change with each session.
    documents = sorted(set(re.findall(r'\b[A-Z][A-Z0-9_]*\d+\b', refs)))
    return hashlib.sha256(legal.dumps([row['numero'], row['evento'], row['data_evento'], text, documents]).encode()).hexdigest()


def candidates(db, latest=True):
    scoped = db.execute("SELECT 1 FROM mandate_state WHERE chave='somente_lista' AND valor='1'").fetchone()
    source_exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='source_events'").fetchone()
    if not source_exists:
        return
    query = '''SELECT a.*, e.payload FROM mandate_alerts a
        JOIN source_events e ON e.id=a.event_id WHERE 1=1'''
    if latest:
        query += ''' AND NOT EXISTS (SELECT 1 FROM source_events later
                       WHERE later.case_id=e.case_id AND later.numero=e.numero AND later.id>e.id)'''
    if scoped:
        query += ' AND a.numero IN (SELECT numero FROM mandate_watchlist)'
    for row in db.execute(query + ' ORDER BY a.id'):
        category = mandados.classify(row['trecho'])
        if category in LABELS:
            yield fingerprint(row), row, category


def seed(db):
    schema(db)
    db.executemany('INSERT OR IGNORE INTO email_mandate_events(chave) VALUES(?)',
                   [(key,) for key, _, _ in candidates(db, latest=False)])


def pending(db, limit=50):
    seen = {r[0] for r in db.execute('SELECT chave FROM email_mandate_events')}
    selected = []
    for key, row, category in candidates(db):
        if key in seen:
            continue
        seen.add(key)
        selected.append((key, row, category))
        if len(selected) >= limit:
            break
    return selected


def message(items):
    lines = ['ConectaAdv | Novidades de mandados', '',
             'Movimentações importadas para conferência no processo de origem.', '']
    for _, row, category in items:
        lines.extend([LABELS[category],
                      f"Processo {row['numero']} · evento {row['evento']}",
                      str(row['data_evento'] or 'Data não informada'), row['trecho'], ''])
    lines.append('Confira a movimentação e o documento no tribunal antes de tomar providências.')
    return '\n'.join(lines)
