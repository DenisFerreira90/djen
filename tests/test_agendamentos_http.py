import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import juridico,servidor

class SchedulingHTTP(unittest.TestCase):
 def test_admin_grants_creation_by_sector_without_existing_agenda_access(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=juridico.Store(Path(tmp)/'app.db')
   owner=store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True)
   worker=store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},owner)
   with patch.object(juridico,'store',store):
    server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    def request(path,body=None,auth=None):
     req=Request(base+'/api/juridico/'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(auth or {})})
     with urlopen(req) as response:return json.load(response),response.headers
    def login(name):
     data,headers=request('entrar',{'login':name,'senha':'senha-forte-123'})
     return {'Cookie':headers['Set-Cookie'].split(';')[0],'Origin':base,'X-CSRF-Token':data['csrf']}
    try:
     admin=login('dono');user=login('equipe')
     with self.assertRaises(HTTPError) as denied:request('setores/agendamentos',{'user_id':worker['id'],'setores':['civel']},user)
     self.assertEqual(denied.exception.code,403)
     request('setores/agendamentos',{'user_id':worker['id'],'setores':['civel']},admin)
     access,_=request('setores/acesso',auth=user)
     self.assertEqual(access['resultado']['criar_agendas_setores'],['civel'])
     request('calendarios',{'nome':'Entrevistas','setor':'civel'},user)
     with self.assertRaises(HTTPError) as denied:request('calendarios',{'nome':'Contratação','setor':'contratacao'},user)
     self.assertEqual(denied.exception.code,403)
    finally:server.shutdown();server.server_close();thread.join()
