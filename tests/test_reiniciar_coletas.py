import json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
from test_limpar_processos import CleanupTests
import reiniciar_coletas as reset,monitoramento as monitor,mandados,email_alertas,email_resumos,agendamento,juridico as legal

class RestartTests(CleanupTests):
 def populate(self):
  root=Path(self.tmp.name);folder=root/'dados_eproc'/'rodada-antiga';folder.mkdir(parents=True);(folder/'execucao.json').write_text('{}');session=root/'dados_eproc'/'sessao';session.mkdir();(session/'cookie').write_text('preservar')
  with self.store.connect() as db:
   monitor.jobs_schema(db);mandados.schema(db);email_alertas.schema(db);email_resumos.schema(db);agendamento.schema(db)
   db.execute("INSERT INTO monitor_runs VALUES('old','start','end','TJRS','parcial',1)")
   db.execute("INSERT INTO monitor_results VALUES('old','numero','falha','erro antigo','data','[]')")
   db.execute("INSERT INTO monitor_baselines VALUES('numero','{}','data')")
   db.execute("INSERT INTO mandate_watchlist VALUES('numero')")
   db.execute("INSERT INTO monitor_repeat VALUES(1,'{}')")
   db.execute("INSERT INTO collection_schedule VALUES(1,'{}')")
   db.execute("INSERT INTO email_delivery VALUES(1,'data','teste','aceito_smtp',1,'')")
  return root,folder,session
 def test_restart_clears_collections_preserves_other_data_and_backup(self):
  root,folder,session=self.populate()
  result=reset.restart(self.store,self.owner,root)
  self.assertFalse(folder.exists());self.assertTrue((Path(result['pasta_arquivo'])/'rodada-antiga'/'execucao.json').exists());self.assertTrue((session/'cookie').exists())
  with self.store.connect() as db:
   for table in ('monitor_runs','monitor_results','monitor_baselines','mandate_watchlist','monitor_repeat','collection_schedule','imports'):
    self.assertEqual(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0,table)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM email_delivery').fetchone()[0],1)
   self.assertIsNotNone(db.execute('SELECT id FROM records WHERE id=?',(self.manual['id'],)).fetchone())
   self.assertIsNone(db.execute('SELECT id FROM records WHERE id=?',(self.rid,)).fetchone())
  with sqlite3.connect(result['backup']) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_results').fetchone()[0],1)
 def test_failure_restores_archived_files_and_original_data(self):
  root,folder,_=self.populate()
  with patch.object(reset.cleanup,'clean',side_effect=OSError('backup indisponível')):
   with self.assertRaises(OSError):reset.restart(self.store,self.owner,root)
  self.assertTrue((folder/'execucao.json').exists())
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_results').fetchone()[0],1)
 def test_empty_imports_still_clears_old_monitoring_with_backup(self):
  root,_,_=self.populate();reset.restart(self.store,self.owner,root)
  with self.store.connect() as db:db.execute("INSERT INTO monitor_runs VALUES('new','start','end','TJRS','parcial',0)")
  result=reset.restart(self.store,self.owner,root);self.assertTrue(Path(result['backup']).is_file())
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_runs').fetchone()[0],0)
 def test_non_admin_rejected_before_archiving(self):
  root,folder,_=self.populate()
  with self.assertRaises(legal.AppError):reset.restart(self.store,self.other,root)
  self.assertTrue(folder.exists())
del CleanupTests
if __name__=='__main__':unittest.main()
