import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import eproc
import servidor
import juridico

NUMBER = '5001234-12.2025.8.21.0001'

class TestExports(unittest.TestCase):
    def test_only_process_read_links(self):
        links = {'links': [
            {'texto': NUMBER, 'url': 'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=processo_selecionar&hash=secret'},
            {'texto': '5001235-12.2025.8.21.0001', 'url': 'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=intimacao_abrir'},
            {'texto': '5001236-12.2025.8.21.0001', 'url': 'https://evil.test/?acao=processo_selecionar'},
        ]}
        self.assertEqual(list(eproc.process_links(links)), [NUMBER])

    def test_export_preserves_multiple_deadlines_and_source_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            status = {'id': '20261026-100000-abcdef12', 'inicio': eproc.now(), 'estado': 'parcial'}
            table = {'titulo': 'Prazos', 'linhas': [['Início', 'Fim'], ['26/10/2026', '27/10/2026'], ['26/10/2026', '30/10/2026']]}
            records = [{'processo': NUMBER, 'situacao': 'pagina_lida_requer_conferencia', 'detalhes': {'texto': 'Autor: A; Réu: B', 'tabelas': [table]}}]
            eproc.write_exports(folder, records, [], status)
            with zipfile.ZipFile(folder / 'exportacao.zip') as z:
                data = json.loads(z.read('processos.json'))
                self.assertEqual(data['processos'][0]['detalhes']['tabelas'][0], table)
                rows = list(csv.reader(io.StringIO(z.read('processos.csv').decode('utf-8-sig')), delimiter=';'))
                self.assertEqual(len(rows), 4)
                self.assertIn('27/10/2026', rows[2][5])
                self.assertIn('30/10/2026', rows[3][5])
            self.assertTrue(eproc.safe_cell(' =HYPERLINK("x")').startswith("'"))

    def test_log_persistence_and_distinct_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = eproc.Collector(directory)
            with patch.object(collector, 'run', return_value=None):
                first = collector.start()['atual']['id']
                collector.thread.join()
                collector.log('Sem credenciais no log.')
                second = collector.start()['atual']['id']
                collector.thread.join()
            self.assertNotEqual(first, second)
            self.assertEqual(len(collector.status()['historico']), 2)
            self.assertIn('Sem credenciais', (Path(directory) / first / 'log.jsonl').read_text())

    def test_login_navigation_error_still_waits_for_user(self):
        collector = eproc.Collector()
        page = MagicMock()
        page.goto.side_effect = RuntimeError('secret-url-and-password')
        context = MagicMock(pages=[page])
        with patch.object(collector, 'log') as log, patch.object(collector, 'wait_user') as wait, patch.dict(eproc.os.environ, {'EPROC_USUARIO': '', 'EPROC_SENHA': ''}):
            collector.open_login(context)
            wait.assert_called_once()
            context.close.assert_not_called()
            self.assertNotIn('secret-url-and-password', str(log.call_args_list))

    def test_early_continue_returns_to_wait_instead_of_closing(self):
        collector = eproc.Collector()
        page = MagicMock()
        page.is_closed.return_value = False
        context = MagicMock(pages=[page])
        listing = object()
        attempts = [None, RuntimeError('frame detached'), listing]
        def locate(_):
            item = attempts.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        with patch.object(collector, 'find_list', side_effect=locate), patch.object(collector, 'surfaces', return_value=[]), patch.object(collector, 'log'), patch.object(collector, 'wait_user') as wait:
            self.assertIs(collector.await_listing(context), listing)
            wait.assert_called_once()
            context.close.assert_not_called()

    def test_api_rejects_foreign_origin_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(eproc, 'collector', eproc.Collector(directory)), patch.object(juridico, 'store', juridico.Store(Path(directory)/'db.sqlite3')):
            server = servidor.ThreadingHTTPServer(('127.0.0.1', 0), servidor.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            try:
                with self.assertRaises(HTTPError) as denied:
                    urlopen(base + '/api/eproc/status')
                self.assertEqual(denied.exception.code,401)
                juridico.store.create_user({'nome':'Admin','login':'admin','senha':'senha-segura-123'},setup=True)
                session,key=juridico.store.login('admin','senha-segura-123')
                auth={'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf']}
                self.assertTrue(json.load(urlopen(Request(base + '/api/eproc/status',headers=auth)))['ok'])
                for url, headers, body, expected in [
                    ('/api/eproc/iniciar', {'Content-Type': 'application/json', 'Origin': 'https://evil.test'}, b'{}', 403),
                    ('/api/eproc/status', {'Host': 'evil.test'}, None, 403),
                    ('/api/eproc/exportar?id=../../servidor.py', {}, None, 400),
                    ('/api/eproc/continuar', {'Content-Type': 'application/json'}, b'{}', 400),
                ]:
                    with self.subTest(url=url), self.assertRaises(HTTPError) as caught:
                        urlopen(Request(base+url, data=body, headers={**auth,**headers}))
                    self.assertEqual(caught.exception.code, expected)
            finally:
                server.shutdown(); server.server_close(); thread.join()

if __name__ == '__main__': unittest.main()
