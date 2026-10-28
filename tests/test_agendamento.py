import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico,agendamento,eproc,gestao
class ScheduleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=juridico.Store(Path(self.tmp.name)/'db.sqlite')
  self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
 def tearDown(self):self.tmp.cleanup()
 def test_next_morning_once_and_incremental_without_extras(self):
  c=SimpleNamespace(thread=None,start=Mock())
  with patch.object(juridico,'now',return_value='2026-10-27T19:00:00-03:00'):agendamento.configure(self.store,self.actor)
  with patch.object(juridico,'now',return_value='2026-10-27T20:00:00-03:00'):agendamento.tick(self.store,c)
  c.start.assert_not_called()
  with patch.object(juridico,'now',return_value='2026-10-28T06:00:00-03:00'):
   agendamento.tick(self.store,c);agendamento.tick(self.store,c)
  self.assertEqual(c.start.call_count,1);self.assertEqual(c.start.call_args.kwargs['options'],{'modo':'incremental','descobrir_consultas':False,'automatico':True})
 def test_no_overlapping_or_disabled_schedule(self):
  c=SimpleNamespace(thread=Mock(),start=Mock());c.thread.is_alive.return_value=True
  with patch.object(juridico,'now',return_value='2026-10-27T05:00:00-03:00'):agendamento.configure(self.store,self.actor)
  with patch.object(juridico,'now',return_value='2026-10-27T06:00:00-03:00'):agendamento.tick(self.store,c)
  c.start.assert_not_called()
  with self.assertRaises(juridico.AppError):agendamento.configure(self.store,{**self.actor,'role':'equipe'})
 def test_unattended_does_not_wait_forever_for_login(self):
  collector=eproc.Collector(Path(self.tmp.name)/'eproc');collector.options={'automatico':True};collector.log=Mock()
  with self.assertRaisesRegex(RuntimeError,'ACAO_HUMANA'):collector.wait_user('Login necessário')
 def test_failed_local_import_is_not_marked_read(self):
  gestao.sync_save(self.store,'5004310-40.2026.8.21.0018','fp',{'detalhes':{'texto':'exemplo'},'gravado_no_sistema':False},'run')
  self.assertTrue(gestao.sync_plan(self.store,'5004310-40.2026.8.21.0018','fp')[0])
 def test_hourly_service_uses_each_slot_once(self):
  c=SimpleNamespace(thread=None,start=Mock())
  with patch.object(juridico,'now',return_value='2026-10-27T05:10:00-03:00'):agendamento.configure_service(self.store,self.actor,{'ativo':True,'frequencia':'horaria','limite_minutos':50,'detalhada':True})
  with patch.object(juridico,'now',return_value='2026-10-27T05:30:00-03:00'):agendamento.tick(self.store,c)
  c.start.assert_not_called()
  with patch.object(juridico,'now',return_value='2026-10-27T06:00:00-03:00'):
   agendamento.tick(self.store,c);agendamento.tick(self.store,c)
  with patch.object(juridico,'now',return_value='2026-10-27T07:00:00-03:00'):agendamento.tick(self.store,c)
  self.assertEqual(c.start.call_count,2);self.assertEqual(c.start.call_args.kwargs['options']['limite_minutos'],50);self.assertTrue(c.start.call_args.kwargs['options']['descobrir_consultas'])
 def test_budget_is_checked_before_next_operation(self):
  collector=eproc.Collector(Path(self.tmp.name)/'eproc');collector.deadline=1
  with patch('time.monotonic',return_value=2):
   with self.assertRaises(eproc.CollectionBudget):collector.check()
