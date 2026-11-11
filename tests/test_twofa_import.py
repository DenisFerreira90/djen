import sys,tempfile,unittest,json,base64
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,twofa
from test_twofa import codec,SECRET
URI='otpauth://totp/Portal:Teste?issuer=Portal&secret='+SECRET
class ImportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'main.sqlite3');self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-teste'},setup=True);self.peer=self.store.create_user({'nome':'Colega','login':'colega','senha':'senha-forte-teste'},self.owner);self.p=patch('twofa.crypt',side_effect=codec);self.p.start();self.clock=patch('twofa.time.time',return_value=59);self.clock.start()
 def tearDown(self):self.clock.stop();self.p.stop();self.tmp.cleanup()
 def body(self,entries=None,nonce='pedido-importacao-001'):return {'pedido':nonce,'confirmar':True,'entradas':entries or [{'uri':URI,'nome':'eproc RS','conta':'Titular teste','cpf':'52998224725'}]}
 def test_encrypted_import_live_codes_and_masking(self):
  result=twofa.import_batch(self.store,self.owner,self.body());self.assertEqual(result['importadas'],1);row=twofa.codes(self.store,self.owner)['itens'][0];self.assertEqual(row['codigo'],'287082');self.assertEqual(row['nome'],'eproc RS');self.assertEqual(row['cpf_mascarado'],'•••.•••.•••-25')
  with patch('twofa.time.time',return_value=90):self.assertNotEqual(twofa.codes(self.store,self.owner)['itens'][0]['codigo'],'287082')
  raw=twofa.vault_path(self.store).read_bytes();self.assertNotIn(SECRET.encode(),raw);self.assertNotIn(b'52998224725',raw)
  with self.store.connect() as db:audit=json.dumps([dict(r) for r in db.execute('SELECT * FROM audit')])
  self.assertNotIn(SECRET,audit);self.assertNotIn('52998224725',audit);self.assertNotIn('287082',audit)
 def test_idempotent_retry_and_duplicate_seed(self):
  result=twofa.import_batch(self.store,self.owner,self.body());self.assertEqual(twofa.import_batch(self.store,self.owner,self.body()),result)
  other=twofa.import_batch(self.store,self.owner,self.body(nonce='pedido-importacao-002'));self.assertEqual(other['importadas'],0);self.assertEqual(other['duplicadas'],1)
  self.assertEqual(len(twofa.codes(self.store,self.owner)['itens']),1)
 def test_owner_only_even_with_code_permission(self):
  twofa.grant(self.store,self.owner,{'user_id':self.peer['id'],'autorizado':True})
  with self.assertRaises(legal.AppError):twofa.import_batch(self.store,self.peer,self.body())
 def test_bad_entry_rolls_back_whole_batch_and_explicit_confirmation(self):
  with self.assertRaises(legal.AppError):twofa.import_batch(self.store,self.owner,self.body([{'uri':URI},{'uri':'https://example.com/'}]))
  with twofa.vault(self.store) as db:self.assertEqual(db.execute('SELECT count(*) FROM tokens').fetchone()[0],0)
  with self.assertRaises(legal.AppError):twofa.import_batch(self.store,self.owner,{**self.body(),'confirmar':False})
 def test_encryption_failure_no_partial_insert(self):
  with patch('twofa.crypt',side_effect=legal.AppError('Proteção indisponível')):
   with self.assertRaises(legal.AppError):twofa.import_batch(self.store,self.owner,self.body())
  with twofa.vault(self.store) as db:self.assertEqual(db.execute('SELECT count(*) FROM tokens').fetchone()[0],0)
 def test_cap_and_malformed_factor(self):
  with self.assertRaises(legal.AppError):twofa.import_batch(self.store,self.owner,self.body([{'uri':URI}]*101))
  for uri in (URI.replace('/totp/','/hotp/'),URI+'&digits=7',URI+'&algorithm=MD5'):
   with self.assertRaises(legal.AppError):twofa.import_batch(self.store,self.owner,self.body([{'uri':uri}]))
 def test_http_routes_auth_csrf_and_assets(self):
  import servidor,threading
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  with patch.object(legal,'store',self.store):
   server=servidor.DiagnosticHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
   try:
    session,key=self.store.login('dono','senha-forte-teste');headers={'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf'],'Content-Type':'application/json'};endpoint=base+'/api/juridico/2fa/importar';payload=json.dumps(self.body()).encode()
    with self.assertRaises(HTTPError) as e:urlopen(Request(endpoint,data=payload,headers={'Content-Type':'application/json'}))
    self.assertEqual(e.exception.code,401)
    with self.assertRaises(HTTPError) as e:urlopen(Request(endpoint,data=payload,headers={k:v for k,v in headers.items() if k!='X-CSRF-Token'}))
    self.assertEqual(e.exception.code,403)
    with urlopen(Request(endpoint,data=payload,headers=headers)) as response:self.assertEqual(json.load(response)['resultado']['importadas'],1)
    for path in ('/vendor/jsQR.js','/js/twofa-qr.js'):
     with urlopen(base+path) as response:self.assertEqual(response.status,200)
   finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
