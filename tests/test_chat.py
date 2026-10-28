import sys,tempfile,unittest,base64,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,chat_interno as chat,painel_operacional as panel

class ChatTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db.sqlite')
  self.admin=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  self.a=self.store.create_user({'nome':'Ana','login':'ana','senha':'senha-forte-123','role':'equipe'},self.admin)
  self.b=self.store.create_user({'nome':'Bruno','login':'bruno','senha':'senha-forte-123','role':'equipe'},self.admin)
  self.other=self.store.create_user({'nome':'Outro','login':'outro','senha':'senha-forte-123','role':'equipe'},self.admin)
 def tearDown(self):self.tmp.cleanup()
 def room(self):return chat.create(self.store,self.admin,{'tipo':'grupo','titulo':'Equipe','membros':[self.a['id'],self.b['id']]})['id']
 def send(self,rid,files=None,nonce='test-nonce-123'):return chat.send(self.store,self.a,rid,{'texto':'Mensagem de trabalho','nonce':nonce,'anexos':files or []})
 def test_access_and_audited_admin(self):
  rid=self.room();self.send(rid)
  with self.assertRaises(legal.AppError):chat.messages(self.store,self.other,rid)
  observer=self.store.create_user({'nome':'Auditor','login':'auditor','senha':'senha-forte-123','role':'administrador'},self.admin)
  with self.assertRaises(legal.AppError):chat.messages(self.store,observer,rid)
  with self.assertRaises(legal.AppError):chat.messages(self.store,observer,rid,reason='Conferência de atendimento')
  direct=chat.create(self.store,self.a,{'tipo':'direta','membros':[self.b['id']]})['id']
  chat.messages(self.store,self.admin,direct,reason='Conferência de atendimento')
  with self.store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE acao='consultar_chat'").fetchone()[0],1)
 def test_idempotency_unread_and_removed_member(self):
  rid=self.room();mid=self.send(rid)['id'];self.assertEqual(self.send(rid)['id'],mid)
  self.assertEqual(next(r for r in chat.rooms(self.store,self.b) if r['id']==rid)['nao_lidas'],1)
  chat.read(self.store,self.b,rid,mid);self.assertEqual(next(r for r in chat.rooms(self.store,self.b) if r['id']==rid)['nao_lidas'],0)
  chat.members(self.store,self.admin,rid,[self.a['id'],self.other['id']])
  with self.assertRaises(legal.AppError):chat.messages(self.store,self.b,rid)
 def test_attachment_requires_room_access(self):
  rid=self.room();self.send(rid,[{'nome':'figurinha.webp','tipo':'figurinha','base64':base64.b64encode(b'RIFF0000WEBPexample').decode()}])
  f=chat.messages(self.store,self.a,rid)['itens'][0]['anexos'][0]
  self.assertEqual(chat.download(self.store,self.b,f['id'])['mime'],'image/webp')
  with self.assertRaises(legal.AppError):chat.download(self.store,self.other,f['id'])
  with self.assertRaises(legal.AppError):chat.attachment({'nome':'evil.svg','tipo':'figurinha','base64':base64.b64encode(b'<svg onload="evil()"/>').decode()})
 def test_communication_restricted_and_reader(self):
  with self.assertRaises(legal.AppError):chat.create(self.store,self.a,{'tipo':'comunicado','titulo':'Aviso','membros':[self.b['id']]})
  rid=chat.create(self.store,self.admin,{'tipo':'comunicado','titulo':'Aviso','membros':[self.b['id']]})['id']
  with self.assertRaises(legal.AppError):chat.send(self.store,self.b,rid,{'texto':'Não','nonce':'test-nonce-456'})
  with self.assertRaises(legal.AppError):chat.create(self.store,{**self.a,'role':'leitor'},{})
 def test_direct_unique_and_history_pagination(self):
  rid=chat.create(self.store,self.a,{'tipo':'direta','membros':[self.b['id']]})['id']
  self.assertEqual(chat.create(self.store,self.b,{'tipo':'direta','membros':[self.a['id']]})['id'],rid)
  with self.store.connect() as db:
   chat.schema(db)
   db.executemany('INSERT INTO chat_messages(room_id,sender_id,texto,criado,nonce) VALUES(?,?,?,?,?)',[(rid,self.a['id'],'Mensagem '+str(i),legal.now(),'nonce-'+str(i)) for i in range(105)])
  page=chat.messages(self.store,self.a,rid);self.assertTrue(page['tem_mais']);self.assertEqual(len(page['itens']),100)
  older=chat.messages(self.store,self.a,rid,before=page['itens'][0]['id']);self.assertEqual(len(older['itens']),5)
  self.assertEqual(len(chat.messages(self.store,self.a,rid,search='Mensagem 104')['itens']),1)
 def test_dashboard_scope_and_unconfirmed_deadline(self):
  today=legal.now()[:10]
  case=self.store.save('processos',{'dados':{'numero':'5004310-40.2026.8.21.0018','titulo':'Teste'}},self.admin)
  for user in (self.a,self.b):self.store.save('prazos',{'processo_id':case['id'],'dados':{'titulo':'Fatal','vencimento':today,'status':'pendente','responsavel_id':user['id'],'conferido':False}},self.admin)
  a=panel.report(self.store,self.a);admin=panel.report(self.store,self.admin)
  self.assertEqual(a['contagens']['fatais_hoje'],1);self.assertEqual(admin['contagens']['fatais_hoje'],2)
  self.assertNotIn('financeiro_vencido',a['contagens']);self.assertIn('financeiro_vencido',admin['contagens'])
  self.assertEqual(a['contagens']['prazos_sem_conferencia'],1)
 def test_http_auth_files_and_export(self):
  import servidor,threading
  from unittest.mock import patch
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  rid=self.room();self.send(rid,[{'nome':'arquivo.txt','tipo':'arquivo','base64':base64.b64encode(b'confidencial').decode()}])
  f=chat.messages(self.store,self.a,rid)['itens'][0]['anexos'][0]
  with patch.object(legal,'store',self.store):
   server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
   def headers(login):
    session,key=self.store.login(login,'senha-forte-123');return {'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf'],'Content-Type':'application/json'}
   try:
    with self.assertRaises(HTTPError) as err:urlopen(base+'/api/juridico/chat/conversas')
    self.assertEqual(err.exception.code,401)
    other=headers('outro')
    with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/juridico/chat/arquivos/'+f['id'],headers=other))
    self.assertEqual(err.exception.code,403)
    admin=headers('admin')
    with urlopen(Request(base+'/api/juridico/chat/conversas/'+str(rid)+'/exportar?motivo=Conferencia',headers=admin)) as response:
     self.assertEqual(len(json.load(response)['itens']),1)
    with urlopen(Request(base+'/api/juridico/chat/arquivos/'+f['id'],headers=headers('ana'))) as response:
     self.assertEqual(response.read(),b'confidencial');self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
    with urlopen(Request(base+'/api/juridico/painel-operacional',headers=other)) as response:self.assertEqual(json.load(response)['resultado']['contagens']['fatais_hoje'],0)
   finally:server.shutdown();server.server_close();thread.join(3)
 def test_only_admin_manages_sectors_and_extensions(self):
  with self.assertRaises(legal.AppError):chat.create(self.store,self.a,{'tipo':'grupo','titulo':'Jurídico','membros':[self.b['id']]})
  rid=self.room()
  with self.assertRaises(legal.AppError):chat.members(self.store,self.a,rid,[self.a['id'],self.b['id']])
  with self.assertRaises(legal.AppError):chat.rename(self.store,self.a,rid,'Novo setor')
  with self.assertRaises(legal.AppError):chat.profile(self.store,self.a,self.a['id'],{'nome':'Ana','ramal':'101'})
  chat.profile(self.store,self.admin,self.a['id'],{'nome':'Ana Equipe','ramal':'101'})
  self.assertEqual(next(u for u in chat.users(self.store) if u['id']==self.a['id'])['ramal'],'101')
  chat.profile(self.store,self.admin,self.a['id'],{'nome':'Ana Equipe','ramal':''})
  chat.rename(self.store,self.admin,rid,'Controladoria')
  self.assertEqual(next(r for r in chat.rooms(self.store,self.a) if r['id']==rid)['titulo'],'Controladoria')
  direct=chat.create(self.store,self.a,{'tipo':'direta','membros':[self.other['id']]})['id']
  self.assertIsInstance(direct,int)
