import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conectacoletor.runtime import Runtime, detail_scope, category_issues
from conectacoletor.storage import Vault, AgentDB
import eproc
import eproc_relatorios as reports

KIND = 'movimentacoes_preparadas'
ACTION = 'movimentacao_preparada_listar'
HEADER = ['', 'Processo', 'Evento', 'Data da Criação', 'Preparado para',
          'Preparado por', 'Data Final do Prazo', 'Resultado', 'Ações']
NUMBER = '5000001-00.2026.8.24.0001'


def snapshot(total=22, repeat=False, end='20/11/2026'):
    rows = [['', NUMBER if repeat else f'{5000001+i:07d}-00.2026.8.24.0001',
             'Petição preparada', '06/11/2026 10:30:00', 'Destinatário de teste',
             'Preparador de teste', end if i < total-3 else '', 'Resultado de teste', 'Consultar']
            for i in range(total)]
    return {'texto': '', 'links': [], 'tabelas': [{
        'titulo': f'Lista de Movimentações preparadas ({total} registros):',
        'linhas': [HEADER, *rows]}]}


def page(**kwargs):
    return {**snapshot(**kwargs), 'origem_relatorio': KIND}


class PreparedCategoryTests(unittest.TestCase):
    def test_observed_sc_22_rows_and_distinct_fields_are_preserved(self):
        snap = page()
        rows, total = reports.report_rows(snap, KIND)
        self.assertEqual((len(rows), total), (22, 22))
        entries = reports.prepared_entries([snap])
        self.assertEqual(len(entries), 22)
        self.assertEqual(sum(bool(e['data_final_prazo_origem']) for e in entries), 19)
        self.assertEqual(entries[0]['data_criacao'], '06/11/2026 10:30:00')
        self.assertEqual(entries[0]['preparado_para'], 'Destinatário de teste')
        self.assertEqual(entries[0]['preparado_por'], 'Preparador de teste')
        self.assertEqual(entries[0]['resultado'], 'Resultado de teste')

    def test_repeated_preparations_are_retained_in_one_process(self):
        snap = page(repeat=True)
        pages = eproc.case_pages([snap])
        self.assertEqual(set(pages), {NUMBER})
        self.assertEqual(len(reports.prepared_entries(pages[NUMBER])), 22)
        self.assertEqual(reports.open_listing_rows([snap]), [])

    def test_reading_uses_current_panel_link_and_never_opens_prepared_edit_actions(self):
        url = 'https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao='+ACTION+'&hash=TEST_ONLY'
        edit = 'https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao=preparar_processo_futura_movimentacao_consultar&hash=TEST_ONLY'
        snap = snapshot()
        snap['links'] = [
            {'texto': NUMBER, 'url': 'https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao=processo_selecionar&hash=TEST_ONLY'},
            {'texto': 'Consultar preparação', 'url': edit}]
        browser_page = MagicMock(); browser_page.url = url
        browser_page.locator.return_value.count.return_value = 0
        browser_page.evaluate.return_value = snap
        frame = MagicMock(); frame.url = 'https://eproc1g.tjsc.jus.br/eproc/'
        frame.locator.return_value.evaluate_all.return_value = [edit, url]
        context = MagicMock(); context.new_page.return_value = browser_page
        collector = MagicMock(); collector.options = {'tribunal': 'TJSC'}
        collector.surfaces.return_value = [frame]
        pages, found = [], {}
        coverage, _ = reports.collect(collector, context, ACTION, eproc.SNAPSHOT, pages, found,
                                       lambda value: eproc.process_links(value, 'TJSC'))
        self.assertTrue(coverage['completo'])
        self.assertEqual((coverage['registros'], coverage['processos_distintos']), (22, 22))
        browser_page.goto.assert_called_once_with(url, wait_until='domcontentloaded', timeout=60000)
        browser_page.locator.return_value.click.assert_not_called()
        self.assertNotIn(edit, found.values())
        self.assertNotIn('TEST_ONLY', json.dumps(pages))
        browser_page.close.assert_called_once()

    def test_unknown_preparation_columns_are_not_certified(self):
        snap = snapshot(); snap['tabelas'][0]['linhas'][0][6] = 'Data desconhecida'
        self.assertEqual(reports.report_rows(snap, KIND), ([], None))

    def test_prepared_data_is_not_a_filed_event_or_fatal_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = Runtime(folder, Vault(Path(folder)/'vault', lambda value, decrypt=False: value))
            payload = {'execucao': {'id': 'prepared-test'}, 'processos': [], 'paginas_da_lista': [page()]}
            summary = runtime.local.import_corpus(payload, runtime.actor)
            self.assertEqual(summary['total'], 22)
            with runtime.local.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='prazos' AND json_extract(data,'$.origem')='eproc'").fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM source_events').fetchone()[0], 0)
                values = [json.loads(r[0]) for r in db.execute('SELECT payload FROM source_complements WHERE tipo=?', (KIND,))]
                self.assertEqual(len(values), 22)
                self.assertEqual(sum(len(v['registros_preparados']) for v in values), 22)
            again = runtime.local.import_corpus(payload, runtime.actor)
            self.assertTrue(again['repetido'])

    def test_large_inventory_date_rule_includes_prepared_undated_and_near_deadlines(self):
        near = page(total=1)
        near['tabelas'][0]['linhas'][1][6] = '20/11/2026'
        options = {'total_processos': 501, 'dias': 20}
        self.assertEqual(detail_scope([NUMBER], [near], options, dt.date(2026, 11, 7))[0], [NUMBER])
        near['tabelas'][0]['linhas'][1][6] = '31/12/2026'
        self.assertEqual(detail_scope([NUMBER], [near], options, dt.date(2026, 11, 7))[0], [])
        self.assertEqual(detail_scope([NUMBER], [near], {'total_processos': 500}, dt.date(2026, 11, 7))[0], [NUMBER])
        near['tabelas'][0]['linhas'][1][6] = ''
        opened = {'tabelas': [{'linhas': [['Processo', 'Evento e Prazo', 'Final Prazo'], [NUMBER, 'Intimação', '31/12/2026']]}]}
        self.assertEqual(detail_scope([NUMBER], [opened, near], options, dt.date(2026, 11, 7))[0], [NUMBER])

    def test_rs_initial_categories_have_observed_headers_without_cnj_column(self):
        self.assertEqual(reports.ACTIONS['peticao_inicial_preparada_listar'], 'processos_pendentes_advogado')
        self.assertEqual(reports.ACTIONS['peticao_inicial_preparada_escritorio_listar'], 'processos_pendentes_sociedade')
        self.assertEqual(reports.ACTIONS[ACTION], KIND)
        for kind in reports.INITIAL_KINDS:
            self.assertEqual(reports.HEADERS[kind], ['', 'Autor', 'Réu', 'Assunto', 'Data da Criação', 'Criado por', 'Ações'])
            self.assertNotIn('Processo', reports.HEADERS[kind])

    def test_category_pending_notice_is_resolved_only_for_that_portal_and_category(self):
        with tempfile.TemporaryDirectory() as folder:
            db = AgentDB(Path(folder)/'db')
            category_issues(db, 'TJRS', [{'tipo': 'processos_pendentes_sociedade', 'completo': False, 'motivo': 'layout_nao_validado'},
                                       {'tipo': KIND, 'completo': False, 'motivo': 'relatorio_nao_localizado'}])
            category_issues(db, 'TJSC', [{'tipo': KIND, 'completo': False, 'motivo': 'pagina_nao_mudou'}])
            self.assertEqual(len(db.issues()), 3)
            category_issues(db, 'TJRS', [{'tipo': KIND, 'completo': True}])
            self.assertEqual(len(db.issues()), 2)
            self.assertEqual(sorted(r['local'] for r in db.issues()), sorted([KIND, 'processos_pendentes_sociedade']))

    def test_prepared_route_is_separate_from_editing_and_other_courts(self):
        base = 'https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao='
        self.assertTrue(reports.valid_url(base+ACTION, ACTION, 'TJSC'))
        self.assertFalse(reports.valid_url(base+'preparar_processo_futura_movimentacao_consultar', ACTION, 'TJSC'))
        self.assertFalse(reports.valid_url((base+ACTION).replace('tjsc', 'tjrs'), ACTION, 'TJSC'))
