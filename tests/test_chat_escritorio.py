import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,chat_interno as chat,chat_recursos as features,chat_escritorio as office
class OfficeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db.sqlite')
  self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True)
  self.a=self.store.create_user({'nome':'Ana','login':'ana','senha':'senha-forte-123'},self.owner)
  self.b=self.store.create_user({'nome':'Bruno','login':'bruno','senha':'senha-forte-123'},self.owner)
  self.c=self.store.create_user({'nome':'Carla','login':'carla','senha':'senha-forte-123'},self.owner)
  self.rid=chat.create(self.store,self.owner,{'tipo':'grupo','titulo':'Setor exemplo','membros':[self.a['id'],self.b['id']]})['id']
 def tearDown(self):self.tmp.cleanup()
 def assign(self,user,uid):return office.directory(self.store,self.owner,{'acao':'pessoa','user_id':user['id'],'unidade_id':uid})
 def post(self,scope,ids,nonce='broadcast-test-123',actor=None,kind='alerta'):
  actor=actor or self.owner;audience={'escopo':scope,'ids':ids};preview=office.preview(self.store,actor,{'audiencia':audience});body={'titulo':'Aviso teste','texto':'Mensagem interna','tipo':kind,'audiencia':audience,'previa_token':preview['token'],'nonce':nonce};return office.broadcast(self.store,actor,body),body
 def test_units_seeded_and_only_owner_assigns(self):
  data=office.directory(self.store,self.owner);self.assertEqual([u['atendimento'] for u in data['unidades']],[1,0]);self.assertEqual([u['endereco'] for u in data['unidades']],['Ramiro Barcelos, 805','Ramiro Barcelos, 787']);self.assertTrue(all(u['unidade_id'] is None for u in data['usuarios']))
  features.config(self.store,self.owner,{'user_id':self.a['id'],'admin':True,'speaker':False})
  with self.assertRaises(legal.AppError):office.directory(self.store,self.a,{'acao':'pessoa','user_id':self.b['id'],'unidade_id':2})
  self.assign(self.a,2);self.assertEqual(next(u for u in chat.users(self.store) if u['id']==self.a['id'])['unidade_id'],2)
 def test_target_unit_is_private_and_snapshot_does_not_expand(self):
  self.assign(self.a,2);self.assign(self.b,1);result,body=self.post('unidades',[2]);rid=result['id']
  self.assertEqual(chat.messages(self.store,self.a,rid)['itens'][0]['aviso']['tipo'],'alerta')
  with self.assertRaises(legal.AppError):chat.messages(self.store,self.b,rid)
  self.assign(self.b,2)
  with self.assertRaises(legal.AppError):chat.messages(self.store,self.b,rid)
 def test_everyone_reuses_general_and_includes_unassigned(self):
  rid=features.ensure_general
  result,_=self.post('todos',[]);room=chat.messages(self.store,self.c,result['id'])['conversa'];self.assertEqual(room['tipo'],'geral');self.assertEqual(result['total'],3)
 def test_sector_selected_members_deduplicated(self):
  office.directory(self.store,self.owner,{'acao':'setor','room_id':self.rid,'unidade_id':2,'setor':True})
  preview=office.preview(self.store,self.owner,{'audiencia':{'escopo':'setores','ids':[self.rid,self.rid]}});self.assertEqual({p['id'] for p in preview['pessoas']},{self.a['id'],self.b['id']});self.assertEqual(preview['total'],2)
  self.assertTrue(next(r for r in chat.rooms(self.store,self.a) if r['id']==self.rid)['setor'])
 def test_changed_roster_requires_new_preview_and_no_partial_channel(self):
  self.assign(self.a,2);aud={'escopo':'unidades','ids':[2]};review=office.preview(self.store,self.owner,{'audiencia':aud});self.assign(self.b,2)
  with self.store.connect() as db:before=db.execute('SELECT COUNT(*) FROM chat_rooms').fetchone()[0]
  with self.assertRaises(legal.AppError):office.broadcast(self.store,self.owner,{'titulo':'Alerta','texto':'Teste','tipo':'alerta','audiencia':aud,'previa_token':review['token'],'nonce':'changed-list-123'})
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chat_rooms').fetchone()[0],before)
 def test_idempotence_avoids_duplicate_messages_or_channels(self):
  result,body=self.post('pessoas',[self.a['id']]);again=office.broadcast(self.store,self.owner,body);self.assertEqual(result['mensagem_id'],again['mensagem_id']);self.assertTrue(again['repetido']);self.assertEqual(len(chat.messages(self.store,self.a,result['id'])['itens']),1)
  with self.assertRaises(legal.AppError):office.broadcast(self.store,self.owner,{**body,'texto':'Alterado'})
 def test_publication_permission_and_inactive_targets(self):
  with self.assertRaises(legal.AppError):office.preview(self.store,self.a,{'audiencia':{'escopo':'todos','ids':[]}})
  features.config(self.store,self.owner,{'user_id':self.a['id'],'admin':False,'speaker':True});result,_=self.post('pessoas',[self.b['id']],actor=self.a);self.assertEqual(len(chat.messages(self.store,self.b,result['id'])['itens']),1)
  self.store.update_user(self.b['id'],{'ativo':False},self.owner)
  with self.assertRaises(legal.AppError):office.preview(self.store,self.owner,{'audiencia':{'escopo':'pessoas','ids':[self.b['id']]}})
 def test_empty_unit_and_ambiguous_all_selection_rejected(self):
  with self.assertRaises(legal.AppError):office.preview(self.store,self.owner,{'audiencia':{'escopo':'unidades','ids':[2]}})
  with self.assertRaises(legal.AppError):office.preview(self.store,self.owner,{'audiencia':{'escopo':'todos','ids':[self.a['id']]}})

 def test_broadcast_members_fixed_and_can_pin_for_its_audience(self):
  result,_=self.post('pessoas',[self.a['id']]);rid=result['id']
  with self.assertRaises(legal.AppError):chat.members(self.store,self.owner,rid,[self.a['id'],self.b['id']])
  features.action(self.store,self.owner,result['mensagem_id'],{'acao':'fixar','titulo':'Aviso fixado','ordem':0})
  data=chat.messages(self.store,self.a,rid);self.assertTrue(data['conversa']['audiencia_fixa']);self.assertEqual(len(data['conversa']['fixados']),1)
 def test_http_preview_send_and_restricted_attachment(self):
  import servidor,threading,json,base64
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  from unittest.mock import patch
  with patch.object(legal,'store',self.store):
   server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)+'/api/juridico/chat/'
   def headers(login):
    session,key=self.store.login(login,'senha-forte-123');return {'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf'],'Content-Type':'application/json'}
   try:
    owner=headers('dono');aud={'escopo':'pessoas','ids':[self.a['id']]}
    with urlopen(Request(base+'avisos/previa',data=json.dumps({'audiencia':aud}).encode(),headers=owner)) as response:review=json.load(response)['resultado']
    payload={'titulo':'Restrito','texto':'Arquivo do setor','tipo':'alerta','audiencia':aud,'previa_token':review['token'],'nonce':'http-alert-123','anexos':[{'nome':'arquivo.txt','tipo':'arquivo','base64':base64.b64encode(b'privado').decode()}]}
    with urlopen(Request(base+'avisos',data=json.dumps(payload).encode(),headers=owner)) as response:result=json.load(response)['resultado']
    message=chat.messages(self.store,self.a,result['id'])['itens'][0];fid=message['anexos'][0]['id']
    with self.assertRaises(HTTPError) as err:urlopen(Request(base+'arquivos/'+fid,headers=headers('bruno')))
    self.assertEqual(err.exception.code,403)
    with urlopen(Request(base+'arquivos/'+fid,headers=headers('ana'))) as response:self.assertEqual(response.read(),b'privado')
   finally:server.shutdown();server.server_close();thread.join(3)
