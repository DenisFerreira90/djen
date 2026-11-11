import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import juridico,servidor

class InventoryHTTP(unittest.TestCase):
 def test_inventory_routes_enforce_session_csrf_scopes_and_revocation(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=juridico.Store(Path(tmp)/'app.db');owner=store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-teste'},setup=True)
   user=store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-teste','role':'equipe'},owner)
   with patch.object(juridico,'store',store):
    server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
    def req(path,body=None,auth=None):
     request=Request(base+'/api/juridico/'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(auth or {})})
     with urlopen(request) as response:
      data=json.load(response);return data.get('resultado',data),response.headers
    def login(name):
     data,headers=req('entrar',{'login':name,'senha':'senha-forte-teste'})
     return {'Cookie':headers['Set-Cookie'].split(';')[0],'Origin':base,'X-CSRF-Token':data['csrf']}
    def denied(path,body,auth,code=403):
     with self.assertRaises(HTTPError) as error:req(path,body,auth)
     self.assertEqual(error.exception.code,code)
    try:
     denied('estoque/acesso',None,None,401)
     admin=login('admin');team=login('equipe')
     self.assertEqual(req('estoque/acesso',auth=team)[0]['estoques'],[])
     denied('estoque/permissoes',None,team)
     denied('estoque/permissoes',{'user_id':user['id'],'permissoes':{'ti':'crud','escritorio_limpeza':''}},team)
     denied('estoque/itens?estoque=ti',None,team)
     permission={'user_id':user['id'],'permissoes':{'ti':'ver','escritorio_limpeza':''}}
     denied('estoque/permissoes',permission,{'Cookie':admin['Cookie']})
     req('estoque/permissoes',permission,admin)
     locations=req('estoque/locais?estoque=ti',auth=team)[0]
     body={'estoque':'ti','nome':'Teclado','unidade':'un.','local_id':locations[0]['id'],'quantidade':'2','minimo':'1'}
     denied('estoque/itens',body,team)
     req('estoque/permissoes',{**permission,'permissoes':{'ti':'crud','escritorio_limpeza':''}},admin)
     item=req('estoque/itens',body,team)[0]
     self.assertEqual(req('estoque/itens?estoque=ti',auth=team)[0]['total'],1)
     denied('estoque/itens?estoque=escritorio_limpeza',None,team)
     move={'versao':item['versao'],'tipo':'entrada','quantidade':'1','motivo':'Recebimento'}
     self.assertEqual(req('estoque/itens/'+str(item['id'])+'/movimentar',move,team)[0]['quantidade'],'3')
     denied('estoque/itens/'+str(item['id'])+'/movimentar',move,team,409)
     req('estoque/permissoes',{**permission,'permissoes':{'ti':'','escritorio_limpeza':''}},admin)
     denied('estoque/itens/'+str(item['id'])+'/historico',None,team)
     denied('estoque/locais?estoque=ti',None,team)
     with urlopen(base+'/js/estoque.js') as response:self.assertEqual(response.status,200)
    finally:server.shutdown();server.server_close();thread.join()
