import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import Mock,patch,MagicMock
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,mandados,monitoramento as m,eproc,agendamento
N='5001234-12.2025.8.21.0001';N2='5001235-12.2025.8.21.0001';SC='5001234-12.2025.8.24.0001'
def record(text='Evento inicial',count=1):
 return {'processo':N,'gravado_no_sistema':True,'detalhes':{'texto':'Nº do processo '+N,'cobertura_eventos':{'completo':True,'eventos_visiveis':count},'tabelas':[{'linhas':[['Evento','Data/Hora','Descrição','Usuário','Documentos'],*[[str(i),'30/10/2026 10:00:00',text+str(i),'Servidor','PET1'] for i in range(1,count+1)]]}]}}
class MonitorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db.sqlite');self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  mandados.set_scope(self.store,self.actor,[N,N2,SC]);self.counter=0
 def tearDown(self):self.tmp.cleanup()
 def begin(self):
  self.counter+=1;run='run-'+str(self.counter);m.begin(self.store,run,'TJRS');return run
 def test_first_unchanged_changed_and_reason(self):
  a=self.begin();self.assertEqual(m.result(self.store,a,N,record())['status'],'primeira_leitura')
  b=self.begin();self.assertEqual(m.result(self.store,b,N,record())['status'],'sem_atualizacao')
  c=self.begin();r=m.result(self.store,c,N,record(count=2));self.assertEqual(r['status'],'atualizado');self.assertEqual(r['diferencas'][0]['evento'],'2');self.assertEqual(r['diferencas'][0]['tipo'],'novo_evento')
 def test_failed_partial_and_failed_import_never_replace_baseline(self):
  m.result(self.store,self.begin(),N,record())
  for field in ('partial','import','identity'):
   r=record(count=2)
   if field=='partial':r['detalhes']['cobertura_eventos']['completo']=False
   if field=='import':r['gravado_no_sistema']=False
   if field=='identity':r['detalhes']['texto']='Nº do processo '+N2
   self.assertEqual(m.result(self.store,self.begin(),N,r)['status'],'falha')
  self.assertEqual(m.result(self.store,self.begin(),N,record(count=2))['diferencas'][0]['tipo'],'novo_evento')
 def test_wrong_process_record_and_unplanned_number_cannot_create_baseline(self):
  run=self.begin();r=record();r['processo']=N2;r['detalhes']['texto']='Nº do processo '+N2
  self.assertEqual(m.result(self.store,run,N,r)['status'],'falha')
  with self.assertRaises(legal.AppError):m.result(self.store,run,SC,record())
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_baselines').fetchone()[0],0)
 def test_missing_events_fields_and_description_changes(self):
  old=m.canonical(record(count=2));new=m.canonical(record(text='Alterado'))
  old['campos']['classe']='Classe anterior'
  kinds={r['tipo'] for r in m.diff(old,new)};self.assertEqual(kinds,{'evento_alterado','campo','eventos_ausentes'})
 def test_cancel_budget_and_login_leave_unvisited_explicit(self):
  run=self.begin();m.result(self.store,run,N,record());m.finish(self.store,run,'pausado_orcamento')
  status=m.status(self.store,self.actor,run)
  self.assertEqual(status['contagens'],{'primeira_leitura':1,'nao_consultado':1});self.assertEqual(status['total_lista'],3)
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT numero FROM monitor_baselines').fetchall()[0][0],N)
 def test_rotation_prioritizes_unvisited_and_excludes_other_court(self):
  run=self.begin();m.result(self.store,run,N,record());m.finish(self.store,run,'cancelado')
  result=m.begin(self.store,'rotation','TJRS');self.assertEqual(result,[N2,N]);self.assertNotIn(SC,result)
 def test_schedule_two_hours_no_overlap_no_catchup_burst(self):
  collector=SimpleNamespace(thread=None,start=Mock())
  with patch.object(legal,'now',return_value='2026-10-30T06:15:00-03:00'):m.config(self.store,self.actor,{'ativo':True,'intervalo_horas':2,'tribunal':'TJRS'})
  with patch.object(legal,'now',return_value='2026-10-30T08:14:00-03:00'):self.assertFalse(m.tick(self.store,collector))
  with patch.object(legal,'now',return_value='2026-10-30T08:15:00-03:00'):self.assertTrue(m.tick(self.store,collector));self.assertFalse(m.tick(self.store,collector))
  self.assertEqual(collector.start.call_count,1);self.assertTrue(collector.start.call_args.kwargs['options']['monitorar_lista'])
  with patch.object(legal,'now',return_value='2026-10-30T19:00:00-03:00'):self.assertTrue(m.tick(self.store,collector));self.assertFalse(m.tick(self.store,collector))
  self.assertEqual(collector.start.call_count,2)
 def test_busy_disabled_and_non_admin(self):
  user=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},self.actor)
  with self.assertRaises(legal.AppError) as e:m.config(self.store,user,{'ativo':True,'intervalo_horas':2})
  self.assertEqual(e.exception.code,403)
  collector=SimpleNamespace(thread=Mock(),start=Mock());collector.thread.is_alive.return_value=True
  m.config(self.store,self.actor,{'ativo':True,'intervalo_horas':3,'tribunal':'TJRS'})
  self.assertFalse(m.tick(self.store,collector));collector.start.assert_not_called()
  for interval in (1,4,True,'2'):
   with self.assertRaises(legal.AppError):m.config(self.store,self.actor,{'ativo':True,'intervalo_horas':interval})
 def test_list_removed_no_longer_in_next_run_baseline_retained(self):
  m.result(self.store,self.begin(),N,record());mandados.set_scope(self.store,self.actor,[N2])
  self.assertEqual(m.begin(self.store,'changed-list','TJRS'),[N2])
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM monitor_baselines').fetchone()[0],1)
 def test_number_lookup_fails_closed_for_unknown_form(self):
  collector=Mock(options={'tribunal':'TJRS'});context=Mock();page=Mock();frame=Mock(url='https://evil.test/eproc/controlador.php');page.frames=[frame]
  with self.assertRaisesRegex(ValueError,'FORMULARIO_NAO_LOCALIZADO'):m.lookup(collector,context,page,'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=painel_adv_listar',N,eproc.SNAPSHOT)
  frame.locator.assert_not_called()
 def test_number_lookup_uses_actual_form_and_confirms_identity(self):
  collector=Mock(options={'tribunal':'TJRS'});page=MagicMock();frame=MagicMock(url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=processo_pesquisa_rapida');page.frames=[frame];page.is_closed.return_value=False;context=Mock(pages=[page])
  form=MagicMock();forms=MagicMock();forms.count.return_value=1;forms.nth.return_value=form;form.get_attribute.return_value='controlador.php?acao=processo_pesquisa_rapida&hash=current'
  inputs=MagicMock();inputs.count.return_value=1;inputs.first.is_visible.return_value=True;buttons=MagicMock();buttons.count.return_value=1;buttons.first.is_visible.return_value=True
  form.locator.side_effect=lambda s:inputs if s.startswith('input') else buttons
  password=MagicMock();password.count.return_value=0;body=MagicMock();body.inner_text.return_value='Nº do processo '+N
  frame.locator.side_effect=lambda s:forms if s.startswith('form') else password if s.startswith('input') else body
  self.assertEqual(m.lookup(collector,context,page,'unused',N,eproc.SNAPSHOT),(page,frame));inputs.first.fill.assert_called_once_with(N,timeout=10000);buttons.first.click.assert_called_once();page.goto.assert_not_called()
 def test_empty_list_start_rejected_without_browser(self):
  mandados.set_scope(self.store,self.actor,[],False);c=eproc.Collector(Path(self.tmp.name)/'eproc')
  with patch.object(legal,'store',self.store):
   with self.assertRaisesRegex(ValueError,'Salve uma lista'):c.start(self.actor,{'tribunal':'TJRS','monitorar_lista':True})
 def test_result_has_no_false_all_clear_for_unknown_run(self):
  with self.assertRaises(legal.AppError) as e:m.status(self.store,self.actor,'unknown')
  self.assertEqual(e.exception.code,404)
 def test_unchanged_case_is_checked_without_reimporting_details(self):
  from types import SimpleNamespace
  from unittest.mock import MagicMock
  import eproc_eventos
  baseline=record();self.store.import_corpus({'execucao':{'id':'initial'},'processos':[baseline]},self.actor);m.result(self.store,self.begin(),N,baseline)
  run=self.begin();page=MagicMock();frame=MagicMock();frame.page=page;frame.evaluate.return_value={'texto':baseline['detalhes']['texto'],'tabelas':baseline['detalhes']['tabelas']}
  collector=SimpleNamespace(current={'id':run},monitor_numbers=[N],options={'tribunal':'TJRS'},actor=self.actor,update=Mock(),log=Mock(),check=Mock(),save_checkpoint=Mock(),await_listing=Mock(return_value=SimpleNamespace(url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=citacao_intimacao_prazo_aberto_listar')),diagnostic=Mock(return_value='erro seguro'))
  context=SimpleNamespace(new_page=Mock(return_value=page),pages=[page]);records=[]
  with patch.object(legal,'store',self.store),patch.object(m,'lookup',return_value=(page,frame)),patch.object(eproc_eventos,'expand',return_value=baseline['detalhes']['cobertura_eventos']),patch.object(self.store,'import_corpus',wraps=self.store.import_corpus) as save:
   m.collect(collector,context,records,[]);save.assert_not_called()
  self.assertTrue(records[0]['gravacao_dispensada_sem_alteracao']);self.assertIsNone(records[0]['detalhes']);self.assertEqual(m.status(self.store,self.actor,run)['contagens']['sem_atualizacao'],1)
 def test_incomplete_read_keeps_prior_data_and_does_not_import(self):
  from types import SimpleNamespace
  from unittest.mock import MagicMock
  import eproc_eventos
  baseline=record();self.store.import_corpus({'execucao':{'id':'initial'},'processos':[baseline]},self.actor);m.result(self.store,self.begin(),N,baseline)
  run=self.begin();page=MagicMock();frame=MagicMock();frame.page=page;frame.evaluate.return_value={'texto':baseline['detalhes']['texto'],'tabelas':baseline['detalhes']['tabelas']}
  collector=SimpleNamespace(current={'id':run},monitor_numbers=[N],options={'tribunal':'TJRS'},actor=self.actor,update=Mock(),log=Mock(),check=Mock(),save_checkpoint=Mock(),await_listing=Mock(return_value=SimpleNamespace(url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=citacao_intimacao_prazo_aberto_listar')),diagnostic=Mock(return_value='erro seguro'))
  context=SimpleNamespace(new_page=Mock(return_value=page),pages=[page]);records=[]
  with patch.object(legal,'store',self.store),patch.object(m,'lookup',return_value=(page,frame)),patch.object(eproc_eventos,'expand',return_value={**baseline['detalhes']['cobertura_eventos'],'completo':False}),patch.object(self.store,'import_corpus',wraps=self.store.import_corpus) as save:
   m.collect(collector,context,records,[]);save.assert_not_called()
  self.assertFalse(records[0]['gravado_no_sistema']);self.assertIsNotNone(records[0]['detalhes']);self.assertEqual(m.status(self.store,self.actor,run)['contagens']['falha'],1)
if __name__=='__main__':unittest.main()
