import json,tempfile,threading,unittest,sys
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico,servidor,eproc
class CollectorHTTP(unittest.TestCase):
 def test_real_start_route_creates_sc_run_and_reports_failure(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=juridico.Store(Path(tmp)/'legal.db');store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
   collector=eproc.Collector(Path(tmp)/'runs')
   with patch.object(juridico,'store',store),patch.object(eproc,'collector',collector):
    server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base='http://127.0.0.1:'+str(server.server_port)
    def req(route,body=None,headers=None):
     request=Request(base+route,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
     with urlopen(request) as response:return json.load(response),response.headers
    try:
     data,headers=req('/api/juridico/entrar',{'login':'admin','senha':'senha-forte-123'})
     auth={'Cookie':headers['Set-Cookie'].split(';')[0],'Origin':base,'X-CSRF-Token':data['csrf']}
     options={'tribunal':'TJSC','teste_sc':True,'invisivel':True,'autenticador_id':None,'modo':'incremental','descobrir_consultas':False,'incluir_prazos_a_encerrar':False,'incluir_agravos_distribuidos':False,'url_prazos_a_encerrar':'','url_agravos_distribuidos':''}
     with patch.object(collector,'run',return_value=None):
      output,_=req('/api/eproc/iniciar',{'opcoes':options},auth)
      self.assertEqual(output['resultado']['atual']['tribunal'],'TJSC')
     collector.thread.join()
     self.assertTrue((Path(tmp)/'runs'/collector.current['id']/'execucao.json').exists())
     options['autenticador_id']=0
     with self.assertRaises(HTTPError) as error:req('/api/eproc/iniciar',{'opcoes':options},auth)
     self.assertIn('Autenticador inválido',json.load(error.exception)['erro'])
    finally:server.shutdown();server.server_close();worker.join()
if __name__=='__main__':unittest.main()
