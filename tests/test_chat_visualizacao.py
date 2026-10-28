import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,chat_interno as chat,chat_recursos as features,chat_visualizacao as visual,chat_preferencias as prefs
class ViewingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db.sqlite')
  self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True)
  self.a=self.store.create_user({'nome':'Ana','login':'ana','senha':'senha-forte-123'},self.owner)
  self.b=self.store.create_user({'nome':'Bruno','login':'bruno','senha':'senha-forte-123'},self.owner)
  self.room=chat.create(self.store,self.owner,{'tipo':'grupo','titulo':'Grupo','membros':[self.a['id'],self.b['id']]})['id'];self.n=0
 def tearDown(self):self.tmp.cleanup()
 def send(self):
  self.n+=1;return chat.send(self.store,self.owner,self.room,{'texto':'Mensagem '+str(self.n),'nonce':'viewing-nonce-'+str(self.n)})['id']
 def set_rule(self,scope,values,user=None,actor=None):return visual.config(self.store,actor or self.owner,{'escopo':scope,'valores':values,**({'user_id':user['id']} if user else {})})
 def test_owner_only_even_delegated_admin(self):
  features.config(self.store,self.owner,{'user_id':self.a['id'],'admin':True,'speaker':True})
  for scope in ('geral','usuario'):
   with self.assertRaises(legal.AppError):self.set_rule(scope,{'previas':False},self.b,self.a)
  self.set_rule('usuario',{'previas':False},self.a);prefs.save(self.store,self.a,{'mostrar_previas':True})
  self.assertFalse(prefs.get(self.store,self.a)['recursos']['previas'])
 def test_preview_does_not_mark_read_or_generate_time(self):
  mid=self.send();before=chat.rooms(self.store,self.a);data=visual.previews(self.store,self.a);self.assertEqual(data['itens'][0]['id'],mid)
  self.assertEqual(next(r for r in before if r['id']==self.room)['nao_lidas'],next(r for r in chat.rooms(self.store,self.a) if r['id']==self.room)['nao_lidas'])
  self.assertEqual(visual.receipt(self.store,self.owner,mid)['visualizadas'],0)
  self.set_rule('geral',{'previas':False})
  with self.assertRaises(legal.AppError):visual.previews(self.store,self.a)
 def test_explicit_visible_messages_leave_unseen_gaps_unread(self):
  ids=[self.send() for _ in range(3)];chat.read(self.store,self.a,self.room,[ids[2]])
  room=next(r for r in chat.rooms(self.store,self.a) if r['id']==self.room);self.assertEqual(room['nao_lidas'],2)
  self.assertEqual(visual.receipt(self.store,self.owner,ids[0])['visualizadas'],0)
  self.assertEqual(visual.receipt(self.store,self.owner,ids[2])['visualizadas'],1)
 def test_first_visualization_time_immutable_and_delivery_not_reading(self):
  mid=self.send()
  with patch.object(legal,'now',return_value='2026-10-28T21:00:00-03:00'):visual.acknowledge(self.store,self.a,self.room,[mid])
  r=visual.receipt(self.store,self.owner,mid);self.assertEqual(r['visualizadas'],0);self.assertEqual(r['pessoas'][0]['estado'],'recebida')
  with patch.object(legal,'now',return_value='2026-10-28T21:02:00-03:00'):chat.read(self.store,self.a,self.room,[mid])
  with patch.object(legal,'now',return_value='2026-10-28T22:00:00-03:00'):chat.read(self.store,self.a,self.room,[mid])
  person=next(p for p in visual.receipt(self.store,self.owner,mid)['pessoas'] if p['id']==self.a['id']);self.assertEqual(person['lida_em'],'2026-10-28T21:02:00-03:00');self.assertEqual(person['recebida_em'],'2026-10-28T21:00:00-03:00')
 def test_sender_only_access_and_policy_hides_timestamps_at_api(self):
  mid=self.send();chat.read(self.store,self.a,self.room,[mid])
  with self.assertRaises(legal.AppError):visual.receipt(self.store,self.b,mid)
  self.set_rule('usuario',{'horarios':False},self.owner);r=visual.receipt(self.store,self.owner,mid)
  self.assertNotIn('lida_em',r['pessoas'][0]);self.assertFalse(r['horarios_permitidos'])
  self.set_rule('geral',{'confirmacoes':False})
  with self.assertRaises(legal.AppError):visual.receipt(self.store,self.owner,mid)
  self.assertNotIn('confirmacao',chat.messages(self.store,self.owner,self.room)['itens'][0]);self.assertNotIn('last_read',chat.messages(self.store,self.b,self.room)['conversa']['membros'][0])
 def test_recording_disabled_never_backfills_old_read_time(self):
  mid=self.send();self.set_rule('geral',{'registrar_horarios':False});chat.read(self.store,self.a,self.room,[mid]);self.set_rule('geral',{'registrar_horarios':True});chat.read(self.store,self.a,self.room,[mid])
  person=next(p for p in visual.receipt(self.store,self.owner,mid)['pessoas'] if p['id']==self.a['id']);self.assertIsNone(person['lida_em']);self.assertTrue(person['horario_anterior_indisponivel'])
 def test_legacy_read_cursor_has_no_invented_time(self):
  mid=self.send()
  with self.store.connect() as db:
   db.execute('DROP TABLE chat_read_baseline');db.execute('UPDATE chat_members SET last_read=? WHERE room_id=? AND user_id=?',(mid,self.room,self.a['id']))
  person=next(p for p in visual.receipt(self.store,self.owner,mid)['pessoas'] if p['id']==self.a['id']);self.assertEqual(person['estado'],'visualizada');self.assertIsNone(person['lida_em'])
  chat.read(self.store,self.a,self.room,[mid]);person=next(p for p in visual.receipt(self.store,self.owner,mid)['pessoas'] if p['id']==self.a['id']);self.assertIsNone(person['lida_em']);self.assertIsNone(person['recebida_em'])
 def test_cross_room_ack_rejected_and_removed_member_loses_access(self):
  mid=self.send();direct=chat.create(self.store,self.a,{'tipo':'direta','membros':[self.b['id']]})['id']
  with self.assertRaises(legal.AppError):chat.read(self.store,self.a,direct,[mid])
  chat.members(self.store,self.owner,self.room,[self.b['id']])
  with self.assertRaises(legal.AppError):chat.read(self.store,self.a,self.room,[mid])
  self.assertEqual(visual.previews(self.store,self.a)['itens'],[])
 def test_preview_honors_privacy_and_preferences_survive_restart(self):
  self.send();prefs.save(self.store,self.a,{'ocultar_historico':True,'recolher_auto':False})
  with self.assertRaises(legal.AppError):visual.previews(self.store,self.a)
  reopened=legal.Store(self.store.path);self.assertFalse(prefs.get(reopened,self.a)['recursos']['recolher_auto'])
 def test_http_policy_is_owner_only_and_timestamps_filtered(self):
  import servidor,threading
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  mid=self.send()
  with patch.object(legal,'store',self.store):
   server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)+'/api/juridico/chat/'
   def headers(login):
    session,key=self.store.login(login,'senha-forte-123');return {'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf'],'Content-Type':'application/json'}
   owner=headers('dono');team=headers('ana')
   try:
    payload=json.dumps({'escopo':'geral','valores':{'horarios':False}}).encode()
    with self.assertRaises(HTTPError) as error:urlopen(Request(base+'configuracoes',headers=team,data=payload))
    self.assertEqual(error.exception.code,403)
    with urlopen(Request(base+f'conversas/{self.room}/lida',headers=team,data=json.dumps({'mensagens':[mid]}).encode())) as response:self.assertEqual(response.status,200)
    with urlopen(Request(base+'configuracoes',headers=owner,data=payload)) as response:self.assertEqual(response.status,200)
    with urlopen(Request(base+f'mensagens/{mid}/leituras',headers=owner)) as response:data=json.load(response)['resultado']
    self.assertNotIn('lida_em',data['pessoas'][0]);self.assertEqual(data['visualizadas'],1)
   finally:server.shutdown();server.server_close();thread.join(3)

 def test_owner_can_disable_an_individual_read_sharing(self):
  mid=self.send();self.set_rule('usuario',{'compartilhar_leitura':False},self.a);chat.read(self.store,self.a,self.room,[mid])
  r=visual.receipt(self.store,self.owner,mid);person=next(p for p in r['pessoas'] if p['id']==self.a['id']);self.assertEqual(person['estado'],'recebida');self.assertIsNone(person['lida_em']);self.assertEqual(r['visualizadas'],0)
  self.assertEqual(next(r for r in chat.rooms(self.store,self.a) if r['id']==self.room)['nao_lidas'],0)
  self.set_rule('usuario',{'compartilhar_leitura':True},self.a);chat.read(self.store,self.a,self.room,[mid]);self.assertEqual(visual.receipt(self.store,self.owner,mid)['visualizadas'],0)
 def test_revoking_sharing_hides_previously_shared_read(self):
  mid=self.send();chat.read(self.store,self.a,self.room,[mid]);self.assertEqual(visual.receipt(self.store,self.owner,mid)['visualizadas'],1)
  self.set_rule('geral',{'compartilhar_leitura':False});r=visual.receipt(self.store,self.owner,mid);self.assertEqual(r['visualizadas'],0);self.assertTrue(all(p['lida_em'] is None for p in r['pessoas']))
