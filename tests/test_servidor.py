import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import servidor


class FakeResponse:
    def __init__(self, obj):
        self.body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return None
    def read(self, size):
        return self.body[:size]


class TestConsulta(unittest.TestCase):
    def test_validate_optional_oab_and_accent(self):
        params, page = servidor.validate_query('texto=distribu%C3%ADdo+para&siglaTribunal=tjrs&pagina=2')
        self.assertEqual(params['texto'], 'distribuído para')
        self.assertEqual(params['siglaTribunal'], 'TJRS')
        self.assertEqual(params['itensPorPagina'], '100')
        self.assertEqual(page, 2)
        self.assertNotIn('numeroOab', params)

    def test_validate_full_process_and_dates(self):
        params, page = servidor.validate_query('numeroProcesso=5001234-12.2025.8.21.0001&dataDisponibilizacaoInicio=2026-10-01&dataDisponibilizacaoFim=2026-10-25')
        self.assertEqual(params['numeroProcesso'], '50012341220258210001')
        self.assertEqual(page, 1)

    def test_invalid_filters(self):
        for query in ('', 'ufOab=RS&texto=teste', 'texto=abc&pagina=0',
                      'texto=abc&dataDisponibilizacaoInicio=2026-12-02',
                      'texto=abc&siglaTribunal=TJRS&siglaTribunal=TJSP',
                      'texto=abc&dataDisponibilizacaoInicio=2026-13-02&dataDisponibilizacaoFim=2026-13-03'):
            with self.subTest(query=query), self.assertRaises(servidor.ValidationError):
                servidor.validate_query(query)

    def test_normalization(self):
        raw = {
            'id': 10, 'numeroProcesso': '0012345-76.2024.8.21.0001',
            'siglaTribunal': 'TJRS', 'nomeDestinatario': 'João',
            'texto': '<p>Processo <strong>distribuído</strong> para</p><p>Vara Cível &amp; Anexos</p>',
        }
        item = servidor.normalize_item(raw)
        self.assertEqual(item['tribunal'], 'TJRS')
        self.assertIn('distribuído para', item['texto'])
        self.assertIn('Vara Cível & Anexos', item['texto'])
        self.assertEqual(item['partes'], ['João'])

    def test_query_cnj_api(self):
        sample = {'count': 450, 'items': [
            {'id': 1, 'texto': '<div>Distribuído para análise</div>', 'siglaTribunal': 'TJSC'},
            {'id': 2, 'texto': 'Publicação de teste', 'siglaTribunal': 'TJRS'},
        ]}
        with patch.object(servidor.urllib.request, 'urlopen', return_value=FakeResponse(sample)) as mocked:
            params, page = servidor.validate_query('texto=distribuido+para&pagina=1')
            result = servidor.query_cnj(params, page)
        self.assertEqual(result['total'], 450)
        self.assertEqual(len(result['itens']), 2)
        self.assertEqual(result['itens'][0]['tribunal'], 'TJSC')
        self.assertIn('itensPorPagina=100', mocked.call_args.args[0].full_url)

    def test_http_static_and_api(self):
        server = servidor.ThreadingHTTPServer(('127.0.0.1', 0), servidor.Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/') as r:
                self.assertEqual(r.status, 200)
                self.assertIn('Consulta DJEN', r.read().decode('utf-8'))
            with urlopen(base + '/js/app.js') as r:
                self.assertIn('/api/buscar?', r.read().decode('utf-8'))
            with urlopen(base + '/api/health') as r:
                self.assertTrue(json.load(r)['ok'])
            with patch.object(servidor, 'query_cnj', return_value={
                'ok': True, 'pagina': 1, 'itens': [], 'total': 0, 'tamanho_lote': 100
            }):
                with urlopen(base + '/api/buscar?texto=distribuido%20para') as r:
                    self.assertEqual(r.status, 200)
                    self.assertEqual(json.load(r)['total'], 0)
            try:
                urlopen(base + '/api/buscar?ufOab=RS')
                self.fail('Should get 400')
            except servidor.urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 400)
            try:
                urlopen(base + '/servidor.py')
                self.fail('Should get 404')
            except servidor.urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
