import copy
import datetime as dt
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import juridico
import painel_operacional


def export(count, minutes_ago):
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    due = juridico.now()[:10]
    rows = [['Processo', 'Classe', 'Evento e Prazo', 'Final Prazo']]
    rows.extend([f'{index:07}-00.2026.8.21.0001', 'Busca e apreensão', 'Intimação', due]
                for index in range(1, count + 1))
    return {
        'processos': [],
        'execucao': {'id': f'teste-{count}-{minutes_ago}', 'tribunal': 'TJRS', 'sistema': 'eproc', 'grau': 1,
                     'fim': now.isoformat(), 'escopo': 'html_listas', 'fonte_coleta': 'extensao_tjrs',
                     'cobertura_listas_conferida': True, 'registros_html': count, 'paginas_html': 1,
                     'paginacao_lista': {'registros': count, 'esperados': count, 'paginas': 1, 'completo': True}},
        'paginas_da_lista': [{'tribunal': 'TJRS', 'pagina_origem': 1, 'tabelas': [
            {'titulo': f'Lista de Citações e Intimações Pendentes ({count} registros):', 'linhas': rows}
        ]}]
    }


class CurrentTJRS(unittest.TestCase):
    def test_full_snapshot_replaces_counts_and_keeps_history(self):
        with TemporaryDirectory() as directory:
            store = juridico.Store(Path(directory) / 'db.sqlite3')
            admin = store.create_user({'nome': 'Admin', 'login': 'admin', 'senha': 'senha-forte-123'}, setup=True)
            report = lambda: painel_operacional.report(store, admin)
            due = juridico.now()[:10]
            old = export(12, 10)
            store.import_corpus(old, admin)
            self.assertEqual(report()['contagens']['fatais_hoje'], 12)
            self.assertEqual(report()['contagens']['mandados_fatais_hoje'], 12)
            current = export(8, 5)
            store.import_corpus(current, admin)
            self.assertEqual(report()['contagens']['fatais_hoje'], 8)
            self.assertEqual(report()['contagens']['mandados_fatais_hoje'], 8)
            self.assertEqual(len(report()['listas']['fatais_hoje']), 8)
            with store.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM records WHERE kind='prazos'").fetchone()[0], 12)
            case = store.list('processos', '0000001-00.2026.8.21.0001')['itens'][0]
            store.save('prazos', {'processo_id': case['id'], 'dados': {'titulo': 'Prazo manual', 'vencimento': due}}, admin)
            sc = export(1, 4)
            del sc['execucao']['fonte_coleta']
            sc['execucao']['tribunal'] = 'TJSC'
            sc['paginas_da_lista'][0]['tabelas'][0]['linhas'][1][0] = '5000001-00.2026.8.24.0001'
            store.import_corpus(sc, admin)
            self.assertEqual(report()['contagens']['fatais_hoje'], 10)
            self.assertTrue(store.import_corpus(old, admin)['desatualizado'])
            partial = copy.deepcopy(current)
            partial['paginas_da_lista'][0]['tabelas'][0]['linhas'].pop()
            with self.assertRaises(juridico.AppError):
                store.import_corpus(partial, admin)
            self.assertEqual(report()['contagens']['fatais_hoje'], 10)
            fresh = export(8, 1)
            self.assertTrue(store.import_corpus(fresh, admin)['repetido'])
            self.assertEqual(report()['tjrs_lista_atual']['capturado'], fresh['execucao']['fim'])
            future = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))) + dt.timedelta(minutes=21)
            with patch('juridico.now', return_value=future.isoformat()):
                self.assertTrue(report()['tjrs_lista_atual']['atrasada'])
            store.import_corpus(export(0, 0), admin)
            self.assertEqual(report()['contagens']['fatais_hoje'], 2)
