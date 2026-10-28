import sys,tempfile,unittest,json,threading
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico,servidor,rede_piloto,configurar_piloto_rede

class NetworkPilotTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=juridico.Store(Path(self.tmp.name)/'db.sqlite')
  self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  self.config=Path(self.tmp.name)/'rede.json';self.config.write_text(json.dumps({'origem':'https://conectaadv.interno:9443','redes_permitidas':['192.168.1.0/24','10.8.0.0/24']}))
 def tearDown(self):self.tmp.cleanup()
 def test_rejects_open_network_and_writes_reviewable_proxy(self):
  self.config.write_text(json.dumps({'origem':'https://conectaadv.interno','redes_permitidas':['0.0.0.0/0']}))
  with self.assertRaises(ValueError):rede_piloto.load(self.config)
  address=configurar_piloto_rede.configure(self.tmp.name,'https://conectaadv.interno:9443','192.168.1.20',['192.168.1.0/24','10.8.0.0/24'])
  text=(Path(self.tmp.name)/'Caddyfile').read_text();self.assertIn('bind 192.168.1.20',text);self.assertIn('tls internal',text);self.assertIn('reverse_proxy 127.0.0.1:8766',text);self.assertIn('header_up X-Forwarded-For {remote_host}',text)
 def test_http_proxy_policy_cookie_and_pilot_isolation(self):
  with patch.object(juridico,'store',self.store):
   server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);server.chat_only=True;server.rede_piloto=rede_piloto.load(self.config)
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
   h={'Host':'conectaadv.interno:9443','X-Forwarded-For':'192.168.1.42','X-Forwarded-Proto':'https','Origin':'https://conectaadv.interno:9443','Content-Type':'application/json'}
   def code(path,headers,data=None):
    try:
     with urlopen(Request(base+path,headers=headers,data=data)) as r:return r.status,r.read(),r.headers
    except HTTPError as e:return e.code,e.read(),e.headers
   try:
    self.assertEqual(code('/api/juridico/sessao',{})[0],403)
    self.assertEqual(code('/api/juridico/sessao',{**h,'X-Forwarded-For':'8.8.8.8'})[0],403)
    self.assertEqual(code('/api/juridico/sessao',{**h,'X-Forwarded-Proto':'http'})[0],403)
    self.assertEqual(code('/api/juridico/sessao',h)[0],200)
    status,raw,headers=code('/api/juridico/entrar',h,json.dumps({'login':'admin','senha':'senha-forte-123'}).encode());self.assertEqual(status,200)
    self.assertIn('Secure',headers['Set-Cookie']);session=json.loads(raw);h['Cookie']=headers['Set-Cookie'].split(';')[0];h['X-CSRF-Token']=session['csrf']
    self.assertEqual(code('/api/juridico/chat/conversas',h)[0],200)
    self.assertEqual(code('/api/juridico/registros',h)[0],403)
    self.assertEqual(code('/api/eproc/status',h)[0],403)
    self.assertEqual(code('/api/buscar?texto=teste',h)[0],403)
    self.assertEqual(code('/api/juridico/chat/conversas',{**h,'Origin':'https://outro.interno'},b'{}')[0],403)
    self.assertEqual(code('/api/juridico/backup',h)[0],200)
   finally:server.shutdown();server.server_close();thread.join(3)
