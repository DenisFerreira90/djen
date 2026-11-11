import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import eproc,eproc_login as login,twofa,juridico
from test_twofa import codec,SECRET

def group(items):
 g=MagicMock();g.count.return_value=len(items);g.nth.side_effect=lambda i:items[i];return g

def setup_frame(host='eproc1g.tjsc.jus.br'):
 f=MagicMock(url='https://'+host+'/eproc/');f.locator.return_value=group([]);f.get_by_text.return_value=group([]);return f

class LoginFlow(unittest.TestCase):
 def collector(self,frame):
  c=eproc.Collector();c.options={'tribunal':'TJSC','invisivel':True,'autenticador_id':7};c.actor={'id':1};c.surfaces=MagicMock(return_value=[frame]);c.log=MagicMock();return c
 def test_otp_then_delayed_profile_then_listing(self):
  f=setup_frame('sso.tjsc.jus.br');field=MagicMock();form=MagicMock();submit=MagicMock();field.locator.return_value=group([form]);field.locator.return_value.locator.return_value=group([submit])
  f.locator.side_effect=lambda selector:group([field]) if selector==login.OTP_FIELDS else group([])
  c=self.collector(f)
  with patch.object(twofa,'collector_code',return_value='123456') as codes:
   login.step(c,MagicMock());login.step(c,MagicMock())
  codes.assert_called_once();field.fill.assert_called_once_with('123456',timeout=10000);submit.click.assert_called_once()
  self.assertNotIn('123456',str(c.log.call_args_list))
  f.url='https://eproc1g.tjsc.jus.br/eproc/';f.locator.side_effect=None;f.locator.return_value=group([])
  login.step(c,MagicMock())
  profile=MagicMock();f.locator.side_effect=lambda s:group([profile]) if 'data-descricao' in s else group([])
  login.step(c,MagicMock());login.step(c,MagicMock());profile.click.assert_called_once()
 def test_await_listing_rechecks_profile_after_redirect(self):
  f=setup_frame();c=self.collector(f);c.check=MagicMock();c.find_list=MagicMock(side_effect=[None,None,None,None,'listing']);c.listing=MagicMock(return_value=False)
  context=MagicMock();page=MagicMock();page.is_closed.return_value=False;context.pages=[page]
  with patch.object(login,'step') as step:
   self.assertEqual(c.await_listing(context),'listing')
  self.assertEqual(step.call_count,3)
 def test_external_host_never_receives_code(self):
  c=self.collector(setup_frame('outside.invalid'))
  with patch.object(twofa,'collector_code') as codes:login.step(c,MagicMock())
  codes.assert_not_called()
 def test_otp_permission_failure_stops_without_code(self):
  f=setup_frame();field=MagicMock();form=MagicMock();field.locator.return_value=group([form]);field.locator.return_value.locator.return_value=group([MagicMock()]);f.locator.side_effect=lambda s:group([field]) if s==login.OTP_FIELDS else group([]);c=self.collector(f)
  with patch.object(twofa,'collector_code',side_effect=ValueError('private')):
   with self.assertRaisesRegex(RuntimeError,'ACAO_HUMANA'):login.step(c,MagicMock())
  field.fill.assert_not_called();self.assertNotIn('private',str(c.log.call_args_list))

class VaultSelection(unittest.TestCase):
 def test_selected_token_only_permission_and_no_code_in_metadata(self):
  with tempfile.TemporaryDirectory() as tmp,patch('twofa.crypt',side_effect=codec),patch('twofa.time.time',return_value=59):
   store=juridico.Store(Path(tmp)/'test.db');owner=store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
   token=twofa.add(store,owner,{'nome':'SC','conta':'Titular','chave':SECRET,'confirmacao':'287082'})['id']
   self.assertIsNone(twofa.collector_code(store,owner,token))
   with patch('twofa.time.time',return_value=61):
    self.assertEqual(len(twofa.collector_code(store,owner,token)),6)
   metadata=twofa.collector_tokens(store,owner);self.assertEqual(metadata['itens'][0]['id'],token);self.assertNotIn('codigo',json.dumps(metadata));self.assertNotIn('secret',json.dumps(metadata))
   with self.assertRaises(juridico.AppError):twofa.collector_code(store,{'id':999},token)
if __name__=='__main__':unittest.main()
