"""Paginação com o formato RS observado, usando somente dados sintéticos."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conectacoletor import runtime
import eproc
import eproc_eventos as events
import eproc_relatorios as reports
from eproc_paginacao import ListCoverage, signature, page_info, wait_table

HEADER = reports.HEADERS['pendentes_citacao_intimacao']


def listing(first, last, total=1570, repeat_case=False):
    rows = [['', f'{5000000+(0 if repeat_case else n):07d}-00.2026.8.21.0001',
             'Classe', 'Assunto', 'Intimação', '06/11/2026', '', '']
            for n in range(first, last+1)]
    return {'texto': '', 'links': [], 'tabelas': [{
        'titulo': f'Lista de Citações e Intimações Pendentes ({total:,} registros - {first} a {last}):'.replace(',', '.'),
        'linhas': [HEADER, *rows]}]}


def state(numbers, loaded=0, total=1):
    return {'tabela': True, 'eventos': list(numbers), 'carregadas': loaded,
            'total': total, 'funcao': True, 'eventos_ocultos': []}


class PaginationTests(unittest.TestCase):
    def test_rs_1570_records_requires_six_pages_and_preserves_repeated_cases(self):
        tracker = ListCoverage(1570)
        for first in range(1, 1571, 300):
            snap = listing(first, min(first+299, 1570), repeat_case=True)
            rows, tables = reports.open_page(snap)
            self.assertTrue(tracker.accept(rows, tables))
            self.assertEqual(tracker.complete, first == 1501)
        self.assertEqual((tracker.pages, tracker.rows), (6, 1570))
        self.assertEqual(tracker.export()['intervalos'][-1], [1501, 1570])

    def test_skipped_overlapping_and_short_pages_are_rejected(self):
        for first, last, drop in [(601, 900, False), (300, 599, False), (301, 600, True)]:
            with self.subTest(first=first, drop=drop):
                tracker = ListCoverage()
                tracker.accept(*reports.open_page(listing(1, 300)))
                snap = listing(first, last)
                if drop:
                    snap['tabelas'][0]['linhas'].pop()
                self.assertFalse(tracker.accept(*reports.open_page(snap)))
                self.assertFalse(tracker.complete)
                self.assertEqual(tracker.rows, 300)

    def test_repeated_page_and_changed_total_are_not_complete(self):
        for snap, reason in [(listing(1, 300), 'pagina_repetida'),
                             (listing(301, 600, 1600), 'total_alterado_durante_coleta')]:
            tracker = ListCoverage()
            tracker.accept(*reports.open_page(listing(1, 300)))
            self.assertFalse(tracker.accept(*reports.open_page(snap)))
            self.assertEqual(tracker.reason, reason)

    def test_caption_total_may_replace_stale_panel_only_before_first_page(self):
        tracker = ListCoverage(70)
        self.assertTrue(tracker.accept(*reports.open_page(listing(1, 68, 68))))
        self.assertTrue(tracker.complete)
        self.assertEqual(tracker.expected, 68)

    def test_unknown_empty_layout_is_not_certified_even_when_panel_says_zero(self):
        tracker = ListCoverage(0)
        self.assertFalse(tracker.accept([], []))
        self.assertFalse(tracker.complete)
        table = {'titulo': 'Lista (0 registros)', 'linhas': [HEADER]}
        self.assertTrue(tracker.accept([], [table]))
        self.assertTrue(tracker.complete)

    def test_legacy_list_without_ranges_needs_exact_total_and_unique_pages(self):
        tracker = ListCoverage()
        snap = listing(1, 7, 7)
        snap['tabelas'][0]['titulo'] = 'Lista (7 registros)'
        self.assertTrue(tracker.accept(*reports.open_page(snap)))
        self.assertTrue(tracker.complete)
        self.assertFalse(tracker.export()['intervalos_conferidos'])

    def test_missing_range_after_first_page_stays_pending(self):
        tracker = ListCoverage()
        tracker.accept(*reports.open_page(listing(1, 300)))
        snap = listing(301, 600)
        snap['tabelas'][0]['titulo'] = 'Lista (1.570 registros)'
        self.assertFalse(tracker.accept(*reports.open_page(snap)))
        self.assertEqual(tracker.reason, 'intervalo_da_pagina_ausente')

    def test_wait_ignores_body_spinner_and_requires_stable_table_rows(self):
        before, after = listing(1, 300), listing(301, 600)
        spinner = {**before, 'texto': 'Carregando...'}
        empty = {'tabelas': []}
        old_rows, old_tables = reports.open_page(before)
        old = (signature(old_rows), tuple(sorted(page_info(old_tables)[1])))
        page = MagicMock()
        page.evaluate.side_effect = [spinner, empty, after, after, after]
        self.assertEqual(wait_table(MagicMock(), page, eproc.SNAPSHOT, reports.open_page, old), after)
        self.assertEqual(page.evaluate.call_count, 5)

    def test_table_that_never_changes_stops_instead_of_repeating(self):
        snap = listing(1, 300)
        rows, tables = reports.open_page(snap)
        page = MagicMock(); page.evaluate.return_value = snap
        self.assertIsNone(wait_table(MagicMock(), page, '', reports.open_page,
                                    (signature(rows), tuple(sorted(page_info(tables)[1])))))

    def test_pending_report_reads_all_six_pages_and_saves_before_navigation(self):
        snaps = [listing(n, min(n+299, 1570)) for n in range(1, 1571, 300)]
        page = MagicMock(); index = [0]; order = []
        url = 'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=citacao_intimacao_pendente_listar'
        page.url = url
        page.locator.return_value.count.return_value = 0
        page.evaluate.side_effect = lambda _: snaps[index[0]]
        button = MagicMock()
        def click(**kw):
            order.append('next'); index[0] += 1
        button.click.side_effect = click
        collector = MagicMock(); collector.options = {'tribunal': 'TJRS', 'url_pendentes_citacao_intimacao': url}
        collector.save_checkpoint.side_effect = lambda *a: order.append('saved')
        context = MagicMock(); context.new_page.return_value = page
        pages = []; found = {}
        with patch.object(reports, 'next_enabled', return_value=[button]):
            result, numbers = reports.collect(collector, context, 'citacao_intimacao_pendente_listar', '', pages, found, lambda snap: {})
        self.assertTrue(result['completo'])
        self.assertEqual((result['paginas'], result['registros']), (6, 1570))
        self.assertEqual(len(numbers), 1570)
        self.assertEqual(order, ['saved', 'next']*5+['saved'])
        page.close.assert_called_once()

    def test_event_loader_appends_remaining_rs_events_before_finishing(self):
        first = state(range(19, 119)); final = state(range(1, 119), 1)
        page = MagicMock(); invoked = [False]; calls = []
        def evaluate(js):
            if js != events.STATE:
                invoked[0] = True; calls.append('load'); return
            return final if invoked[0] else first
        page.evaluate.side_effect = evaluate
        result = events.expand(MagicMock(), page)
        self.assertTrue(result['completo'])
        self.assertEqual(result['eventos_visiveis'], 118)
        self.assertEqual(calls, ['load'])

    def test_advanced_event_counter_without_new_rows_remains_partial(self):
        first = state(range(19, 119)); bad = state(range(19, 119), 1)
        page = MagicMock(); invoked = [False]
        def evaluate(js):
            if js != events.STATE:
                invoked[0] = True; return
            return bad if invoked[0] else first
        page.evaluate.side_effect = evaluate
        result = events.expand(MagicMock(), page)
        self.assertFalse(result['completo'])
        self.assertTrue(result['falha_paginacao'])
        # Reconciliation cannot turn this failure into confirmed pagination.
        snap = {'tabelas': [{'linhas': [['Evento', 'Data/Hora', 'Descrição', 'Usuário', 'Documentos'],
                                     *[[str(n), '', 'Petição', '', ''] for n in range(19, 119)]]}]}
        self.assertFalse(events.reconcile(result, snap)['completo'])

    def test_replacing_instead_of_appending_event_rows_is_not_complete(self):
        first = state(range(19, 119)); bad = state(range(1, 19), 1)
        page = MagicMock(); invoked = [False]
        def evaluate(js):
            if js != events.STATE:
                invoked[0] = True; return
            return bad if invoked[0] else first
        page.evaluate.side_effect = evaluate
        self.assertFalse(events.expand(MagicMock(), page)['completo'])

    def test_stalled_loader_does_not_loop_forever_or_erase_pause(self):
        page = MagicMock(); page.evaluate.return_value = state(range(19, 119))
        result = events.expand(MagicMock(), page)
        self.assertEqual(result['motivo'], 'sem_avanco_no_carregamento')
        collector = MagicMock(); collector.check.side_effect = InterruptedError('pausado')
        with self.assertRaises(InterruptedError):
            events.expand(collector, page)
