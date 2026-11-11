import unittest,tempfile,datetime as dt,json,sys
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.storage import AgentDB,Vault,exclusive
from conectacoletor import access
from conectacoletor.runtime import Runtime,detail_scope
from conectacoletor.sync import flush,SyncError,validate_base

def fake_cipher(data,decrypt=False):return data[7:] if decrypt else b'cipher:'+data

def listing(rows):
 return [{'texto':'','tabelas':[{'titulo':'Lista','linhas':[['Processo','Evento e Prazo','Final Prazo'],*[[n,'Intimação',date] for n,date in rows]]}]}]

class AgentTests(unittest.TestCase):
 def test_vault_written_verified_and_private(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Vault(tmp,fake_cipher);p=v.write('TJSC',{'senha':'TEST_ONLY'})
   self.assertEqual(v.read('TJSC'),{'senha':'TEST_ONLY'});self.assertTrue(p.exists())
   with self.assertRaises(ValueError):v.path('../escape')
 def test_save_requires_confirmed_panel_before_creating_file(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Vault(tmp,fake_cipher);context=MagicMock()
   with patch.object(access,'confirmed',return_value=False):
    with self.assertRaises(RuntimeError):access.save(context,v,'TJSC')
   self.assertFalse(v.path('sessao_TJSC').exists())
 def test_save_state_verifies_file_and_restore(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Vault(tmp,fake_cipher);context=MagicMock();context.pages=[]
   state={'cookies':[{'name':'example','value':'TEST_ONLY'}],'origins':[]};context.storage_state.return_value=state
   with patch.object(access,'confirmed',return_value=True):path,summary=access.save(context,v,'TJSC')
   self.assertTrue(path.is_file());self.assertEqual(summary,{'cookies':1,'origens':0})
   target=MagicMock();self.assertTrue(access.restore(target,v,'TJSC'))
   target.set_storage_state.assert_called_once_with(storage_state=state)
 def test_empty_state_is_not_saved(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Vault(tmp,fake_cipher);context=MagicMock();context.storage_state.return_value={'cookies':[]}
   with patch.object(access,'confirmed',return_value=True):
    with self.assertRaises(RuntimeError):access.save(context,v,'TJSC')
   self.assertFalse(v.path('sessao_TJSC').exists())
 def test_durable_jobs_and_idempotent_outbox(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db';a=AgentDB(path);job=a.new_job('TJSC',{'dias':20});a.update(job,'executando','run')
   a.enqueue('one',{'x':1});a.enqueue('one',{'x':1});a.set('pausado',True)
   b=AgentDB(path);self.assertEqual(len(b.pending()),1);self.assertTrue(b.get('pausado'));self.assertEqual(b.recover(),[{'run_id':'run','court':'TJSC'}]);self.assertEqual(b.job(job)['state'],'interrompido')
   b.delivered('one');self.assertEqual(b.pending(),[])
 def test_twenty_day_window_moves_and_keeps_undated_overdue(self):
  nums=['5000001-00.2026.8.24.0001','5000002-00.2026.8.24.0001','5000003-00.2026.8.24.0001','5000004-00.2026.8.24.0001']
  nums += [f'{n:07d}-00.2026.8.24.0001' for n in range(6000000,6000497)]
  pages=listing([(nums[0],'01/11/2026'),(nums[1],'25/11/2026'),(nums[2],'26/11/2026'),(nums[3],'')])
  selected,deferred,date=detail_scope(nums,pages,{'dias':20},dt.date(2026,11,5));self.assertEqual(date,'2026-11-25');self.assertEqual(selected,[nums[0],nums[1],*nums[3:]]);self.assertEqual(deferred,1)
  selected,deferred,date=detail_scope(nums,pages,{'dias':20},dt.date(2026,11,6));self.assertEqual(selected,nums);self.assertEqual(deferred,0)
 def test_rolling_window_only_filters_above_500_distinct_cases(self):
  nums=[f'{n:07d}-00.2026.8.24.0001' for n in range(6000000,6000501)]
  pages=listing([(nums[0],'30/12/2026')])
  self.assertEqual(detail_scope(nums[:500],pages,{'dias':20},dt.date(2026,11,5))[0],nums[:500])
  self.assertNotIn(nums[0],detail_scope(nums,pages,{'dias':20},dt.date(2026,11,5))[0])
  self.assertEqual(detail_scope([nums[0]]*501,pages,{'dias':20},dt.date(2026,11,5))[1],0)
 def test_fixed_cutoff_and_invalid_scope(self):
  nums=['5000001-00.2026.8.24.0001'];pages=listing([(nums[0],'25/11/2026')])
  self.assertEqual(detail_scope(nums,pages,{'ate':'2026-11-24'})[0],[])
  with self.assertRaises(ValueError):detail_scope(nums,pages,{'dias':0})
 def test_profile_lock_blocks_simultaneous_access(self):
  with tempfile.TemporaryDirectory() as tmp:
   with exclusive(Path(tmp)/'lock'):
    with self.assertRaises(RuntimeError):
     with exclusive(Path(tmp)/'lock'):pass
 def test_delivery_requires_confirmation_and_retains_offline_payload(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=AgentDB(Path(tmp)/'db');vault=Vault(Path(tmp)/'vault',fake_cipher);vault.write('destino',{'url':'http://localhost:8765','usuario':'u','senha':'p'});db.enqueue('one',{'x':1})
   with patch('conectacoletor.sync.Client') as client:
    client.return_value.send.side_effect=SyncError('Offline')
    self.assertEqual(flush(db,vault)['enviados'],0)
   self.assertEqual(len(db.pending()),1)
   with patch('conectacoletor.sync.Client') as client:
    client.return_value.send.return_value={'criados':1}
    self.assertEqual(flush(db,vault)['enviados'],1)
   self.assertEqual(db.pending(),[])
 def test_denied_auth_pauses_sync(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=AgentDB(Path(tmp)/'db');vault=Vault(Path(tmp)/'vault',fake_cipher);vault.write('destino',{'url':'http://localhost:8765','usuario':'u','senha':'p'});db.enqueue('one',{})
   with patch('conectacoletor.sync.Client') as client:
    client.return_value.send.side_effect=SyncError('Denied',True);flush(db,vault)
   self.assertTrue(db.get('sync_bloqueada'));self.assertEqual(len(db.pending()),1)
 def test_sync_refuses_remote_plaintext_and_embedded_credentials(self):
  for url in ('http://example.com','https://u:p@example.com','https://example.com?x=y'):
   with self.assertRaises(ValueError):validate_base(url)
  self.assertEqual(validate_base('http://localhost:8765/'),'http://localhost:8765')
 def test_real_local_database_and_checkpoint_capture_survive_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Runtime(tmp,Vault(Path(tmp)/'vault',fake_cipher));c=r.collector({'dias':20})
   with patch('eproc.threading.Thread'):c.start(r.actor,{'tribunal':'TJSC','teste_sc':True,'invisivel':True})
   record={'processo':'5000001-00.2026.8.24.0001','detalhes':None,'gravado_no_sistema':False,'situacao':'falha_na_leitura'}
   c.save_checkpoint([record],[]);c.save_checkpoint([record],[])
   self.assertEqual(len(r.db.pending()),1)
   r.recover_run(c.current['id'],'TJSC');self.assertEqual(len(r.db.pending()),1)
   self.assertEqual(r.db.pending()[0]['id'].count(record['processo']),1)
if __name__=='__main__':unittest.main()
