import sys,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico,servidor,eproc,diagnostico,proprietario
class OwnerAreaHTTP(unittest.TestCase):
 def test_owner_identity_survives_new_admin_and_direct_requests_are_denied(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=juridico.Store(Path(tmp)/'app.db');owner=store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True)
   store.create_user({'nome':'Outro admin','login':'admin2','senha':'senha-forte-123','role':'administrador'},owner)
   store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},owner)
   collector=eproc.Collector(Path(tmp)/'runs')
   with patch.object(juridico,'store',store),patch.object(eproc,'collector',collector):
    server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base='http://127.0.0.1:'+str(server.server_port)
    def req(path,body=None,auth=None):
     r=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(auth or {})})
     with urlopen(r) as response:return json.load(response),response.headers
    def login(name):
     data,headers=req('/api/juridico/entrar',{'login':name,'senha':'senha-forte-123'})
     return {'Cookie':headers['Set-Cookie'].split(';')[0],'Origin':base,'X-CSRF-Token':data['csrf']}
    try:
     for name in ('dono','admin2','equipe'):
      auth=login(name);session,_=req('/api/juridico/sessao',auth=auth);self.assertEqual(session['area_tecnica'],name=='dono')
      req('/api/juridico/registros?tipo=processos',auth=auth)
      if name=='dono':
       req('/api/eproc/status',auth=auth);req('/api/juridico/conectores',auth=auth)
      else:
       for path,body in [('/api/eproc/status',None),('/api/eproc/exportar?id=x',None),('/api/eproc/iniciar',{'opcoes':{}}),('/api/juridico/conectores',None),('/api/juridico/fila-coleta',None),('/api/juridico/importar',{}),('/api/juridico/backup',None),('/api/juridico/saude-sistema/saude',None),('/api/juridico/processos/5001234-12.2026.8.24.0001/dados',None),('/api/juridico/evidencias/1',None),('/api/juridico/diagnostico/1',None),('/api/juridico/reprocessar/1',{}),('/api/juridico/monitoramento/procurar',{}),('/api/juridico/servico-coleta',{}),('/api/juridico/agendamento',None)]:
        with self.assertRaises(HTTPError) as denied:req(path,body,auth)
        self.assertEqual(denied.exception.code,403,path)
       with patch.object(diagnostico,'permission',return_value={'permitido':True,'proprietario':False}):
        rights,_=req('/api/juridico/saude-sistema/acesso',auth=auth)
        self.assertFalse(rights['resultado']['permitido'])
     self.assertEqual(proprietario.access(store,owner),{'proprietario':True,'area_tecnica':True})
    finally:server.shutdown();server.server_close();worker.join()
if __name__=='__main__':unittest.main()
