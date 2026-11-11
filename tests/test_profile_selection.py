import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conectacoletor import runtime
from conectacoletor.cli import profile_tick
from conectacoletor.console import browser_input
import eproc_login as login
import eproc


def group(items):
    value=MagicMock();value.count.return_value=len(items);value.nth.side_effect=lambda i:items[i]
    return value


def frame(labels,host='eproc1g.tjrs.jus.br'):
    current=MagicMock(url='https://'+host+'/eproc/externo_controlador.php?acao=entrar_sso#')
    current.is_detached.return_value=False
    buttons=[]
    for label in labels:
        button=MagicMock();button.is_visible.return_value=True
        button.get_attribute.return_value=label
        area=MagicMock();area.count.return_value=1;area.is_visible.return_value=True
        button.locator.return_value=area;buttons.append(button)
    current.locator.side_effect=lambda selector:group(buttons) if selector=='button[data-descricao]' else group([])
    current.get_by_text.return_value=group([])
    return current,buttons


class ProfileSelectionTests(unittest.TestCase):
    def test_account_prefix_from_received_layout_selects_label_not_default_action(self):
        current,buttons=frame(['RS000001 / ADVOGADO-TITULAR'])
        state={};log=MagicMock();manual=MagicMock()
        self.assertTrue(login.select_profile([current],'TJRS',state,log,manual))
        buttons[0].locator.assert_called_once_with('xpath=./div[1]')
        buttons[0].locator.return_value.click.assert_called_once_with(timeout=15000)
        buttons[0].click.assert_not_called()
        manual.assert_not_called()
        self.assertNotIn('RS000001',str(log.call_args_list))
        self.assertFalse(login.select_profile([current],'TJRS',state,log,manual))

    def test_two_accounts_or_two_frames_require_manual_choice_without_clicks(self):
        first,buttons=frame(['RS000001 / ADVOGADO-TITULAR','RS000002 / ADVOGADO-TITULAR'])
        manual=MagicMock();state={}
        self.assertFalse(login.select_profile([first],'TJRS',state,MagicMock(),manual))
        login.select_profile([first],'TJRS',state,MagicMock(),manual)
        manual.assert_called_once()
        for button in buttons:button.locator.return_value.click.assert_not_called()
        other,more=frame(['RS000003 / ADVOGADO-TITULAR'])
        self.assertFalse(login.select_profile([first,other],'TJRS',{},MagicMock(),MagicMock()))
        more[0].locator.return_value.click.assert_not_called()

    def test_external_host_wrong_court_and_other_roles_are_not_selected(self):
        for labels,host in [(['RS000001 / ADVOGADO-TITULAR'],'outside.invalid'),
                            (['RS000001 / ADVOGADO-TITULAR'],'eproc1g.tjsc.jus.br'),
                            (['RS000001 / ADVOGADO-SUBSTABELECIDO'],'eproc1g.tjrs.jus.br')]:
            current,buttons=frame(labels,host)
            self.assertFalse(login.select_profile([current],'TJRS',{},MagicMock(),MagicMock()))
            for button in buttons:button.locator.return_value.click.assert_not_called()

    def test_selection_error_has_no_automatic_repeat_and_no_false_confirmation(self):
        current,buttons=frame(['RS000001 / ADVOGADO-TITULAR']);state={};manual=MagicMock();log=MagicMock()
        buttons[0].locator.return_value.click.side_effect=RuntimeError('PRIVATE_AUTH_URL')
        self.assertFalse(login.select_profile([current],'TJRS',state,log,manual))
        self.assertFalse(login.select_profile([current],'TJRS',state,log,manual))
        buttons[0].locator.return_value.click.assert_called_once()
        log.assert_not_called();self.assertNotIn('PRIVATE_AUTH_URL',str(manual.call_args_list))

    def test_access_command_tick_uses_same_profile_selection(self):
        current,buttons=frame(['RS000001 / ADVOGADO-TITULAR'])
        page=MagicMock(frames=[current]);page.is_closed.return_value=False
        with patch('builtins.print'):
            profile_tick(MagicMock(pages=[page]),'TJRS',{})
        buttons[0].locator.return_value.click.assert_called_once()
        with patch.object(login,'select_profile') as select:
            profile_tick(MagicMock(),'PJE_PE_1G',{})
            select.assert_not_called()

    def test_waiting_for_enter_runs_profile_callback_on_browser_owner_thread(self):
        owner=threading.get_ident();ticked=threading.Event()
        page=MagicMock();page.is_closed.return_value=False
        def callback():
            self.assertEqual(threading.get_ident(),owner);ticked.set()
        def reader(_):
            self.assertNotEqual(threading.get_ident(),owner)
            self.assertTrue(ticked.wait(2));return ''
        self.assertEqual(browser_input(MagicMock(pages=[page]),'',reader,tick=callback),'')

    def test_visible_collection_wait_also_pumps_browser_and_selects_profile(self):
        current,buttons=frame(['RS000001 / ADVOGADO-TITULAR'])
        page=MagicMock(frames=[current]);page.is_closed.return_value=False
        context=MagicMock(pages=[page])
        with tempfile.TemporaryDirectory() as tmp:
            collector=eproc.Collector(Path(tmp));collector.options={'tribunal':'TJRS','invisivel':False}
            collector.update=MagicMock();collector.log=MagicMock();collector.check=MagicMock()
            state={}
            def tick():
                login.select_profile([current],'TJRS',state,collector.log,collector.log)
                collector.resume.set()
            collector.wait_user('Login',context=context,on_wait=tick)
            page.wait_for_timeout.assert_called_once_with(100)
            buttons[0].locator.return_value.click.assert_called_once()
