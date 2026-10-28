import sys,tempfile,unittest,base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,chat_interno as chat,chat_recursos as ext
class ResourcesTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db.sqlite')
  self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True)
  self.a=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},self.owner)
  self.b=self.store.create_user({'nome':'Outro admin sistema','login':'outro','senha':'senha-forte-123','role':'administrador'},self.owner)
  self.rid=chat.create(self.store,self.owner,{'tipo':'grupo','titulo':'Setor','membros':[self.a['id']]})['id']
  self.counter=0
 def tearDown(self):self.tmp.cleanup()
 def send(self,actor=None,rid=None,**extra):
  self.counter+=1
  return chat.send(self.store,actor or self.owner,rid or self.rid,{'texto':'Mensagem','nonce':'test-nonce-'+str(self.counter),**extra})['id']
 def general(self,actor=None):return next(r for r in chat.rooms(self.store,actor or self.a) if r['tipo']=='geral')['id']
 def grant(self,uid,admin=False,speaker=False):return ext.config(self.store,self.owner,{'user_id':uid,'admin':admin,'speaker':speaker})
 def test_owner_exclusive_delegation_and_revocation(self):
  with self.assertRaises(legal.AppError):ext.config(self.store,self.b,{'user_id':self.a['id'],'admin':True,'speaker':True})
  with self.assertRaises(legal.AppError):chat.rename(self.store,self.b,self.rid,'Intrusão')
  self.grant(self.a['id'],admin=True);chat.rename(self.store,self.a,self.rid,'Autorizado')
  with self.assertRaises(legal.AppError):ext.config(self.store,self.a,{'user_id':self.b['id'],'admin':True,'speaker':True})
  self.grant(self.a['id'])
  with self.assertRaises(legal.AppError):chat.rename(self.store,self.a,self.rid,'Revogado')
 def test_general_membership_publish_grant_revoke(self):
  rid=self.general();room=chat.messages(self.store,self.a,rid)['conversa'];self.assertEqual(len(room['membros']),3);self.assertFalse(room['pode_publicar'])
  with self.assertRaises(legal.AppError):self.send(self.a,rid)
  self.grant(self.a['id'],speaker=True);self.send(self.a,rid);self.grant(self.a['id'])
  with self.assertRaises(legal.AppError):self.send(self.a,rid)
  with self.assertRaises(legal.AppError):self.send(self.b,rid)
  with self.assertRaises(legal.AppError):chat.members(self.store,self.owner,rid,[])
 def test_reply_scope_and_forward_without_original_identity(self):
  mid=self.send(self.a);reply=self.send(responder_id=mid)
  data=chat.messages(self.store,self.owner,self.rid)['itens'][-1];self.assertEqual(data['resposta']['nome'],self.a['nome'])
  direct=chat.create(self.store,self.owner,{'tipo':'direta','membros':[self.b['id']]})['id']
  with self.assertRaises(legal.AppError):self.send(rid=direct,responder_id=mid)
  result=ext.forward(self.store,self.owner,mid,{'destino_id':direct,'nonce':'forward-nonce-123'})
  again=ext.forward(self.store,self.owner,mid,{'destino_id':direct,'nonce':'forward-nonce-123'});self.assertEqual(result,again)
  m=chat.messages(self.store,self.b,direct)['itens'][0];self.assertEqual(m['sender_id'],self.owner['id']);self.assertTrue(m['encaminhada']);self.assertIsNone(m['resposta']);self.assertNotIn('original_sender',m)
  with self.assertRaises(legal.AppError):ext.forward(self.store,self.b,mid,{'destino_id':direct,'nonce':'forward-nonce-456'})
 def test_reactions_toggle_one_per_user_nonmember_denied(self):
  mid=self.send();ext.action(self.store,self.a,mid,{'acao':'reagir','emoji':'👍'});ext.action(self.store,self.owner,mid,{'acao':'reagir','emoji':'👍'})
  self.assertEqual(len(chat.messages(self.store,self.a,self.rid)['itens'][0]['reacoes']),2)
  ext.action(self.store,self.a,mid,{'acao':'reagir','emoji':'❤️'});ext.action(self.store,self.a,mid,{'acao':'reagir','emoji':'❤️'})
  self.assertEqual(len(chat.messages(self.store,self.a,self.rid)['itens'][0]['reacoes']),1)
  with self.assertRaises(legal.AppError):ext.action(self.store,self.b,mid,{'acao':'reagir','emoji':'👍'})
 def test_poll_unique_vote_change_close_and_validation(self):
  mid=self.send(enquete=['Sim','Não']);ext.action(self.store,self.a,mid,{'acao':'votar','opcao':0});ext.action(self.store,self.a,mid,{'acao':'votar','opcao':1})
  p=chat.messages(self.store,self.a,self.rid)['itens'][0]['enquete'];self.assertEqual(len(p['votos']),1);self.assertEqual(p['votos'][0]['opcao'],1)
  with self.assertRaises(legal.AppError):ext.action(self.store,self.a,mid,{'acao':'encerrar'})
  ext.action(self.store,self.owner,mid,{'acao':'encerrar'})
  with self.assertRaises(legal.AppError):ext.action(self.store,self.a,mid,{'acao':'votar','opcao':0})
  for options in (['Sim'],['Sim',' sim '],[1,2]):
   with self.assertRaises(legal.AppError):self.send(enquete=options)
 def test_pinned_board_order_and_mute_persistence(self):
  rid=self.general();one=self.send(rid=rid);two=self.send(rid=rid)
  for mid,pos in ((one,20),(two,10)):ext.action(self.store,self.owner,mid,{'acao':'fixar','titulo':'Prioridade','ordem':pos})
  self.assertEqual([r['mensagem_id'] for r in chat.messages(self.store,self.a,rid)['conversa']['fixados']],[two,one])
  with self.assertRaises(legal.AppError):ext.action(self.store,self.a,one,{'acao':'desfixar'})
  ext.mute(self.store,self.a,rid,{'silenciado':True});reopened=legal.Store(self.store.path)
  self.assertTrue(next(r for r in chat.rooms(reopened,self.a) if r['id']==rid)['silenciado']);self.assertFalse(next(r for r in chat.rooms(reopened,self.owner) if r['id']==rid)['silenciado'])
  ext.action(self.store,self.owner,one,{'acao':'desfixar'});self.assertEqual(len(chat.messages(self.store,self.a,rid)['conversa']['fixados']),1)
 def test_owner_account_cannot_be_taken_by_another_system_admin(self):
  ext.config(self.store,self.owner)
  with self.assertRaises(legal.AppError):self.store.update_user(self.owner['id'],{'senha':'roubar-conta-123'},self.b)
  with self.assertRaises(legal.AppError):self.store.update_user(self.owner['id'],{'ativo':False},self.owner)
 def test_forward_attachment_and_reply_are_independent(self):
  raw=b'RIFF0000WEBPexample'
  mid=self.send(self.a,anexos=[{'nome':'imagem.webp','tipo':'figurinha','base64':base64.b64encode(raw).decode()}])
  destination=chat.create(self.store,self.owner,{'tipo':'direta','membros':[self.b['id']]})['id']
  ext.forward(self.store,self.owner,mid,{'destino_id':destination,'nonce':'forward-file-123'})
  original=chat.messages(self.store,self.a,self.rid)['itens'][0]['anexos'][0]
  forwarded=chat.messages(self.store,self.b,destination)['itens'][0]['anexos'][0]
  self.assertNotEqual(original['id'],forwarded['id']);self.assertEqual(chat.download(self.store,self.b,forwarded['id'])['conteudo'],raw)
 def test_new_http_routes_auth_csrf_and_controls(self):
  import servidor,threading,json
  from unittest.mock import patch
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  with patch.object(legal,'store',self.store):
   server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)+'/api/juridico/chat/'
   session,key=self.store.login('equipe','senha-forte-123');headers={'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf'],'Content-Type':'application/json'}
   try:
    mid=self.send()
    with self.assertRaises(HTTPError) as err:urlopen(base+'controle')
    self.assertEqual(err.exception.code,401)
    payload=json.dumps({'acao':'reagir','emoji':'👍'}).encode()
    with self.assertRaises(HTTPError) as err:urlopen(Request(base+f'mensagens/{mid}/acao',data=payload,headers={'Cookie':headers['Cookie'],'Content-Type':'application/json'}))
    self.assertEqual(err.exception.code,403)
    with urlopen(Request(base+f'mensagens/{mid}/acao',data=payload,headers=headers)) as r:self.assertEqual(r.status,200)
    with self.assertRaises(HTTPError) as err:urlopen(Request(base+'controle',data=json.dumps({'user_id':self.b['id'],'admin':True,'speaker':True}).encode(),headers=headers))
    self.assertEqual(err.exception.code,403)
   finally:server.shutdown();server.server_close();thread.join(3)
