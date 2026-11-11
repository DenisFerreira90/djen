import io,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError
import servidor,INICIAR_VERIFICADO as startup

class AssetDeliveryTests(unittest.TestCase):
 def setUp(self):
  self.server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.base='http://127.0.0.1:'+str(self.server.server_port)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
 def test_javascript_mime_does_not_depend_on_operating_system_registry(self):
  with patch.object(servidor.mimetypes,'guess_type',return_value=('application/json',None)):
   with urlopen(self.base+'/js/estoque.js?v=63') as response:
    self.assertEqual(response.status,200);self.assertEqual(response.headers['Content-Type'],'text/javascript; charset=utf-8')
    self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff');self.assertIn(b'window.Estoque=',response.read())
 def test_missing_javascript_is_a_real_404_not_disguised_as_a_script(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(servidor,'ROOT',Path(tmp)):
   with self.assertRaises(HTTPError) as error:urlopen(self.base+'/js/estoque.js?v=63')
   self.assertEqual(error.exception.code,404);self.assertTrue(error.exception.headers['Content-Type'].startswith('application/json'))
   self.assertEqual(startup.running_server(self.base)['estado'],'arquivo_ausente')
 def test_active_server_identity_and_old_process_are_distinguished(self):
  self.assertEqual(startup.running_server(self.base)['estado'],'pronto')
  with patch.object(servidor,'APP_VERSION',str(int(startup.EXPECTED_VERSION)-1)):
   self.assertEqual(startup.running_server(self.base)['estado'],'antigo')
 def test_local_installation_check_detects_incomplete_extraction(self):
  self.assertEqual(startup.installation_errors(),[])
  with tempfile.TemporaryDirectory() as tmp:
   errors=startup.installation_errors(Path(tmp));self.assertEqual(len(errors),7)
   self.assertTrue(any('js/estoque.js' in error for error in errors))
 def test_json_200_is_not_accepted_as_javascript(self):
  class Response(io.BytesIO):
   def __init__(self,body,ctype):super().__init__(body);self.headers={'Content-Type':ctype};self.status=200
  responses=iter([Response(json.dumps({'versao_aplicacao':startup.EXPECTED_VERSION}).encode(),'application/json'),Response(b'{"erro":"arquivo indisponivel"}','application/json')])
  self.assertEqual(startup.running_server(self.base,lambda *a,**k:next(responses))['estado'],'arquivo_invalido')
 def test_nested_djen_directory_is_rejected_before_starting_empty_database(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'djen'/'djen';root.mkdir(parents=True)
   self.assertTrue(any('djen dentro de djen' in error for error in startup.installation_errors(root)))
