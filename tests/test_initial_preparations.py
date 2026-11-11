import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conectacoletor.runtime import Runtime
from conectacoletor.storage import Vault
import eproc
import eproc_relatorios as reports
from eproc_paginacao import ListCoverage

KIND = 'processos_pendentes_advogado'
OTHER = 'processos_pendentes_sociedade'
ACTION = 'peticao_inicial_preparada_listar'


def snapshot(total=24):
    return {'texto': '', 'links': [], 'tabelas': [{
        'titulo': f'Lista de Petições Iniciais preparadas ({total} registros):',
        'identificadores_peticoes_linhas': [None, *[str(1001+n) for n in range(total)]],
        'linhas': [reports.INITIAL_HEADER, *[['', 'Autor de teste', 'Réu de teste',
                  'Assunto de teste', '07/11/2026 10:00:00', 'Usuário de teste', 'Carregar']
                  for _ in range(total)]]}]}


def page(kind=KIND, total=24):
    return {**snapshot(total), 'origem_relatorio': kind, 'tribunal': 'TJRS'}


class InitialPreparationTests(unittest.TestCase):
    def test_24_initial_petitions_are_read_without_fabricating_process_numbers(self):
        rows, total = reports.report_rows(snapshot(), KIND)
        self.assertEqual((len(rows), total), (24, 24))
        self.assertTrue(all('numero' not in r for r in rows))
        entries = reports.initial_entries([page()])
        self.assertEqual(len(entries), 24)
        self.assertEqual(entries[0]['autor'], 'Autor de teste')
        self.assertEqual(entries[0]['reu'], 'Réu de teste')

    def test_missing_malformed_or_ambiguous_ids_are_not_counted_as_full_page(self):
        for value in (None, '', 'invalid', '001', '1&hash=PRIVATE'):
            snap = snapshot(); snap['tabelas'][0]['identificadores_peticoes_linhas'][1] = value
            rows, _ = reports.report_rows(snap, KIND)
            tracker = ListCoverage()
            self.assertTrue(tracker.accept(rows, snap['tabelas']))
            self.assertFalse(tracker.complete)
            self.assertEqual(len(rows), 23)

    def test_initial_rows_never_enter_case_list_even_if_subject_mentions_cnj(self):
        snap = page()
        snap['tabelas'][0]['linhas'][1][3] = 'Referência a 5000001-00.2026.8.21.0001'
        self.assertEqual(reports.case_listing_pages([snap]), [])
        self.assertEqual(eproc.case_pages([snap]), {})
        self.assertEqual(reports.open_listing_rows([snap]), [])

    def test_both_lists_preserve_membership_but_have_only_24_distinct_identities(self):
        entries = reports.initial_entries([page(), page(OTHER)])
        self.assertEqual(len(entries), 48)
        self.assertEqual(len({e['id_peticao_pendente'] for e in entries}), 24)
        self.assertEqual({e['categoria'] for e in entries}, {KIND, OTHER})

    def test_initials_are_saved_locally_with_repeated_snapshot_idempotence_and_court_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Runtime(folder, Vault(Path(folder)/'vault', lambda value, decrypt=False: value))
            pages = [page(), page(OTHER)]
            self.assertEqual(reports.save_initials(runtime.local, pages, 'TJRS', 'test'), 48)
            self.assertEqual(reports.save_initials(runtime.local, pages, 'TJRS', 'another-run'), 0)
            with self.assertRaises(ValueError):reports.save_initials(runtime.local,pages,'TJSC','wrong-court')
            self.assertEqual(reports.save_initials(runtime.local, [{**page(), 'tribunal':'TJSC'}], 'TJSC', 'test-sc'), 24)
            status={r['tribunal']:r for r in runtime.db.status()['peticoes_iniciais_preparadas_locais']}
            self.assertEqual(status['TJRS']['peticoes_distintas'],24)
            self.assertEqual(status['TJRS']['categorias_observadas'],2)
            with runtime.local.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(DISTINCT peticao_id) FROM source_initial_preparations WHERE tribunal='TJRS'").fetchone()[0], 24)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='processos'").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='prazos'").fetchone()[0], 0)

    def test_collector_reads_list_without_loading_draft_or_adding_found_processes(self):
        url = 'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao='+ACTION+'&hash=TEST_ONLY'
        collector = MagicMock(); collector.options = {'tribunal': 'TJRS', 'url_'+KIND: url}
        browser_page = MagicMock(); browser_page.url = url
        browser_page.locator.return_value.count.return_value = 0
        browser_page.evaluate.return_value = snapshot()
        context = MagicMock(); context.new_page.return_value = browser_page
        pages, found = [], {}
        coverage, numbers = reports.collect(collector, context, ACTION, '', pages, found,
                                             lambda snap: {'SHOULD_NOT_ENTER': 'https://example.invalid'})
        self.assertTrue(coverage['completo'])
        self.assertEqual(coverage['registros'], 24)
        self.assertEqual(coverage['peticoes_distintas'], 24)
        self.assertEqual(coverage['processos_distintos'], 0)
        self.assertEqual(found, {})
        self.assertEqual(numbers, set())
        browser_page.locator.return_value.click.assert_not_called()
        self.assertNotIn('TEST_ONLY', json.dumps(pages))

    def test_recovery_persists_initials_without_syncing_them_as_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Runtime(folder, Vault(Path(folder)/'vault', lambda value, decrypt=False: value))
            run = 'only-initials'; dest = runtime.data/'coletas'/run; dest.mkdir(parents=True)
            (dest/'processos.json').write_text(json.dumps({'processos': [], 'paginas_da_lista': [page()]}))
            runtime.recover_run(run, 'TJRS')
            with runtime.local.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM source_initial_preparations').fetchone()[0], 24)
            self.assertEqual(runtime.db.status()['sincronizacao'].get('pendente', 0), 0)

    def test_sc_empty_form_without_table_remains_unconfirmed(self):
        self.assertEqual(reports.report_rows({'tabelas': []}, KIND), ([], None))
        tracker = ListCoverage()
        self.assertFalse(tracker.accept([], []))
        self.assertFalse(tracker.complete)
