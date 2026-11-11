import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conectacoletor import access
from conectacoletor.portals import PORTALS, trusted_url, public_catalog


class PortalTests(unittest.TestCase):
    def test_original_eproc_identifiers_remain(self):
        for portal_id in ('TJRS', 'TJSC', 'TJRJ'):
            self.assertEqual(PORTALS[portal_id]['family'], 'eproc')
        self.assertEqual(PORTALS['TJSC']['url'], 'https://eproc1g.tjsc.jus.br/eproc/')

    def test_pje_entries_have_static_official_urls_and_explicit_validation(self):
        pje = {k:v for k,v in PORTALS.items() if v['family'] == 'pje'}
        self.assertEqual(set(pje), {'PJE_RJ_1G','PJE_PE_1G','PJE_PE_2G','PJE_BA_1G','PJE_BA_2G'})
        for key, value in pje.items():
            with self.subTest(portal=key):
                parsed = urlsplit(value['url'])
                self.assertEqual(parsed.scheme, 'https')
                self.assertFalse(parsed.query or parsed.fragment)
                self.assertEqual(value['authenticated_validation'], 'pendente')
                self.assertIn('nao_validado', value['collection_status'])
                self.assertTrue(trusted_url(value['url'], key))
        self.assertEqual(len(public_catalog()), 8)

    def test_host_path_and_protocol_are_not_interchangeable(self):
        for url in (
            'https://pje.cloud.tjpe.jus.br/2g/Painel/painel_usuario/advogado.seam',
            'https://pje.cloud.tjpe.jus.br.evil.example/1g/',
            'https://evil.example/1g/',
            'http://pje.cloud.tjpe.jus.br/1g/',
            'https://pje.cloud.tjpe.jus.br:444/1g/',
            'https://user:pass@pje.cloud.tjpe.jus.br/1g/',
            'https://pje.cloud.tjpe.jus.br/1greater/',
        ):
            with self.subTest(url=url):
                self.assertFalse(trusted_url(url, 'PJE_PE_1G'))
        self.assertTrue(trusted_url('https://pje.cloud.tjpe.jus.br/1g/Painel/painel_usuario/advogado.seam', 'PJE_PE_1G'))
        self.assertFalse(trusted_url('https://sso.cloud.pje.jus.br/auth/', 'PJE_PE_1G'))
        self.assertTrue(trusted_url('https://sso.cloud.pje.jus.br/auth/', 'PJE_PE_1G', session=True))

    def context(self, url, *, title=True, marker=True, password=False, otp=False):
        def node(visible):
            item = MagicMock()
            item.count.return_value = int(visible)
            item.nth.return_value.is_visible.return_value = visible
            return item
        def locate(selector):
            if selector.startswith('input[type='):
                return node(password)
            if selector.startswith('input[autocomplete='):
                return node(otp)
            if selector.startswith('h1:has-text("Painel do advogado")'):
                return node(title)
            if selector.startswith('a:has-text("Expedientes")'):
                return node(marker)
            return node(False)
        frame = MagicMock(url=url)
        frame.is_detached.return_value = False
        frame.locator.side_effect = locate
        page = MagicMock(frames=[frame])
        page.is_closed.return_value = False
        return MagicMock(pages=[page])

    def test_pje_confirm_requires_trusted_panel_and_visible_data(self):
        panel='https://tjrj.pje.jus.br/1g/Painel/painel_usuario/advogado.seam'
        self.assertTrue(access.confirmed(self.context(panel), 'PJE_RJ_1G'))
        self.assertTrue(access.confirmed(self.context(panel,title=False), 'PJE_RJ_1G'))
        for kwargs in ({'marker':False}, {'password':True}, {'otp':True}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(access.confirmed(self.context(panel,**kwargs), 'PJE_RJ_1G'))
        for url in ('https://tjrj.pje.jus.br/2g/Painel/painel_usuario/advogado.seam', 'http://tjrj.pje.jus.br/1g/Painel/painel_usuario/advogado.seam', 'https://evil.example/1g/Painel/painel_usuario/advogado.seam'):
            with self.subTest(url=url):
                self.assertFalse(access.confirmed(self.context(url), 'PJE_RJ_1G'))

    def test_login_page_title_alone_is_not_authentication(self):
        url='https://tjrj.pje.jus.br/1g/login.seam'
        self.assertFalse(access.confirmed(self.context(url,marker=False), 'PJE_RJ_1G'))
        self.assertFalse(access.confirmed(self.context(url,marker=True), 'PJE_RJ_1G'))


if __name__ == '__main__':
    unittest.main()
