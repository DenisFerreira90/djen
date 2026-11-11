import sys,tempfile,unittest,base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,chat_interno as chat,chat_produtividade as work,chat_recursos as features,chat_visualizacao as visual,chat_preferencias as prefs,chat_alertas as alerts
class WorkTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3';self.store=legal.Store(self.path)
  self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True)
  self.a=self.store.create_user({'nome':'Ana Silva','login':'ana','senha':'senha-forte-123','role':'equipe'},self.owner)
  self.b=self.store.create_user({'nome':'Bruno','login':'bruno','senha':'senha-forte-123','role':'equipe'},self.owner)
  self.out=self.store.create_user({'nome':'Outro admin','login':'outro','senha':'senha-forte-123','role':'administrador'},self.owner)
  self.rid=chat.create(self.store,self.owner,{'tipo':'grupo','titulo':'RH reservado','membros':[self.a['id']]})['id']
 def tearDown(self):self.tmp.cleanup()
 def send(self,actor=None,text='Conferir 5000425-89.2026.8.21.0059',nonce='mensagem-test-123',files=None,rid=None,**more):
  return chat.send(self.store,actor or self.a,rid or self.rid,{'texto':text,'nonce':nonce,'anexos':files or [],**more})['id']
 def file(self):return {'nome':'contrato.txt','tipo':'arquivo','base64':base64.b64encode(b'reservado').decode()}
 def test_lost_confirmation_retry_and_changed_payload(self):
  f=self.file();mid=self.send(files=[f]);self.assertEqual(self.send(files=[f]),mid)
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM chat_messages').fetchone()[0],1)
  for args in ({'text':'Outro','files':[f]},{},{'files':[{**f,'base64':base64.b64encode(b'alterado').decode()}]}):
   with self.assertRaises(legal.AppError):self.send(**args)
 def test_history_all_paths_and_existing_members(self):
  mid=self.send(files=[self.file()]);fid=chat.messages(self.store,self.a,self.rid)['itens'][0]['anexos'][0]['id']
  work.history(self.store,self.owner,self.rid,{'politica':'apos_entrada'});chat.members(self.store,self.owner,self.rid,[self.a['id'],self.b['id']])
  new=self.send(nonce='mensagem-test-456',responder_id=mid)
  data=chat.messages(self.store,self.b,self.rid);self.assertEqual([m['id'] for m in data['itens']],[new]);self.assertIsNone(data['itens'][0]['resposta'])
  self.assertEqual(len(chat.messages(self.store,self.a,self.rid)['itens']),2)
  for call in (lambda:chat.download(self.store,self.b,fid),lambda:features.forward(self.store,self.b,mid,{'destino_id':self.rid,'nonce':'forward-test-789'}),lambda:work.message(self.store,self.b,mid,{'acao':'salvar'}),lambda:visual.acknowledge(self.store,self.b,self.rid,[mid],True)):
   with self.assertRaises(legal.AppError):call()
  self.assertEqual([m['id'] for m in work.list_items(self.store,self.b,'busca')['itens']],[new])
  self.assertNotIn(mid,[m['id'] for m in alerts.feed(self.store,self.b,0)['itens']]);self.assertNotIn(mid,[m['id'] for m in visual.previews(self.store,self.b)['itens']])
 def test_policy_only_owner_and_full_history(self):
  mid=self.send()
  with self.assertRaises(legal.AppError):work.history(self.store,self.a,self.rid,{'politica':'apos_entrada'})
  work.history(self.store,self.owner,self.rid,{'politica':'completo'});chat.members(self.store,self.owner,self.rid,[self.a['id'],self.b['id']]);self.assertEqual(chat.messages(self.store,self.b,self.rid)['itens'][0]['id'],mid)
 def test_saved_private_and_revoked(self):
  mid=self.send();work.message(self.store,self.a,mid,{'acao':'salvar'});self.assertEqual(len(work.list_items(self.store,self.a,'salvos')['itens']),1)
  self.assertEqual(work.list_items(self.store,self.owner,'salvos')['itens'],[]);self.assertEqual(work.list_items(self.store,self.out,'busca')['itens'],[])
  chat.members(self.store,self.owner,self.rid,[self.b['id']]);self.assertEqual(work.list_items(self.store,self.a,'salvos')['itens'],[])
 def test_search_filters_and_literal_query(self):
  mid=self.send(files=[self.file()]);self.send(self.owner,text='Outra informação',nonce='mensagem-test-222')
  f={'pessoa':str(self.a['id']),'conversa':str(self.rid),'inicio':legal.now()[:10],'fim':legal.now()[:10],'anexos':'1','texto':'contrato.txt'}
  self.assertEqual([m['id'] for m in work.list_items(self.store,self.owner,'busca',f)['itens']],[mid]);self.assertEqual(work.list_items(self.store,self.owner,'busca',{'texto':"%' OR 1=1 --"})['itens'],[])
  with self.assertRaises(legal.AppError):work.list_items(self.store,self.owner,'busca',{'inicio':'2026-11-10','fim':'2026-11-01'})
 def test_task_assignment_context_status_and_revocation(self):
  mid=self.send();body={'acao':'demanda','titulo':'Conferir mandado','responsavel_id':self.owner['id'],'prazo':'2026-11-05','processo':'5000425-89.2026.8.21.0059'}
  tid=work.message(self.store,self.a,mid,body)['id'];row=work.tasks(self.store,self.owner)['itens'][0];self.assertIn('5000425',row['contexto']);self.assertEqual(row['message_id'],mid);self.assertEqual(work.tasks(self.store,self.b)['itens'],[])
  with self.assertRaises(legal.AppError):work.message(self.store,self.a,mid,{**body,'responsavel_id':self.out['id']})
  work.tasks(self.store,self.owner,{'id':tid,'status':'concluida'});self.assertEqual(work.tasks(self.store,self.a)['itens'][0]['status'],'concluida')
  chat.members(self.store,self.owner,self.rid,[self.b['id']]);self.assertEqual(work.tasks(self.store,self.a)['itens'],[])
 def test_ack_explicit_snapshot_idempotent(self):
  rid=chat.create(self.store,self.owner,{'tipo':'comunicado','titulo':'Regra importante','membros':[self.a['id']]})['id'];mid=self.send(self.owner,rid=rid)
  work.message(self.store,self.owner,mid,{'acao':'solicitar_ciencia'});chat.read(self.store,self.a,rid,mid);self.assertEqual(chat.messages(self.store,self.a,rid)['itens'][0]['ciencia']['confirmados'],0)
  work.message(self.store,self.a,mid,{'acao':'ciente'});work.message(self.store,self.a,mid,{'acao':'ciente'})
  data=chat.messages(self.store,self.owner,rid)['itens'][0]['ciencia'];self.assertEqual(data['confirmados'],1);self.assertEqual(len(data['pessoas']),1);self.assertNotIn('pessoas',chat.messages(self.store,self.a,rid)['itens'][0]['ciencia'])
  chat.members(self.store,self.owner,rid,[self.a['id'],self.b['id']]);work.message(self.store,self.owner,mid,{'acao':'solicitar_ciencia'});self.assertEqual(chat.messages(self.store,self.owner,rid)['itens'][0]['ciencia']['total'],1)
  with self.assertRaises(legal.AppError):work.message(self.store,self.b,mid,{'acao':'ciente'})
 def test_personal_notes_persist_and_deny_other_admin(self):
  work.notes(self.store,self.a,{'titulo':'Lembrar','texto':'Falar com cliente'});nid=work.notes(self.store,self.a)['itens'][0]['id'];self.assertEqual(work.notes(self.store,self.owner)['itens'],[])
  with self.assertRaises(legal.AppError):work.notes(self.store,self.owner,{'id':nid,'remover':True})
  self.assertEqual(work.notes(legal.Store(self.path),self.a)['itens'][0]['texto'],'Falar com cliente')
 def test_quiet_position_and_private_previews(self):
  p=prefs.save(self.store,self.a,{'silencio_inicio':'22:00','silencio_fim':'08:00','painel_x':250,'painel_y':45});self.assertEqual(p['painel_x'],250)
  with self.assertRaises(legal.AppError):prefs.save(self.store,self.a,{'silencio_inicio':'25:00'})
  with self.assertRaises(legal.AppError):prefs.save(self.store,self.a,{'painel_x':True})
  self.send(self.owner,text='@Ana Silva conferir cliente');item=alerts.feed(self.store,self.a,0)['itens'][0];self.assertEqual(item['prioridade'],'mencao');self.assertIn('previa',item)
  prefs.save(self.store,self.a,{'ocultar_historico':True});self.assertNotIn('previa',alerts.feed(self.store,self.a,0)['itens'][0])
 def test_independent_chat_migration_keeps_saved_notes_and_tasks(self):
  import chat_servico
  mid=self.send();work.message(self.store,self.a,mid,{'acao':'salvar'});work.notes(self.store,self.a,{'titulo':'Pessoal','texto':'Retornar ligação'})
  work.message(self.store,self.a,mid,{'acao':'demanda','titulo':'Conferir','responsavel_id':self.owner['id'],'prazo':'2026-11-05'})
  dest=Path(self.tmp.name)/'independente.sqlite3';chat_servico.migrate(self.path,dest);separate=legal.Store(dest)
  self.assertEqual(len(work.list_items(separate,self.a,'salvos')['itens']),1);self.assertEqual(len(work.notes(separate,self.a)['itens']),1);self.assertEqual(len(work.tasks(separate,self.owner)['itens']),1)
  self.assertEqual(work.notes(separate,self.out)['itens'],[])
 def test_http_auth_csrf_and_private_scope(self):
  import servidor,threading,json
  from unittest.mock import patch
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  mid=self.send();work.message(self.store,self.a,mid,{'acao':'salvar'})
  with patch.object(legal,'store',self.store):
   server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)+'/api/juridico/chat/produtividade/'
   try:
    def headers(login):
     session,key=self.store.login(login,'senha-forte-123');return {'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf'],'Content-Type':'application/json'}
    a=headers('ana');other=headers('outro')
    with urlopen('http://127.0.0.1:'+str(server.server_port)+'/js/chat-produtividade.js') as response:self.assertEqual(response.status,200)
    with self.assertRaises(HTTPError) as error:urlopen(base+'salvos')
    self.assertEqual(error.exception.code,401)
    with urlopen(Request(base+'salvos',headers=a)) as response:self.assertEqual(len(json.load(response)['resultado']['itens']),1)
    with urlopen(Request(base+'salvos',headers=other)) as response:self.assertEqual(json.load(response)['resultado']['itens'],[])
    payload=json.dumps({'acao':'salvar'}).encode()
    with self.assertRaises(HTTPError) as error:urlopen(Request(base+'mensagem/'+str(mid),data=payload,headers={k:v for k,v in a.items() if k!='X-CSRF-Token'}))
    self.assertEqual(error.exception.code,403)
    with self.assertRaises(HTTPError) as error:urlopen(Request(base+'mensagem/'+str(mid),data=payload,headers=other))
    self.assertEqual(error.exception.code,403)
    with urlopen(Request(base+'notas',data=json.dumps({'titulo':'Pessoal','texto':'Nota de teste'}).encode(),headers=a)) as response:self.assertEqual(len(json.load(response)['resultado']['itens']),1)
   finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
