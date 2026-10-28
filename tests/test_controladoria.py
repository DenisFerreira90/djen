import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest,tempfile,json,threading
from unittest.mock import patch
import juridico as legal
import controladoria as ctl
from test_eproc_estruturado import sample,N

class TestControladoria(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'base.db')
  self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  self.queue=ctl.Queue()
 def tearDown(self):
  if self.queue.thread:self.queue.thread.join(10)
  self.tmp.cleanup()
 def case(self,number=N,source=True):
  c=self.store.save('processos',{'dados':{'numero':number,'titulo':'Processo importado do eproc','observacoes':'Preservar'}},self.actor)
  if source:
   with self.store.connect() as db:
    db.execute('INSERT OR IGNORE INTO imports VALUES(?,?,?,?)',('legado',legal.now(),self.actor['id'],'{}'))
    db.execute('INSERT INTO evidence(import_id,case_id,source,payload) VALUES(?,?,?,?)',('legado',c['id'],'detalhes:0',legal.dumps(sample()['processos'][0]['detalhes'])))
  return c
 def test_batch_without_network_and_automatic_once(self):
  c=self.case();self.case('5004310-40.2026.8.21.0018',False)
  with patch('urllib.request.urlopen',side_effect=AssertionError('Sem rede')):
   self.queue.start(self.store,self.actor,True);self.queue.thread.join(10)
  result=self.queue.status(self.store)['execucao']
  self.assertEqual(result['estado'],'concluido');self.assertEqual(result['contagens'],{'preenchido':1,'sem_origem':1})
  d=self.store.detail(c['id'])['dados'];self.assertEqual(d['orgao'],'Vara de Teste');self.assertEqual(d['observacoes'],'Preservar')
  old=result['id'];self.queue.start(self.store,self.actor,True)
  self.assertEqual(self.queue.status(self.store)['execucao']['id'],old)
 def test_reader_denied(self):
  with self.assertRaises(legal.AppError):self.queue.start(self.store,{**self.actor,'role':'leitor'})
 def test_restart_resumes_persisted_pending_item(self):
  c=self.case()
  with self.store.connect() as db:
   ctl.schema(db);db.execute('INSERT INTO control_jobs VALUES(?,?,?,?,?,?)',('restart',legal.now(),legal.now(),'executando',self.actor['id'],self.actor['nome']))
   db.execute('INSERT INTO control_items(job_id,case_id,numero) VALUES(?,?,?)',('restart',c['id'],N))
  self.assertEqual(self.queue.status(self.store)['execucao']['estado'],'interrompido')
  self.queue.start(self.store,self.actor,True);self.queue.thread.join(10)
  self.assertEqual(self.queue.status(self.store)['execucao']['estado'],'concluido')
 def test_pause_preserves_remaining_items(self):
  self.case();self.case('5004310-40.2026.8.21.0018',False)
  entered=threading.Event();release=threading.Event()
  original=ctl.reprocessamento.repair
  def blocked(*args):entered.set();release.wait(5);return original(*args)
  with patch.object(ctl.reprocessamento,'repair',side_effect=blocked):
   self.queue.start(self.store,self.actor);self.assertTrue(entered.wait(5))
   self.queue.pause(self.store,self.actor);release.set();self.queue.thread.join(10)
  status=self.queue.status(self.store)['execucao'];self.assertEqual(status['estado'],'pausado');self.assertEqual(status['contagens']['pendente'],1)
  self.queue.start(self.store,self.actor,True);self.assertEqual(self.queue.status(self.store)['execucao']['estado'],'pausado')
  self.queue.start(self.store,self.actor);self.queue.thread.join(10)
  self.assertEqual(self.queue.status(self.store)['execucao']['estado'],'concluido')
 def test_report_excludes_historical_other_parties_and_separates_internal(self):
  c=self.case(N,False)
  self.store.save('prazos',{'processo_id':c['id'],'dados':{'titulo':'Histórico de outro polo','vencimento':'2020-01-01','status':'pendente','escopo':'todas_as_partes'}},self.actor)
  self.store.save('tarefas',{'processo_id':c['id'],'dados':{'titulo':'Revisão','vencimento':'2020-01-01','status':'a_fazer','origem':'revisao_interna'}},self.actor)
  result=ctl.report(self.store)
  self.assertEqual(result['oficiais_vencidos'],0);self.assertEqual(result['revisoes_vencidas'],1);self.assertEqual(result['tarefas_atrasadas'],0)
