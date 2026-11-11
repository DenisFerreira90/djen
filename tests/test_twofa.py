from pathlib import Path
import tempfile,unittest,base64,json
from unittest.mock import patch
import juridico as legal
import twofa
SECRET=base64.b32encode(b'12345678901234567890').decode()
def codec(data,decrypt=False):
 if decrypt:
  assert data.startswith(b'test-encrypted:');data=data[15:]
  return bytes(x^90 for x in data)
 return b'test-encrypted:'+bytes(x^90 for x in data)
class TwoFactorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'main.sqlite3')
  self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-teste'},setup=True)
  self.peer=self.store.create_user({'nome':'Outro admin','login':'outro','senha':'senha-forte-teste','role':'administrador'},self.owner)
  self.p=patch('twofa.crypt',side_effect=codec);self.p.start();self.clock=patch('twofa.time.time',return_value=59);self.clock.start()
 def tearDown(self):self.clock.stop();self.p.stop();self.tmp.cleanup()
 def add(self):return twofa.add(self.store,self.owner,{'nome':'Tribunal de teste','conta':'Conta de teste','chave':SECRET,'confirmacao':'287082'})['id']
 def test_cpf_encrypted_masked_and_metadata_owner_only(self):
  key=twofa.add(self.store,self.owner,{'nome':'eproc RS · 1º Grau','conta':'Titular teste','cpf':'529.982.247-25','chave':SECRET,'confirmacao':'287082'})['id']
  row=twofa.codes(self.store,self.owner)['itens'][0];self.assertEqual(row['cpf_mascarado'],'•••.•••.•••-25');self.assertEqual(row['codigo'],'287082')
  self.assertNotIn('52998224725',json.dumps(twofa.settings(self.store,self.owner)));self.assertNotIn(b'52998224725',twofa.vault_path(self.store).read_bytes())
  with self.assertRaises(legal.AppError):twofa.metadata(self.store,self.peer,{'id':key,'nome':'X','conta':'Y','cpf':'52998224725'})
  twofa.metadata(self.store,self.owner,{'id':key,'nome':'eproc SC','conta':'Titular','cpf':''});row=twofa.codes(self.store,self.owner)['itens'][0];self.assertEqual(row['nome'],'eproc SC');self.assertEqual(row['cpf_mascarado'],'•••.•••.•••-25');self.assertEqual(row['codigo'],'287082')
  twofa.metadata(self.store,self.owner,{'id':key,'nome':'eproc SC','conta':'Titular','remover_cpf':True});self.assertEqual(twofa.codes(self.store,self.owner)['itens'][0]['cpf_mascarado'],'Não informado')
  with self.store.connect() as db:audit=' '.join(str(tuple(r)) for r in db.execute('SELECT * FROM audit'))
  self.assertNotIn('529',audit)
 def test_bad_cpf_and_old_vault_migration(self):
  with self.assertRaises(legal.AppError):twofa.cpf_value('111.111.111-11')
  with self.assertRaises(legal.AppError):twofa.cpf_value('52998224726')
  import sqlite3
  path=twofa.vault_path(self.store);path.parent.mkdir(parents=True)
  with sqlite3.connect(path) as db:db.execute('CREATE TABLE tokens(id INTEGER PRIMARY KEY,nome TEXT NOT NULL,conta TEXT NOT NULL,secret BLOB NOT NULL,digits INTEGER NOT NULL,period INTEGER NOT NULL,algorithm TEXT NOT NULL,ativo INTEGER NOT NULL DEFAULT 1,criado TEXT NOT NULL)')
  self.add();self.assertEqual(twofa.codes(self.store,self.owner)['itens'][0]['cpf_mascarado'],'Não informado')
 def test_rfc_vectors(self):
  self.assertEqual(twofa.totp(b'12345678901234567890',59,8),'94287082')
  self.assertEqual(twofa.totp(b'12345678901234567890',59),'287082')
  self.assertEqual(twofa.totp(b'12345678901234567890123456789012',59,8,30,'SHA256'),'46119246')
 def test_parse_and_bad_factors(self):
  self.assertEqual(twofa.parse_secret('otpauth://totp/X?secret='+SECRET+'&digits=8&period=60&algorithm=SHA256')[1:],(8,60,'SHA256'))
  for value in ['123456','otpauth://hotp/X?secret='+SECRET,'invalid!!']:
   with self.assertRaises(legal.AppError):twofa.parse_secret(value)
 def test_owner_only(self):
  with self.assertRaises(legal.AppError):twofa.settings(self.store,self.peer)
  with self.assertRaises(legal.AppError):twofa.grant(self.store,self.peer,{'user_id':self.peer['id'],'autorizado':True})
 def test_grant_revoke(self):
  self.add()
  with self.assertRaises(legal.AppError):twofa.codes(self.store,self.peer)
  twofa.grant(self.store,self.owner,{'user_id':self.peer['id'],'autorizado':True})
  self.assertEqual(twofa.codes(self.store,self.peer)['itens'][0]['codigo'],'287082')
  twofa.grant(self.store,self.owner,{'user_id':self.peer['id'],'autorizado':False})
  with self.assertRaises(legal.AppError):twofa.codes(self.store,self.peer)
 def test_encrypted_separate_storage_and_clean_audit(self):
  self.add();path=twofa.vault_path(self.store);self.assertTrue(path.is_file())
  self.assertNotIn(SECRET.encode(),path.read_bytes());self.assertNotIn(b'12345678901234567890',path.read_bytes())
  self.assertNotIn('secret',json.dumps(twofa.settings(self.store,self.owner)))
  twofa.codes(self.store,self.owner)
  with self.store.connect() as db:audit=' '.join(str(tuple(r)) for r in db.execute('SELECT * FROM audit'))
  self.assertNotIn(SECRET,audit);self.assertNotIn('287082',audit)
 def test_confirmation_and_disable(self):
  with self.assertRaises(legal.AppError):twofa.add(self.store,self.owner,{'nome':'X','conta':'Y','chave':SECRET,'confirmacao':'000000'})
  key=self.add();twofa.disable(self.store,self.owner,key);self.assertEqual(twofa.codes(self.store,self.owner)['itens'],[])
 def test_fail_closed_encryption(self):
  with patch('twofa.crypt',side_effect=legal.AppError('Proteção indisponível')):
   with self.assertRaises(legal.AppError):self.add()
  with twofa.vault(self.store) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM tokens').fetchone()[0],0)
 def test_wrong_windows_account(self):
  self.add()
  with patch('twofa.crypt',side_effect=ValueError('cannot decrypt')):result=twofa.codes(self.store,self.owner)
  self.assertIn('erro',result['itens'][0]);self.assertNotIn('codigo',result['itens'][0])

 def test_other_admin_cannot_take_owner_account_via_password_reset(self):
  twofa.permission(self.store,self.owner)
  with self.assertRaises(legal.AppError) as e:self.store.update_user(self.owner['id'],{'senha':'nova-senha-secreta'},self.peer)
  self.assertEqual(e.exception.code,403)
