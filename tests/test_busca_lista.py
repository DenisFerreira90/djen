import sys,tempfile,unittest,json,threading
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,monitoramento as m,mandados,eproc
RS='5001234-12.2025.8.21.0001';SC='5001234-12.2025.8.24.0001';OTHER='5001234-12.2025.8.16.0001'
class FakeCollector:
 def __init__(self,store):self.store=store;self.thread=None;self.options={};self.started=[];self.action=Mock()
 def start(self,actor,options):
  self.options=options;self.started.append(options);rid='fake-'+str(len(self.started));m.begin(self.store,rid,options['tribunal'],options['numeros_monitorados']);self.thread=Mock();self.thread.is_alive.return_value=True;return {'atual':{'id':rid}}
class SearchListTests(unittest.TestCase):
 def setUp(self):
  import eproc_tribunais
  active=patch.object(eproc_tribunais,'ATIVOS',{'TJRS','TJSC'});active.start();self.addCleanup(active.stop)
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'main.db');self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True);self.collector=FakeCollector(self.store)
 def tearDown(self):self.tmp.cleanup()
 def body(self,**extra):return {'numeros':[RS,SC,OTHER],'acao':'substituir','nonce':'pedido-123456',**extra}
 def finish(self,state='coletado_revisar'):
  rid='fake-'+str(len(self.collector.started));m.finish(self.store,rid,state);self.collector.thread=None
 def test_one_click_partitions_and_returns_both_court_results(self):
  output=m.search_list(self.store,self.owner,self.collector,self.body());self.assertEqual(len(self.collector.started),1)
  first=self.collector.options['tribunal'];self.assertEqual(self.collector.options['numeros_monitorados'],[RS] if first=='TJRS' else [SC])
  self.assertFalse(m.manual_tick(self.store,self.collector));self.finish();self.assertTrue(m.manual_tick(self.store,self.collector));self.assertEqual(len(self.collector.started),2);self.assertNotEqual(first,self.collector.options['tribunal'])
  self.finish();m.manual_tick(self.store,self.collector)
  job=m.job_status(self.store,self.owner)[0];self.assertEqual(job['state'],'encerrado');self.assertEqual(job['resumo']['sem_conector'],[OTHER]);self.assertEqual({s['tribunal'] for s in job['etapas']},{'TJRS','TJSC'})
 def test_retry_does_not_duplicate_and_changed_nonce_payload_rejected(self):
  a=m.search_list(self.store,self.owner,self.collector,self.body());b=m.search_list(self.store,self.owner,self.collector,self.body());self.assertEqual(a['id'],b['id']);self.assertTrue(b['repetido']);self.assertEqual(len(self.collector.started),1)
  with self.assertRaises(legal.AppError) as e:m.search_list(self.store,self.owner,self.collector,self.body(numeros=[RS]))
  self.assertEqual(e.exception.code,409)
 def test_reject_busy_before_replacing_list(self):
  mandados.set_scope(self.store,self.owner,[OTHER]);self.collector.thread=Mock();self.collector.thread.is_alive.return_value=True
  with self.assertRaises(legal.AppError) as e:m.search_list(self.store,self.owner,self.collector,self.body())
  self.assertEqual(e.exception.code,409);self.assertEqual(mandados.status(self.store)['numeros'],[OTHER])
 def test_snapshot_survives_later_list_replacement(self):
  m.search_list(self.store,self.owner,self.collector,self.body());first=self.collector.options['tribunal'];mandados.set_scope(self.store,self.owner,[OTHER]);self.finish();m.manual_tick(self.store,self.collector)
  self.assertEqual(self.collector.options['numeros_monitorados'],[SC] if first=='TJRS' else [RS])
 def test_cancel_stops_remaining_courts(self):
  jid=m.search_list(self.store,self.owner,self.collector,self.body())['id'];m.cancel_job(self.store,self.owner,self.collector,jid);self.collector.action.assert_called_once_with('cancelar');self.finish('cancelado');m.manual_tick(self.store,self.collector);self.assertEqual(len(self.collector.started),1);self.assertEqual(m.job_status(self.store,self.owner)[0]['state'],'cancelado')
 def test_interrupted_stage_is_not_all_clear(self):
  m.search_list(self.store,self.owner,self.collector,self.body());self.collector.thread=None;m.manual_tick(self.store,self.collector)
  stages=m.job_status(self.store,self.owner)[0]['etapas'];self.assertTrue(any(s['state']=='interrompido' for s in stages));self.assertTrue(any(s['contagens'].get('nao_consultado') for s in stages))
 def test_reader_and_foreign_cancellation_denied(self):
  reader=self.store.create_user({'nome':'Leitor','login':'leitor','senha':'senha-forte-123','role':'leitor'},self.owner)
  with self.assertRaises(legal.AppError) as e:m.search_list(self.store,reader,self.collector,self.body())
  self.assertEqual(e.exception.code,403)
  other=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},self.owner)
  jid=m.search_list(self.store,self.owner,self.collector,self.body())['id']
  with self.assertRaises(legal.AppError) as e:m.cancel_job(self.store,other,self.collector,jid)
  self.assertEqual(e.exception.code,403)
 def test_unsupported_only_or_invalid_numbers_preserve_current_list(self):
  mandados.set_scope(self.store,self.owner,[RS])
  for numbers in ([OTHER],['numero-corrompido']):
   with self.assertRaises(legal.AppError):m.search_list(self.store,self.owner,self.collector,self.body(numeros=numbers))
   self.assertEqual(mandados.status(self.store)['numeros'],[RS])
 def test_adding_retains_previous_numbers(self):
  mandados.set_scope(self.store,self.owner,[RS]);m.search_list(self.store,self.owner,self.collector,self.body(numeros=[SC],acao='adicionar'));self.assertEqual(mandados.status(self.store)['numeros'],[RS,SC])
 def test_repeat_uses_latest_list_and_saved_sessions_without_overlap(self):
  with patch.object(legal,'now',return_value='2026-10-30T06:00:00-03:00'):
   m.search_list(self.store,self.owner,self.collector,self.body(intervalo_horas=2))
  self.finish();m.manual_tick(self.store,self.collector);self.finish();m.manual_tick(self.store,self.collector)
  mandados.set_scope(self.store,self.owner,[SC]);previous=len(self.collector.started)
  with patch.object(legal,'now',return_value='2026-10-30T07:59:00-03:00'):self.assertFalse(m.repeat_tick(self.store,self.collector))
  with patch.object(legal,'now',return_value='2026-10-30T08:00:00-03:00'):self.assertTrue(m.repeat_tick(self.store,self.collector));self.assertFalse(m.repeat_tick(self.store,self.collector))
  self.assertEqual(len(self.collector.started),previous+1);self.assertTrue(self.collector.options['automatico']);self.assertEqual(self.collector.options['numeros_monitorados'],[SC])
  m.pause_repeat(self.store,self.owner);self.assertFalse(m.repeat_config(self.store,self.owner)['ativo'])
 def test_nonadmin_cannot_schedule_repetition(self):
  team=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},self.owner)
  with self.assertRaises(legal.AppError) as e:m.search_list(self.store,team,self.collector,self.body(intervalo_horas=3))
  self.assertEqual(e.exception.code,403)
 def test_real_start_has_no_database_lock_with_manual_queue(self):
  collector=eproc.Collector(Path(self.tmp.name)/'eproc')
  with patch.object(legal,'store',self.store),patch.object(collector,'run',return_value=None):
   result=m.search_list(self.store,self.owner,collector,self.body(numeros=[RS]));collector.thread.join(2);self.assertFalse(collector.thread.is_alive());self.assertTrue(result['id'])
 def test_client_context_is_snapshotted_and_reused_on_repetition(self):
  context=[{'numero':RS,'nome_cliente':'Cliente fictício','contato':'Telefone: 51999990000','origem':'Planilha1 linha 2'}]
  issues=[{'aba':'Planilha1','linha':8,'valor':'5.0E+19','motivo':'Sem precisão'}]
  m.search_list(self.store,self.owner,self.collector,self.body(numeros=[RS],contexto=context,problemas=issues))
  job=m.job_status(self.store,self.owner)[0];self.assertEqual(job['resumo']['contexto'][RS][0]['nome_cliente'],'Cliente fictício');self.assertEqual(job['resumo']['problemas'][0]['linha'],8)
  self.finish();m.manual_tick(self.store,self.collector)
  m.search_list(self.store,self.owner,self.collector,{'numeros':[RS],'nonce':'repeticao-1234','acao':'substituir'},automatic=True)
  new=m.job_status(self.store,self.owner)[0];self.assertEqual(new['resumo']['contexto'][RS][0]['contato'],'Telefone: 51999990000')
if __name__=='__main__':unittest.main()
