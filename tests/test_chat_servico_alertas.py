import sys,tempfile,unittest,subprocess,threading,json,socket,time,sqlite3
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,chat_interno as chat,chat_recursos as ext,chat_alertas as alerts,chat_servico

class SeparateChatTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.store=legal.Store(self.path/'juridico.sqlite3')
  self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True)
  self.a=self.store.create_user({'nome':'Ana','login':'ana','senha':'senha-forte-123'},self.owner)
  self.b=self.store.create_user({'nome':'Bruno','login':'bruno','senha':'senha-forte-123'},self.owner)
  self.rid=chat.create(self.store,self.owner,{'tipo':'grupo','titulo':'Setor','membros':[self.a['id']]})['id'];self.n=0
 def tearDown(self):self.tmp.cleanup()
 def send(self,actor=None,rid=None):
  self.n+=1;return chat.send(self.store,actor or self.owner,rid or self.rid,{'texto':'Informação sigilosa','nonce':'test-nonce-'+str(self.n)})['id']
 def test_migration_preserves_chat_users_and_excludes_cases_sessions(self):
  self.send();self.store.login('dono','senha-forte-123')
  self.store.save('processos',{'dados':{'numero':'5004310-40.2026.8.21.0018','titulo':'Não deve ser copiado'}},self.owner)
  destination=self.path/'chat.sqlite3';chat_servico.migrate(self.store.path,destination);other=legal.Store(destination)
  self.assertEqual(chat.messages(other,self.a,self.rid)['itens'][0]['texto'],'Informação sigilosa')
  with other.connect() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0],0);self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)
  other.login('dono','senha-forte-123');chat.send(other,self.a,self.rid,{'texto':'Só no chat separado','nonce':'separate-nonce-1'})
  self.assertEqual(len(chat.messages(self.store,self.a,self.rid)['itens']),1)
  with self.assertRaises(ValueError):chat_servico.migrate(self.store.path,destination)
 def test_feed_access_muted_read_self_and_cursor(self):
  cursor=alerts.feed(self.store,self.a)['cursor'];self.send();other=chat.create(self.store,self.owner,{'tipo':'direta','membros':[self.b['id']]})['id'];self.send(rid=other)
  feed=alerts.feed(self.store,self.a,cursor);self.assertEqual(len(feed['itens']),1);self.assertNotIn('texto',feed['itens'][0]);self.assertEqual(feed['itens'][0]['room_id'],self.rid)
  self.assertEqual(alerts.feed(self.store,self.a,feed['cursor'])['itens'],[])
  ext.mute(self.store,self.a,self.rid,{'silenciado':True});self.send();self.assertEqual(alerts.feed(self.store,self.a,feed['cursor'])['itens'],[])
  ext.mute(self.store,self.a,self.rid,{'silenciado':False});cursor=alerts.feed(self.store,self.a)['cursor'];mid=self.send();chat.read(self.store,self.a,self.rid,mid)
  self.assertEqual(alerts.feed(self.store,self.a,cursor)['itens'],[])
  cursor=alerts.feed(self.store,self.a)['cursor'];self.send(self.a);self.assertEqual(alerts.feed(self.store,self.a,cursor)['itens'],[])
  self.assertLess(alerts.feed(self.store,self.a,999999)['cursor'],999999)
 def test_feed_pagination_does_not_drop_burst(self):
  cursor=alerts.feed(self.store,self.a)['cursor']
  with self.store.connect() as db:
   db.executemany('INSERT INTO chat_messages(room_id,sender_id,texto,criado,nonce) VALUES(?,?,?,?,?)',[(self.rid,self.owner['id'],'Sigiloso',legal.now(),'burst-'+str(n)) for n in range(205)])
  one=alerts.feed(self.store,self.a,cursor);two=alerts.feed(self.store,self.a,one['cursor']);three=alerts.feed(self.store,self.a,two['cursor'])
  self.assertTrue(one['tem_mais']);self.assertTrue(two['tem_mais']);self.assertFalse(three['tem_mais']);self.assertEqual(sum(len(x['itens']) for x in (one,two,three)),205)
 def test_independent_http_process_survives_legal_server_stop(self):
  destination=self.path/'chat.sqlite3';chat_servico.migrate(self.store.path,destination)
  root=Path(__file__).resolve().parents[1];wrapper=self.path/'run_server.py';wrapper.write_text('''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import juridico,chat_servico,servidor
juridico.store=juridico.Store(Path(sys.argv[2]))
chat_servico.CHAT_PATH=Path(sys.argv[3])
mode=sys.argv[4];port=sys.argv[5]
sys.argv=['servidor.py','--porta',port,'--sem-navegador']+(['--chat-independente'] if mode=='chat' else [])
servidor.main()
''')
  def port():
   with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
  cp,lp=port(),port();processes=[]
  def start(mode,p):
   proc=subprocess.Popen([sys.executable,str(wrapper),str(root),str(self.store.path),str(destination),mode,str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);processes.append(proc)
   for _ in range(80):
    if proc.poll() is not None:self.fail('Servidor encerrou antes de abrir a porta.')
    try:
     with urlopen('http://127.0.0.1:'+str(p)+'/api/juridico/sessao',timeout=.3) as r:return proc,json.load(r)
    except OSError:time.sleep(.05)
   self.fail('Servidor não ficou disponível.')
  try:
   cp_proc,cs=start('chat',cp);lp_proc,ls=start('legal',lp);self.assertTrue(cs['modo_chat']);self.assertTrue(ls['chat_externo'])
   base='http://127.0.0.1:'+str(cp)
   req=Request(base+'/api/juridico/entrar',data=json.dumps({'login':'ana','senha':'senha-forte-123'}).encode(),headers={'Content-Type':'application/json'})
   with urlopen(req,timeout=5) as r:
    cookie=r.headers['Set-Cookie'].split(';')[0];session=json.load(r)
   self.assertTrue(cookie.startswith('conectaadv_chat_session='))
   legal_base='http://127.0.0.1:'+str(lp)
   with urlopen(Request(legal_base+'/api/juridico/entrar',data=json.dumps({'login':'ana','senha':'senha-forte-123'}).encode(),headers={'Content-Type':'application/json'}),timeout=5) as r:legal_cookie=r.headers['Set-Cookie'].split(';')[0]
   self.assertTrue(legal_cookie.startswith('juridico_session='))
   with self.assertRaises(HTTPError) as err:urlopen(Request(legal_base+'/api/juridico/chat/conversas',headers={'Cookie':legal_cookie}),timeout=5)
   self.assertEqual(err.exception.code,409)
   with urlopen(Request(base+'/api/juridico/chat/alertas',headers={'Cookie':cookie}),timeout=5) as r:self.assertIn('cursor',json.load(r)['resultado'])
   with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/eproc/status',headers={'Cookie':cookie}),timeout=5)
   self.assertEqual(err.exception.code,403)
   lp_proc.terminate();lp_proc.wait(timeout=5)
   req=Request(base+f'/api/juridico/chat/conversas/{self.rid}/mensagens',data=json.dumps({'texto':'Eproc parado, chat funcionando','nonce':'independent-nonce-123'}).encode(),headers={'Content-Type':'application/json','Cookie':cookie,'X-CSRF-Token':session['csrf']})
   with urlopen(req,timeout=5) as r:self.assertEqual(r.status,200)
   with urlopen(Request(base+f'/api/juridico/chat/conversas/{self.rid}/mensagens',headers={'Cookie':cookie}),timeout=5) as r:self.assertEqual(json.load(r)['resultado']['itens'][-1]['texto'],'Eproc parado, chat funcionando')
   with urlopen(Request(base+'/img/chat-icon.svg'),timeout=5) as r:self.assertEqual(r.status,200)
  finally:
   for proc in processes:
    if proc.poll() is None:proc.terminate()
    try:proc.wait(timeout=5)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
