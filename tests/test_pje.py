import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conectacoletor import pje

A = '5000001-00.2026.8.19.0001'
B = '5000002-00.2026.8.19.0001'
C = '5000003-00.2026.8.19.0001'
D = '5000004-00.2026.8.19.0001'
END = dt.date(2026, 11, 25)


def snapshot(rows, headers=None):
    return {'url': 'https://tjrj.pje.jus.br/1g/painel.seam?cid=PRIVATE', 'titulo': 'Painel do advogado',
            'texto': '\n'.join(' '.join(r) for r in rows),
            'tabelas': [{'titulo': 'Expedientes', 'linhas': [headers or ['Processo', 'Vencimento'], *rows]}]}


class PjeTests(unittest.TestCase):
    def test_explicit_cutoff_keeps_today_overdue_undated_and_removes_future(self):
        extra=[[f'{n:07d}-00.2026.8.19.0001',''] for n in range(6000000,6000497)]
        corpus = pje.parse_snapshot(snapshot([[A, '01/11/2026'], [B, '25/11/2026'],
                                              [C, '26/11/2026'], [D, ''],*extra]), 'PJE_RJ_1G', END)
        self.assertEqual([r['processo'] for r in corpus['processos']], [A, B, D,*[r[0] for r in extra]])
        self.assertEqual(corpus['coleta']['adiados'], 1)
        self.assertEqual(corpus['coleta']['estado'], 'parcial')
        self.assertEqual(corpus['coleta']['descobertos'], 501)
        self.assertTrue(all(r['detalhes'] is None for r in corpus['processos']))
        # Receiver also scans source table rows. Deferred cases cannot leak
        # into import through that second path.
        self.assertNotIn(C, str(corpus['paginas_da_lista'][0]['tabelas']))
        self.assertNotIn('PRIVATE', corpus['paginas_da_lista'][0]['url'])
    def test_small_inventory_keeps_future_deadlines(self):
        result=pje.parse_snapshot(snapshot([[A,'31/12/2099']]),'PJE_RJ_1G',END)
        self.assertEqual([r['processo'] for r in result['processos']],[A])
        self.assertEqual(result['coleta']['adiados'],0)

    def test_notification_date_and_generic_prazo_never_become_fatal(self):
        for header in ('Data de expedição', 'Prazo', 'Prazo para ciência', 'Data de distribuição'):
            with self.subTest(header=header):
                corpus = pje.parse_snapshot(snapshot([[A, '30/12/2026']], ['Processo', header]), 'PJE_RJ_1G', END)
                self.assertEqual(len(corpus['processos']), 1)
                self.assertEqual(corpus['processos'][0]['datas_limite_explicitas'], [])
                self.assertEqual(corpus['coleta']['adiados'], 0)

    def test_same_case_many_rows_keeps_any_current_deadline_or_unknown(self):
        for second in ('', '01/11/2026'):
            corpus = pje.parse_snapshot(snapshot([[A, '30/12/2026'], [A, second]]), 'PJE_RJ_1G', END)
            self.assertEqual(len(corpus['processos']), 1)
            self.assertEqual(len(corpus['processos'][0]['fonte_lista_pje']), 2)

    def test_multiple_dates_invalid_calendar_and_duration_are_unknown(self):
        for value in ('30/02/2026', '5 dias', '01/12/2026 até 02/12/2026'):
            corpus = pje.parse_snapshot(snapshot([[A, value]]), 'PJE_RJ_1G', END)
            self.assertEqual(len(corpus['processos']), 1)
            self.assertEqual(corpus['processos'][0]['datas_limite_explicitas'], [])

    def test_card_and_body_references_preserve_raw_not_complete_details(self):
        snap = {'texto': B.replace('-', '').replace('.', ''), 'cards': [
            {'texto': 'Pendente de ciência ' + A, 'categoria': 'Pendentes de ciência',
             'campos': {'Data de expedição': '01/11/2026'}}]}
        corpus = pje.parse_snapshot(snap, 'PJE_RJ_1G', END)
        self.assertEqual({r['processo'] for r in corpus['processos']}, {A, B})
        self.assertTrue(corpus['processos'][0]['comunicacao_pendente_ou_expediente'])
        self.assertFalse(corpus['processos'][0]['cobertura']['eventos_completos'])

    def test_login_never_captured_and_wrong_portal_path_rejected(self):
        snap = snapshot([[A, '01/11/2026']]); snap['autenticacao_pendente'] = True
        with self.assertRaises(RuntimeError):
            pje.parse_snapshot(snap, 'PJE_RJ_1G', END)
        page = MagicMock(url='https://pje.cloud.tjpe.jus.br/2g/Painel/advogado.seam')
        with self.assertRaises(RuntimeError):
            pje._assert_page(page, 'PJE_PE_1G')
        page = MagicMock(url='https://example.org/1g/Painel/advogado.seam')
        with self.assertRaises(RuntimeError):
            pje._assert_page(page, 'PJE_RJ_1G')
        page.locator.return_value.count.return_value = 1
        with self.assertRaises(RuntimeError):
            pje.capture_page(page)
        page.evaluate.assert_not_called()

    def test_checkpoint_every_page_before_navigation_and_partial_end(self):
        first, second = snapshot([[A, '01/11/2026']]), snapshot([[B, '02/11/2026']])
        sequence = []
        def checkpoint(corpus):
            sequence.append(('saved', len(corpus['processos'])))
        def next_page(page):
            sequence.append(('next', None))
            return 'clicked' if len([x for x in sequence if x[0] == 'next']) == 1 else 'end'
        with patch.object(pje, '_assert_page'), patch.object(pje, 'capture_page', side_effect=[first, second]), \
             patch.object(pje, 'safe_next', side_effect=next_page):
            result = pje.collect_snapshot(MagicMock(), 'PJE_RJ_1G', END, checkpoint=checkpoint)
        self.assertEqual(sequence[:4], [('saved', 1), ('next', None), ('saved', 2), ('next', None)])
        self.assertEqual(result['coleta']['paginas'], 2)
        self.assertTrue(result['coleta']['paginacao_lista_confirmada'])
        self.assertEqual(result['coleta']['estado'], 'parcial')
        self.assertFalse(result['coleta']['detalhes_completos'])

    def test_checkpoint_failure_does_not_navigate_and_repeat_does_not_duplicate(self):
        snap = snapshot([[A, '01/11/2026']])
        with patch.object(pje, '_assert_page'), patch.object(pje, 'capture_page', return_value=snap), \
             patch.object(pje, 'safe_next') as nav:
            with self.assertRaises(OSError):
                pje.collect_snapshot(MagicMock(), 'PJE_RJ_1G', END, checkpoint=lambda _: (_ for _ in ()).throw(OSError()))
            nav.assert_not_called()
        with patch.object(pje, '_assert_page'), patch.object(pje, 'capture_page', return_value=snap), \
             patch.object(pje, 'safe_next', return_value='clicked'):
            result = pje.collect_snapshot(MagicMock(), 'PJE_RJ_1G', END)
        self.assertEqual(result['coleta']['encerramento'], 'pagina_repetida')
        self.assertEqual(result['coleta']['lidos'], 1)

    def test_safe_next_waits_for_list_instead_of_spinner_and_empty_transition(self):
        page = MagicMock(); roots = MagicMock(); root = MagicMock(); button = MagicMock()
        page.locator.return_value = roots; roots.count.return_value = 1; roots.nth.return_value = root
        root.is_visible.return_value = True
        candidates = MagicMock(); root.locator.return_value = candidates
        candidates.count.return_value = 1; candidates.nth.return_value = button; button.is_visible.return_value = True
        button.get_attribute.return_value = None
        first, second = snapshot([[A, '01/11/2026']]), snapshot([[B, '02/11/2026']])
        spinner = {**first, 'texto': 'Carregando...'}
        with patch.object(pje, 'capture_page', side_effect=[first, spinner, {'tabelas': []}, second, second, second]):
            self.assertEqual(pje.safe_next(page), 'clicked')
        button.click.assert_called_once()

    def test_pje_signature_ignores_unrelated_body_changes_but_keeps_case_rows(self):
        first = snapshot([[A, '01/11/2026']])
        self.assertEqual(pje.snapshot_fingerprint(first), pje.snapshot_fingerprint({**first, 'texto': 'Carregando...'}))
        self.assertNotEqual(pje.snapshot_fingerprint(first), pje.snapshot_fingerprint(snapshot([[B, '01/11/2026']])))

    def test_malformed_snapshots_fail_before_interpretation(self):
        for value in (None, [], {'texto': {}}, {'tabelas': None},
                      {'tabelas': [{'linhas': ['not-a-row']}]},
                      {'tabelas': [{'linhas': [[{'nested': 'object'}]]}]},
                      {'cards': [{'campos': []}]}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    pje.parse_snapshot(value, 'PJE_RJ_1G', END)

    def test_generic_next_outside_paginator_is_never_clicked(self):
        page = MagicMock(); page.locator.return_value.count.return_value = 0
        self.assertEqual(pje.safe_next(page), 'unsupported')
        page.get_by_text.assert_not_called()

    def test_disabled_paginator_is_end_and_notice_action_rejected(self):
        page = MagicMock(); roots = MagicMock(); root = MagicMock(); button = MagicMock()
        page.locator.return_value = roots; roots.count.return_value = 1; roots.nth.return_value = root
        root.is_visible.return_value = True
        candidates = MagicMock(); root.locator.return_value = candidates
        candidates.count.return_value = 1; candidates.nth.return_value = button; button.is_visible.return_value = True
        button.get_attribute.side_effect = lambda name: 'true' if name == 'aria-disabled' else None
        self.assertEqual(pje.safe_next(page), 'end'); button.click.assert_not_called()
        button.get_attribute.side_effect = lambda name: 'Tomar ciência' if name == 'title' else None
        self.assertEqual(pje.safe_next(page), 'unsupported'); button.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
