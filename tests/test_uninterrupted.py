import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.runtime import detail_scope,Runtime
from conectacoletor.storage import Vault
import eproc


class UninterruptedTests(unittest.TestCase):
    def collector(self):
        c=eproc.Collector();c.options={'manter_navegador':True,'limite_minutos':50}
        c.current={'lidos':10};c.deadline=100;c.log=MagicMock();return c

    def test_elapsed_budget_with_progress_extends_same_session_without_waiting_for_ok(self):
        c=self.collector();c.wait_user=MagicMock()
        with patch('time.monotonic',return_value=200):c.check()
        self.assertEqual(c.deadline,3200);self.assertEqual(c.budget_last_read,10)
        c.wait_user.assert_not_called();c.log.assert_called_once()
        with patch('time.monotonic',return_value=201):c.check()
        c.log.assert_called_once()

    def test_no_progress_still_ends_interval_instead_of_extending_forever(self):
        c=self.collector();c.budget_last_read=10
        with patch('time.monotonic',return_value=200):
            with self.assertRaises(eproc.CollectionBudget):c.check()

    def test_pause_and_http_refusal_override_automatic_continuation(self):
        c=self.collector();c.cancelled.set()
        with patch('time.monotonic',return_value=200):
            with self.assertRaises(InterruptedError):c.check()
        c.cancelled.clear();c.block_status=403
        with self.assertRaisesRegex(RuntimeError,'HTTP_403'):c.check()
        c.log.assert_not_called()

    def test_motor_default_budget_remains_available_without_independent_option(self):
        c=self.collector();c.options.pop('manter_navegador')
        with patch('time.monotonic',return_value=200):
            with self.assertRaises(eproc.CollectionBudget):c.check()

    def test_filter_breakdown_matches_selected_without_changing_20_day_policy(self):
        numbers=[f'{5000000+i:07d}-00.2026.8.21.0001' for i in range(5)]
        pages=[{'tabelas':[{'linhas':[['Processo','Evento e Prazo','Final Prazo'],
            *[[n,'Intimação',end] for n,end in zip(numbers,['01/11/2026','20/11/2026','','31/12/2026','data inválida'])]]}]}]
        reasons={}
        selected,deferred,end=detail_scope(numbers,pages,{'total_processos':1808,'dias':20},dt.date(2026,11,7),reasons)
        self.assertEqual(set(selected),{numbers[i] for i in (0,1,2,4)})
        self.assertEqual(deferred,1);self.assertEqual(end,'2026-11-27')
        self.assertEqual((reasons['vencidos'],reasons['ate_limite'],reasons['sem_data_ou_data_invalida'],reasons['apos_limite']),(1,1,2,1))

    def test_valid_panel_can_continue_visible_collection_without_manual_confirmation(self):
        c=self.collector();c.options.update(tribunal='TJRS',invisivel=False)
        c.deadline=None;c.login_steps={};c.check=MagicMock();c.log=MagicMock()
        c.login_confirmed=MagicMock(return_value=True);c.wait_user=MagicMock()
        page=MagicMock();context=MagicMock(pages=[page])
        with patch('eproc_login.step'):c.open_login(context)
        c.wait_user.assert_not_called()

    def test_profile_selection_route_is_not_certified_as_authenticated_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp,Vault(Path(tmp)/'vault',lambda value,decrypt=False:value))
            c=runtime.collector({});c.options={'tribunal':'TJRS'}
            c.surfaces=MagicMock(return_value=[MagicMock(url='https://eproc1g.tjrs.jus.br/eproc/externo_controlador.php?acao=entrar_sso')])
            with patch('conectacoletor.access.confirmed',return_value=True):
                self.assertFalse(c.login_confirmed(MagicMock()))
