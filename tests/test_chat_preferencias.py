import unittest,sys,tempfile,base64
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,chat_preferencias as prefs,chat_interno as chat
class PreferencesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db.sqlite')
  self.admin=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  self.other=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},self.admin)
 def tearDown(self):self.tmp.cleanup()
 def test_private_preferences_survive_new_store(self):
  prefs.save(self.store,self.other,{'tema':'escuro','ocultar_historico':True,'fixar_painel':True,'largura':480})
  reopened=legal.Store(self.store.path)
  self.assertEqual(prefs.get(reopened,self.other)['largura'],480)
  self.assertTrue(prefs.get(reopened,self.other)['ocultar_historico'])
  self.assertEqual(prefs.get(reopened,self.admin)['tema'],'sistema')
  with self.assertRaises(legal.AppError):prefs.save(self.store,self.other,{'user_id':self.admin['id']})
 def test_auto_away_online_and_expired_signal(self):
  with patch.object(legal,'now',return_value='2026-10-27T21:00:00-03:00'):
   prefs.heartbeat(self.store,self.other,{'dispositivo':'device-12345','ocioso_segundos':300})
   self.assertEqual(next(u for u in chat.users(self.store) if u['id']==self.other['id'])['presenca'],'ausente')
   prefs.heartbeat(self.store,self.other,{'dispositivo':'device-22222','ocioso_segundos':0})
   self.assertEqual(next(u for u in chat.users(self.store) if u['id']==self.other['id'])['presenca'],'online')
  with patch.object(legal,'now',return_value='2026-10-27T21:01:31-03:00'):
   self.assertEqual(next(u for u in chat.users(self.store) if u['id']==self.other['id'])['presenca'],'offline')
 def test_invisible_and_manual_states(self):
  prefs.heartbeat(self.store,self.other,{'dispositivo':'device-12345','ocioso_segundos':800})
  prefs.save(self.store,self.other,{'estado':'reuniao'})
  self.assertEqual(next(u for u in chat.users(self.store) if u['id']==self.other['id'])['presenca'],'reuniao')
  prefs.save(self.store,self.other,{'estado':'invisivel'})
  user=next(u for u in chat.users(self.store) if u['id']==self.other['id']);self.assertEqual(user['presenca'],'offline');self.assertNotIn('ultimo_sinal',user)
  prefs.offline(self.store,self.other,'device-12345')
 def test_pin_membership_and_per_user_order(self):
  first=chat.create(self.store,self.admin,{'tipo':'direta','membros':[self.other['id']]})['id']
  second=chat.create(self.store,self.admin,{'tipo':'grupo','titulo':'Setor','membros':[self.other['id']]})['id']
  prefs.pin(self.store,self.other,first,True)
  self.assertEqual(chat.rooms(self.store,self.other)[0]['id'],first)
  self.assertFalse(chat.rooms(self.store,self.admin)[0]['fixada'])
  chat.members(self.store,self.admin,second,[self.admin['id']])
  with self.assertRaises(legal.AppError):prefs.pin(self.store,self.other,second,True)
 def test_avatar_validation_and_removal(self):
  with self.assertRaises(legal.AppError):prefs.avatar_save(self.store,self.other,{'base64':base64.b64encode(b'<svg onload="test"/>').decode()})
  prefs.avatar_save(self.store,self.other,{'base64':base64.b64encode(b'\x89PNG\r\n\x1a\nimage-data').decode()})
  self.assertEqual(prefs.avatar(self.store,self.other['id'])['mime'],'image/png')
  prefs.avatar_save(self.store,self.other,{'remover':True})
  with self.assertRaises(legal.AppError):prefs.avatar(self.store,self.other['id'])
