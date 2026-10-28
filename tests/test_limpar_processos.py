import sys,tempfile,unittest,json,sqlite3
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,gestao,chat_interno,limpar_processos as cleanup
N='5001234-12.2025.8.21.0001'
class CleanupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'dados_juridico'/'juridico.sqlite3')
  self.owner=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  self.other=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123'},self.owner)
  self.manual=self.store.save('processos',{'dados':{'numero':'5001235-12.2025.8.21.0001','titulo':'Manual'}},self.owner)
  self.store.import_corpus({'execucao':{'id':'test-cleanup'},'paginas_da_lista':[{'tabelas':[{'titulo':'Lista','linhas':[['Processo'],[N]]}]}],'processos':[]},self.owner)
  with self.store.connect() as db:
   self.rid=db.execute("SELECT id FROM records WHERE kind='processos' AND json_extract(data,'$.numero')=?",(N,)).fetchone()[0]
   self.imported=gestao.insert(self.store,db,'partes',{'nome':'Parte importada','origem':'eproc'},self.owner,self.rid,'parte:eproc:cleanup')[0]
  self.task=self.store.save('tarefas',{'processo_id':self.rid,'dados':{'titulo':'Trabalho manual','status':'a_fazer'}},self.owner)
  self.finance=self.store.save('financeiro',{'processo_id':self.rid,'dados':{'titulo':'Honorário','natureza':'receber','valor_centavos':10000,'status':'pendente'}},self.owner)
  room=chat_interno.create(self.store,self.owner,{'tipo':'direta','membros':[self.other['id']]})['id'];chat_interno.send(self.store,self.owner,room,{'texto':'Preservar histórico','nonce':'cleanup-chat-123'});self.room=room
 def tearDown(self):self.tmp.cleanup()
 def test_preview_no_mutation_and_scoped_execution_with_backup(self):
  before=self.store.path.read_bytes();summary=cleanup.preview(self.store.path);self.assertEqual(summary['processos'],[self.rid]);self.assertEqual(before,self.store.path.read_bytes())
  result=cleanup.clean(self.store,self.owner);self.assertEqual(result['removidos'],1)
  with self.store.connect() as db:
   self.assertIsNone(db.execute('SELECT id FROM records WHERE id=?',(self.rid,)).fetchone());self.assertIsNone(db.execute('SELECT id FROM records WHERE id=?',(self.imported,)).fetchone())
   self.assertIsNotNone(db.execute('SELECT id FROM records WHERE id=?',(self.manual['id'],)).fetchone())
   for rid in (self.task['id'],self.finance['id']):
    row=db.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone();self.assertIsNone(row['case_id']);self.assertIn(N,json.loads(row['data'])['observacoes'])
   self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],2);self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
  self.assertEqual(chat_interno.messages(self.store,self.owner,self.room)['itens'][0]['texto'],'Preservar histórico')
  with sqlite3.connect(result['backup']) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM records WHERE id=?',(self.rid,)).fetchone()[0],1)
 def test_backup_failure_keeps_records(self):
  original=Path.mkdir
  def mkdir(path,*args,**kw):
   if path.name=='backups':raise OSError('Sem espaço')
   return original(path,*args,**kw)
  with patch.object(Path,'mkdir',mkdir):
   with self.assertRaises(OSError):cleanup.clean(self.store,self.owner)
  self.assertIn(self.rid,cleanup.preview(self.store.path)['processos'])
 def test_manual_edit_to_imported_child_is_preserved(self):
  self.store.save('partes',{'versao':1,'processo_id':self.rid,'dados':{'nome':'Corrigido manualmente','papel':'autor'}},self.owner,self.imported)
  cleanup.clean(self.store,self.owner)
  with self.store.connect() as db:
   row=db.execute('SELECT * FROM records WHERE id=?',(self.imported,)).fetchone();self.assertIsNone(row['case_id']);self.assertEqual(json.loads(row['data'])['nome'],'Corrigido manualmente')
 def test_unknown_reference_causes_full_rollback(self):
  with self.store.connect() as db:
   db.execute('CREATE TABLE unknown_link(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES records(id))');db.execute('INSERT INTO unknown_link VALUES(1,?)',(self.rid,))
  with self.assertRaises((sqlite3.IntegrityError,ValueError)):cleanup.clean(self.store,self.owner)
  self.assertIn(self.rid,cleanup.preview(self.store.path)['processos'])
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT case_id FROM records WHERE id=?',(self.task['id'],)).fetchone()[0],self.rid)
 def test_non_admin_rejected_and_second_run_noop(self):
  with self.assertRaises(legal.AppError):cleanup.clean(self.store,self.other)
  cleanup.clean(self.store,self.owner);again=cleanup.clean(self.store,self.owner);self.assertEqual(again['removidos'],0);self.assertIsNone(again['backup'])

 def test_reused_identifier_does_not_target_new_manual_case(self):
  cleanup.clean(self.store,self.owner)
  with self.store.connect() as db:
   data={'numero':N,'titulo':'Novo cadastro manual'}
   db.execute('INSERT INTO records(id,kind,data,criado,atualizado,criado_por,atualizado_por) VALUES(?,?,?,?,?,?,?)',(self.rid,'processos',legal.dumps(data),legal.now(),legal.now(),self.owner['id'],self.owner['id']))
   self.store.audit(db,self.owner,'criar','processos',self.rid,after=data)
  self.assertNotIn(self.rid,cleanup.preview(self.store.path)['processos'])
