import sys,tempfile,unittest,types
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import eproc

class InvisibleTests(unittest.TestCase):
 def test_hidden_run_requires_login_without_waiting_or_showing_browser(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=eproc.Collector(tmp)
   with patch.object(eproc.threading,'Thread'):
    c.start(options={'tribunal':'TJSC','teste_sc':True,'invisivel':True})
   page=MagicMock();page.url='https://sso.tjsc.jus.br/';page.is_closed.return_value=False
   context=MagicMock();context.pages=[page]
   pw=MagicMock();pw.chromium.launch_persistent_context.return_value=context
   sync=MagicMock();sync.return_value.__enter__.return_value=pw
   module=types.ModuleType('playwright.sync_api');module.sync_playwright=sync
   def login_required(ctx):
    c.wait_user('Sessão exige autenticação')
   with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':module}),patch.object(c,'await_listing',side_effect=login_required),patch.dict(eproc.os.environ,{'EPROC_TJSC_USUARIO':'','EPROC_TJSC_SENHA':''}):
    c.run()
   self.assertTrue(pw.chromium.launch_persistent_context.call_args.kwargs['headless'])
   self.assertTrue(str(pw.chromium.launch_persistent_context.call_args.args[0]).endswith('sessao_tjsc'))
   self.assertEqual(c.current['estado'],'requer_login')
   self.assertTrue(context.close.called)
   self.assertTrue((Path(tmp)/c.current['id']/'checkpoint.json').exists())
 def test_background_skips_manual_login_pause(self):
  c=eproc.Collector();c.options={'tribunal':'TJSC','invisivel':True}
  context=MagicMock();context.pages=[MagicMock(url='https://sso.tjsc.jus.br/')]
  with patch.object(c,'log'),patch.object(c,'wait_user') as wait,patch.dict(eproc.os.environ,{'EPROC_TJSC_USUARIO':'','EPROC_TJSC_SENHA':''}):
   c.open_login(context)
  wait.assert_not_called()
 def test_invalid_visibility_rejected_before_run(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=eproc.Collector(tmp)
   with self.assertRaisesRegex(ValueError,'invisível'):c.start(options={'invisivel':'false'})
   self.assertEqual(list(Path(tmp).iterdir()),[])
if __name__=='__main__':unittest.main()
