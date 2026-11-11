import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import eproc,eproc_tribunais as courts,eproc_login as login
from test_eproc_login import setup_frame,group
RJ='5001234-12.2026.8.19.0001'
class RJTests(unittest.TestCase):
 def test_scope_identity_and_isolated_session(self):
  self.assertEqual(courts.from_number(RJ),'TJRJ');self.assertEqual(courts.entry('TJRJ'),'https://eproc1g.tjrj.jus.br/eproc/')
  self.assertEqual(len({courts.config(k)['sessao'] for k in ('TJRS','TJSC','TJRJ')}),3)
  url=courts.entry('TJRJ')+'controlador.php?acao=processo_selecionar'
  self.assertTrue(courts.valid_url(url,'TJRJ'));self.assertFalse(courts.valid_url(url,'TJSC'))
  self.assertFalse(courts.enabled('TJRJ'))
 def test_explicit_manual_start_and_automatic_denied(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=eproc.Collector(tmp)
   for extra in ({'automatico':True},{'monitorar_lista':True}):
    with self.assertRaises(ValueError):c.start(options=dict(extra,tribunal='TJRJ',teste_rj=True))
   with patch.object(eproc.threading,'Thread') as thread:
    c.start(options={'tribunal':'TJRJ','teste_rj':True,'invisivel':True})
   self.assertEqual(c.current['tribunal'],'TJRJ');thread.return_value.start.assert_called_once()
 def test_rj_does_not_reuse_sc_credentials(self):
  f=setup_frame('eproc-sso.tjrj.jus.br');u,p,b=MagicMock(),MagicMock(),MagicMock()
  f.locator.side_effect=lambda s:group([u]) if s=='input[name="username"]' else group([p]) if s=='input[name="password"]' else group([b]) if s=='#kc-login' else group([])
  c=eproc.Collector();c.options={'tribunal':'TJRJ'};c.surfaces=MagicMock(return_value=[f]);c.log=MagicMock()
  with patch.dict(eproc.os.environ,{'EPROC_TJRJ_USUARIO':'rj-user','EPROC_TJRJ_SENHA':'rj-password','EPROC_TJSC_USUARIO':'sc-user','EPROC_TJSC_SENHA':'sc-password'}):login.step(c,MagicMock())
  u.fill.assert_called_once_with('rj-user',timeout=10000);p.fill.assert_called_once_with('rj-password',timeout=10000)
 def test_403_does_not_ask_to_continue_login(self):
  c=eproc.Collector();c.options={'tribunal':'TJRS'};c.block_status=403;c.log=MagicMock();context=MagicMock();context.pages=[MagicMock()]
  with patch.object(c,'wait_user') as wait:
   with self.assertRaisesRegex(RuntimeError,'HTTP_403'):c.open_login(context)
  wait.assert_not_called()
if __name__=='__main__':unittest.main()
