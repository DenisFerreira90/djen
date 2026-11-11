import threading
import unittest
import sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.console import browser_input
from conectacoletor import access


class AccessWaitTests(unittest.TestCase):
    def test_terminal_wait_keeps_browser_events_on_owner_thread(self):
        owner = threading.get_ident()
        pumped = threading.Event()
        page = MagicMock()
        page.is_closed.return_value = False
        context = MagicMock(pages=[page])

        def pump(_):
            self.assertEqual(threading.get_ident(), owner)
            pumped.set()

        def reader(_):
            self.assertNotEqual(threading.get_ident(), owner)
            if not pumped.wait(2):
                raise AssertionError('Browser events were not processed')
            return 'OK'

        page.wait_for_timeout.side_effect = pump
        self.assertEqual(browser_input(context, '', reader), 'OK')
        self.assertTrue(pumped.is_set())

    def test_closed_browser_has_clear_error(self):
        context = MagicMock(pages=[])
        stopped = threading.Event()
        try:
            with self.assertRaisesRegex(RuntimeError, 'janela foi fechada'):
                browser_input(context, '', lambda _: stopped.wait(2))
        finally:
            stopped.set()

    def frame(self, url, visible=True, login=False):
        frame = MagicMock(url=url)
        frame.is_detached.return_value = False
        empty = MagicMock()
        empty.count.return_value = 0
        rows = MagicMock()
        rows.count.return_value = 1
        rows.nth.return_value.is_visible.return_value = visible

        def locator(selector):
            if login and selector.startswith('input[type='):
                field = MagicMock()
                field.count.return_value = 1
                return field
            if selector == 'tr':
                node = MagicMock()
                node.filter.return_value = rows
                return node
            return empty

        frame.locator.side_effect = locator
        page = MagicMock(frames=[frame])
        page.is_closed.return_value = False
        return MagicMock(pages=[page])

    def test_current_panel_with_onclick_links_is_recognized(self):
        context = self.frame('https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao=painel_adv_listar')
        self.assertTrue(access.confirmed(context, 'TJSC'))

    def test_panel_url_alone_or_wrong_host_cannot_confirm(self):
        for url, visible, login in [
            ('https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao=painel_adv_listar', False, False),
            ('https://example.com/?acao=painel_adv_listar', True, False),
            ('http://eproc1g.tjsc.jus.br/?acao=painel_adv_listar', True, False),
            ('https://eproc1g.tjsc.jus.br/?acao=login', True, False),
            ('https://eproc1g.tjsc.jus.br/?acao=painel_adv_listar', True, True),
        ]:
            with self.subTest(url=url, visible=visible, login=login):
                self.assertFalse(access.confirmed(self.frame(url, visible, login), 'TJSC'))
