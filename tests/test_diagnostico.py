import sys,tempfile,unittest,json,threading,sqlite3
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import diagnostico as diag,juridico as legal
class DiagnosticTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.patch=patch.object(diag,'PATH',self.base/'diagnostic'/'diag.sqlite3');self.patch.start()
  self.store=legal.Store(self.base/'legal.sqlite3');self.owner=self.store.create_user({'nome':'Proprietário','login':'dono','senha':'senha-forte-123'},setup=True)
  self.a=self.store.create_user({'nome':'TI','login':'tec','senha':'senha-forte-123','role':'equipe'},self.owner)
  self.admin=self.store.create_user({'nome':'Outro admin','login':'admin','senha':'senha-forte-123','role':'administrador'},self.owner)
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def fault(self):
  try:raise RuntimeError('senha=muito-secreta TOKEN-SEGREDO-1234567890 cliente@email.com 123.456.789-00')
  except Exception as e:return diag.capture(e,'juridico','POST /api/juridico/registros/123?token=secreto',self.owner['id'])
 def test_redaction_and_trace_without_source_locals_or_exception_message(self):
  code=self.fault();self.assertTrue(code['registrado']);data=diag.faults(self.store,self.owner,code=code['codigo']);raw=json.dumps(data)
  for secret in ('muito-secreta','TOKEN-SEGREDO','cliente@email.com','123.456.789','token=secreto','raise RuntimeError'):self.assertNotIn(secret,raw)
  self.assertIn('test_diagnostico.py',raw);self.assertIn('RuntimeError',raw);self.assertIn(':id',data['operation']);self.assertTrue(data['technical']['excecoes'][0]['frames'])
  disk=diag.PATH.read_bytes()
  for secret in (b'muito-secreta',b'TOKEN-SEGREDO',b'cliente@email.com'):self.assertNotIn(secret,disk)
 def test_grouping_counts_resolution_reopens_and_filters(self):
  a=self.fault();b=self.fault();self.assertEqual(a['codigo'],b['codigo']);self.assertEqual(diag.faults(self.store,self.owner)['itens'][0]['total'],2)
  diag.faults(self.store,self.owner,code=a['codigo'],body={'situacao':'resolvido','responsavel_id':self.a['id'],'observacoes':'Contatar cliente@email.com CPF 123.456.789-00'})
  self.fault();data=diag.faults(self.store,self.owner,code=a['codigo']);self.assertEqual(data['state'],'novo');self.assertNotIn('cliente@email.com',data['notes'])
  self.assertEqual(diag.faults(self.store,self.owner,{'modulo':'chat'})['itens'],[])
 def test_owner_grants_only_and_revoke_immediate(self):
  self.assertFalse(diag.permission(self.store,self.admin)['permitido'])
  with self.assertRaises(legal.AppError):diag.grants(self.store,self.admin,{'user_id':self.a['id'],'permitido':True})
  with self.assertRaises(legal.AppError):diag.faults(self.store,self.a)
  diag.grants(self.store,self.owner,{'user_id':self.a['id'],'permitido':True});self.assertTrue(diag.permission(self.store,self.a)['permitido']);diag.faults(self.store,self.a)
  diag.grants(self.store,self.owner,{'user_id':self.a['id'],'permitido':False})
  with self.assertRaises(legal.AppError):diag.faults(self.store,self.a)
 def test_broken_diagnostic_storage_never_raises_and_reports_degraded(self):
  with patch.object(diag,'PATH',self.base):
   result=self.fault();self.assertFalse(result['registrado']);self.assertTrue(result['codigo'].startswith('ERR-'))
   status=diag.health(self.store,self.owner);self.assertEqual(status['servicos'][-1]['estado'],'indisponivel')
  self.assertEqual(self.store.dashboard()['contagens']['processos'],0)
 def test_locked_storage_fails_fast_and_main_bank_survives(self):
  with diag.connect() as db:db.execute('BEGIN EXCLUSIVE');result=self.fault();self.assertFalse(result['registrado'])
  self.assertIsInstance(self.store.dashboard(),dict)
 def test_retention_and_upper_bound(self):
  self.fault()
  with diag.connect() as db:db.execute("UPDATE faults SET last_at='2000-01-01T00:00:00+00:00'")
  self.fault()
  with diag.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM faults').fetchone()[0],1)
 def test_mask_nested_secrets_and_identifiers(self):
  value=diag.mask({'password':'abc','contexto':{'token':'abc','link':'https://site/a?key=abc'},'email':'nome@email.com','observacao':'Authorization: Bearer abc123'})
  data=json.dumps(value);self.assertNotIn('abc',data);self.assertNotIn('nome@email.com',data);self.assertNotIn('https://',data)
 def test_health_truthful_and_backup_timestamp(self):
  data=diag.health(self.store,self.owner,chat_independent=True);self.assertEqual(data['servicos'][0]['servico'],'chat');self.assertEqual(data['servicos'][0]['estado'],'acessivel');self.assertTrue(data['disco_livre_bytes']>0)
  diag.backup_confirmed('banco_chat');self.assertEqual(diag.health(self.store,self.owner,True)['backups_confirmados_nesta_versao'][0]['service'],'banco_chat')
 def test_http_exception_public_code_no_trace_and_details_authorized(self):
  import servidor
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  with patch.object(legal,'store',self.store):
   server=servidor.DiagnosticHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
   def headers(login):
    session,key=self.store.login(login,'senha-forte-123');return {'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf'],'Content-Type':'application/json'}
   try:
    owner=headers('dono');other=headers('admin')
    with patch.object(self.store,'dashboard',side_effect=RuntimeError('PASSWORD-SUPERSECRETO')):
     with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/juridico/painel',headers=owner))
     self.assertEqual(err.exception.code,500);public=json.load(err.exception);code=public['codigo_erro'];self.assertNotIn('trace',json.dumps(public));self.assertNotIn('PASSWORD',json.dumps(public))
    endpoint=base+'/api/juridico/saude-sistema/erros/'+code
    with self.assertRaises(HTTPError) as err:urlopen(endpoint)
    self.assertEqual(err.exception.code,401)
    with self.assertRaises(HTTPError) as err:urlopen(Request(endpoint,headers=other))
    self.assertEqual(err.exception.code,403)
    with urlopen(Request(endpoint,headers=owner)) as response:self.assertIn('technical',json.load(response)['resultado'])
    with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/juridico/saude-sistema/permissoes',data=b'{"user_id":2,"permitido":true}',headers={k:v for k,v in owner.items() if k!='X-CSRF-Token'}))
    self.assertEqual(err.exception.code,403)
    with urlopen(base+'/js/diagnostico.js') as response:self.assertEqual(response.status,200)
    server.chat_only=True
    with urlopen(Request(base+'/api/juridico/saude-sistema/saude',headers=owner)) as response:self.assertEqual(response.status,200)
    with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/juridico/painel',headers=owner))
    self.assertEqual(err.exception.code,403)
    server.chat_only=False
    with patch.object(diag,'PATH',self.base),patch.object(self.store,'dashboard',side_effect=RuntimeError('SEGREDO-NUNCA-EXIBIDO')):
     with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/juridico/painel',headers=owner))
     result=json.load(err.exception);self.assertFalse(result['registro_tecnico']);self.assertNotIn('SEGREDO',json.dumps(result))
   finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
