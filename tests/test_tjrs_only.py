import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,monitoramento as m,eproc,eproc_tribunais as courts
from test_busca_lista import FakeCollector,RS,SC
class RSOnlyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'test.sqlite');self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True);self.collector=FakeCollector(self.store)
 def tearDown(self):self.tmp.cleanup()
 def test_mixed_list_starts_rs_only_and_sc_is_not_consulted(self):
  m.search_list(self.store,self.actor,self.collector,{'numeros':[RS,SC],'nonce':'onlyrs-1234'})
  self.assertEqual(self.collector.options['tribunal'],'TJRS');self.assertEqual(self.collector.options['numeros_monitorados'],[RS])
  job=m.job_status(self.store,self.actor)[0];self.assertEqual(job['resumo']['sem_conector'],[SC]);self.assertEqual(len(job['etapas']),1)
 def test_sc_only_rejected_without_mutation(self):
  with self.assertRaises(legal.AppError):m.search_list(self.store,self.actor,self.collector,{'numeros':[SC],'nonce':'onlysc-1234'})
  self.assertEqual(self.collector.started,[])
 def test_direct_sc_collector_blocked(self):
  with self.assertRaisesRegex(ValueError,'teste manual'):eproc.Collector().start(self.actor,{'tribunal':'TJSC'})
 def test_sc_explicit_manual_test_isolated(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=eproc.Collector(tmp)
   with patch.object(eproc.threading,'Thread') as thread:
    result=c.start(self.actor,{'tribunal':'TJSC','teste_sc':True})
   self.assertEqual(c.options['tribunal'],'TJSC');self.assertEqual(c.current['tribunal'],'TJSC')
   self.assertTrue(thread.return_value.start.called)
 def test_sc_automatic_cannot_use_manual_test_flag(self):
  for options in ({'automatico':True},{'monitorar_lista':True}):
   with self.assertRaisesRegex(ValueError,'teste manual'):
    eproc.Collector().start(self.actor,dict(options,tribunal='TJSC',teste_sc=True))
 def test_sc_history_identity_preserved(self):
  self.assertEqual(courts.from_number(SC),'TJSC');self.assertFalse(courts.enabled('TJSC'));self.assertTrue(courts.enabled('TJRS'))
if __name__=='__main__':unittest.main()
