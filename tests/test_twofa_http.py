import unittest,tempfile,json,threading
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import servidor,juridico,configurar_piloto_rede,rede_piloto
class TwoFAHTTP(unittest.TestCase):
 def test_private_full_office_pilot_and_permissions(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=juridico.Store(Path(tmp)/'main.sqlite3');owner=store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-teste'},setup=True)
   store.create_user({'nome':'Colega','login':'colega','senha':'senha-forte-teste','role':'administrador'},owner)
   config=Path(tmp)/'net';configurar_piloto_rede.configure(config,'https://escritorio.interno:9443','192.168.1.20',['192.168.1.0/24'],chat_port=8765)
   self.assertIn('127.0.0.1:8765',(config/'Caddyfile').read_text())
   with patch.object(juridico,'store',store):
    server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);server.chat_only=False;server.rede_piloto=rede_piloto.load(config/'piloto-rede.json')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
    headers={'Host':'escritorio.interno:9443','Origin':'https://escritorio.interno:9443','X-Forwarded-Proto':'https','X-Forwarded-For':'192.168.1.50','Content-Type':'application/json'}
    def req(route,data=None,auth=None):
     request=Request(base+'/api/juridico/'+route,headers={**headers,**(auth or {})},data=json.dumps(data).encode() if data is not None else None)
     with urlopen(request) as r:return json.load(r),r.headers
    def login(name):
     d,h=req('entrar',{'login':name,'senha':'senha-forte-teste'});self.assertIn('Secure',h['Set-Cookie']);return {'Cookie':h['Set-Cookie'].split(';')[0],'X-CSRF-Token':d['csrf']}
    try:
     with self.assertRaises(HTTPError) as e:req('2fa/acesso')
     self.assertEqual(e.exception.code,401)
     admin=login('dono');peer=login('colega');self.assertTrue(req('painel',auth=peer)[0]['ok'])
     self.assertFalse(req('2fa/acesso',auth=peer)[0]['resultado']['permitido'])
     for route,data in [('2fa/configuracao',None),('2fa/codigos',{}),('2fa/permissoes',{'user_id':2,'autorizado':True})]:
      with self.assertRaises(HTTPError) as e:req(route,data,peer)
      self.assertEqual(e.exception.code,403)
     with self.assertRaises(HTTPError) as e:req('2fa/permissoes',{'user_id':2,'autorizado':True},{'Cookie':admin['Cookie']})
     self.assertEqual(e.exception.code,403)
     req('2fa/permissoes',{'user_id':2,'autorizado':True},admin)
     data,h=req('2fa/codigos',{},peer);self.assertEqual(data['resultado']['itens'],[]);self.assertIn('no-store',h['Cache-Control'])
     req('2fa/permissoes',{'user_id':2,'autorizado':False},admin)
     with self.assertRaises(HTTPError) as e:req('2fa/codigos',{},peer)
     self.assertEqual(e.exception.code,403)
     for change in [{'X-Forwarded-For':'8.8.8.8'},{'X-Forwarded-Proto':'http'}]:
      with self.assertRaises(HTTPError) as e:req('painel',auth={**peer,**change})
      self.assertEqual(e.exception.code,403)
     server.chat_only=True
     with self.assertRaises(HTTPError) as e:req('2fa/acesso',auth=admin)
     self.assertEqual(e.exception.code,403)
    finally:server.shutdown();server.server_close();thread.join()
