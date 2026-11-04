import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import email_alertas as mail,email_resumos as digest,juridico as legal,monitoramento as monitor,mandados
RS='5001234-12.2025.8.21.0001';SC='5001234-12.2025.8.24.0001';OTHER='5001234-12.2025.8.16.0001'
class DigestTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db.sqlite');self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  self.p1=patch.object(mail,'config_path',return_value=Path(self.tmp.name)/'mail.bin');self.p2=patch.object(mail,'crypt',side_effect=lambda b,decrypt=False:b);self.p1.start();self.p2.start();self.seq=0
  self.review_patch=patch.object(mail,'review_required',return_value=False);self.review_patch.start();self.addCleanup(self.review_patch.stop)
  self.cfg(True)
 def tearDown(self):self.p1.stop();self.p2.stop();self.tmp.cleanup()
 def cfg(self,auto):return mail.save(self.store,self.actor,{'remetente':mail.DEFAULT,'destinatario':mail.DEFAULT,'senha_app':'abcdefghijklmnop','automatico':auto})
 def run(self,*args,**kwargs):return super().run(*args,**kwargs)
 def add_run(self,number,state,changes=(),finished=True):
  self.seq+=1;rid='run-'+str(self.seq)
  with self.store.connect() as db:
   monitor.schema(db);db.execute('INSERT INTO monitor_runs VALUES(?,?,?,?,?,?)',(rid,legal.now(),legal.now() if finished else None,'TJSC' if number==SC else 'TJRS','coletado_revisar' if finished else 'em_andamento',1))
   db.execute('INSERT INTO monitor_results VALUES(?,?,?,?,?,?)',(rid,number,state,'Motivo de teste',legal.now(),legal.dumps(changes)))
  return rid
 def event(self,number='102',kind='novo_evento'):return {'tipo':kind,'evento':number,'data':'2026-10-30T11:00:00-03:00','descricao':'Juntada de petição, sem referência a mandado.'}
 def combine(self,runs,finished=True,unsupported=()):
  jid='job-'+str(self.seq)
  with self.store.connect() as db:
   monitor.jobs_schema(db);db.execute('INSERT INTO monitor_jobs VALUES(?,?,?,?,?,?)',(jid,self.actor['id'],legal.now(),'encerrado' if finished else 'ativo',jid,legal.dumps({'sem_conector':list(unsupported)})))
   for rid,n in runs:db.execute('INSERT INTO monitor_job_courts VALUES(?,?,?,?,?)',(jid,'TJSC' if n==SC else 'TJRS','coletado_revisar' if finished else 'consultando',rid,legal.dumps([n])))
  return jid
 def test_three_emails_for_two_courts_no_individual_run_duplicate(self):
  a=self.add_run(RS,'atualizado',[self.event()]);b=self.add_run(SC,'sem_atualizacao');self.combine([(a,RS),(b,SC)])
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);mail.process(self.store);self.assertEqual(send.call_count,3)
   quiet,changed,errors=[c.args[2] for c in send.call_args_list]
   self.assertIn(RS,changed);self.assertIn('Novo evento: 102',changed);self.assertIn('Juntada de petição',changed);self.assertNotIn(SC,changed)
   self.assertIn(SC,quiet);self.assertIn(RS,quiet)
 def test_any_event_number_and_description_are_eligible(self):
  self.add_run(RS,'atualizado',[self.event('7'),self.event('8','evento_alterado')])
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);text=send.call_args_list[1].args[2];self.assertIn('Novo evento: 7',text);self.assertIn('Alteração em evento existente: 8',text);self.assertEqual(send.call_count,3)
 def test_no_email_before_all_courts_finish(self):
  a=self.add_run(RS,'atualizado',[self.event()]);b=self.add_run(SC,'pendente',finished=False);jid=self.combine([(a,RS),(b,SC)],finished=False)
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);send.assert_not_called()
   with self.store.connect() as db:
    db.execute("UPDATE monitor_jobs SET state='encerrado' WHERE id=?",(jid,));db.execute("UPDATE monitor_job_courts SET state='coletado_revisar' WHERE job_id=?",(jid,))
   mail.process(self.store);send.assert_not_called()
   monitor.finish(self.store,b,'parcial');mail.process(self.store);self.assertEqual(send.call_count,3)
 def test_first_read_failures_and_unsupported_are_not_quiet(self):
  a=self.add_run(RS,'primeira_leitura');b=self.add_run(SC,'falha');self.combine([(a,RS),(b,SC)],unsupported=[OTHER])
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);first,second,third=[c.args[2] for c in send.call_args_list];self.assertIn('PRIMEIRA LEITURA',first);self.assertIn('Nenhum processo com alteração',second);self.assertNotIn(RS,second);self.assertIn('CONSULTA NÃO CONFIRMADA',third);self.assertIn('SEM CONECTOR',third);self.assertIn(OTHER,third);self.assertNotIn(SC,second)
 def test_three_reports_even_when_all_unchanged(self):
  self.add_run(RS,'sem_atualizacao')
  with patch.object(mail,'smtp_send') as send:mail.process(self.store);self.assertEqual(send.call_count,3);self.assertIn('Total: 0 processo(s)',send.call_args_list[1].args[2]);self.assertIn(RS,send.call_args_list[0].args[2])
 def test_initialization_and_reactivation_do_not_replay_completed_history(self):
  self.cfg(False);self.add_run(RS,'atualizado',[self.event()]);self.cfg(True)
  with patch.object(mail,'smtp_send') as send:mail.process(self.store);send.assert_not_called()
  self.add_run(SC,'sem_atualizacao')
  with patch.object(mail,'smtp_send') as send:mail.process(self.store);self.assertEqual(send.call_count,3)
 def test_legacy_config_migration_ignores_old_monitor_runs(self):
  self.add_run(RS,'atualizado',[self.event()])
  with self.store.connect() as db:db.execute('DELETE FROM email_digest_state')
  with patch.object(mail,'smtp_send') as send:mail.process(self.store);mail.process(self.store);send.assert_not_called()
 def test_uncertain_delivery_is_not_retried_and_other_half_is_attempted(self):
  self.add_run(RS,'atualizado',[self.event()])
  with patch.object(mail,'smtp_send',side_effect=[TimeoutError('secret SMTP detail'),None,None]) as send:
   with self.assertRaises(legal.AppError):mail.process(self.store)
   mail.process(self.store);self.assertEqual(send.call_count,3)
  rows=mail.status(self.store,self.actor)['historico'];self.assertEqual({r['status'] for r in rows},{'aceito_smtp','incerto'});self.assertNotIn('secret SMTP',json.dumps(rows))
 def test_metadata_change_is_labeled_without_claiming_new_event(self):
  self.add_run(RS,'atualizado',[{'tipo':'campo','campo':'classe','antes':'A','depois':'B'}])
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);text=send.call_args_list[1].args[2];self.assertIn('Campo alterado: classe',text);self.assertIn('Sem novo evento confirmado',text)
 def test_cancelled_unstarted_stage_appears_as_not_consulted(self):
  rid=self.add_run(RS,'sem_atualizacao');jid=self.combine([(rid,RS)])
  with self.store.connect() as db:db.execute("INSERT INTO monitor_job_courts VALUES(?,?,'cancelado',NULL,?)",(jid,'TJSC',legal.dumps([SC])))
  with patch.object(mail,'smtp_send') as send:mail.process(self.store);text=send.call_args_list[2].args[2];self.assertIn('PROCESSO NÃO CONSULTADO',text);self.assertIn(SC,text)
 def test_name_and_explicit_contact_are_included_without_guessing_opponent(self):
  rid=self.add_run(RS,'atualizado',[self.event()]);jid=self.combine([(rid,RS)])
  with self.store.connect() as db:
   summary={'sem_conector':[],'contexto':{RS:[{'nome_cliente':'Cliente fictício','contato':'Telefone: (51) 99999-0000','origem':'Planilha1, linha 2'}]}}
   db.execute('UPDATE monitor_jobs SET summary=? WHERE id=?',(legal.dumps(summary),jid))
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);text=send.call_args_list[1].args[2];self.assertIn('Cliente: Cliente fictício',text);self.assertIn('Contato: Telefone: (51) 99999-0000',text);self.assertIn('Fonte do nome: Planilha1',text)
 def test_missing_contact_stays_missing_instead_of_linking_by_name(self):
  self.store.save('pessoas',{'dados':{'nome':'Cliente fictício','tipo':'cliente','telefone':'(51) 98888-0000'}},self.actor)
  rid=self.add_run(RS,'sem_atualizacao');jid=self.combine([(rid,RS)])
  with self.store.connect() as db:db.execute('UPDATE monitor_jobs SET summary=? WHERE id=?',(legal.dumps({'sem_conector':[],'contexto':{RS:[{'nome_cliente':'Cliente fictício','contato':'','origem':'Planilha'}]}}),jid))
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);text=send.call_args_list[0].args[2];self.assertIn('Contato: não informado',text);self.assertNotIn('98888',text)
 def test_import_problems_and_runtime_failures_only_in_email_three(self):
  rid=self.add_run(RS,'falha');jid=self.combine([(rid,RS)])
  with self.store.connect() as db:db.execute('UPDATE monitor_jobs SET summary=? WHERE id=?',(legal.dumps({'sem_conector':[],'problemas':[{'aba':'Planilha1','linha':5,'valor':'5.0E+19','motivo':'Excel sem precisão'}]}),jid))
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);texts=[c.args[2] for c in send.call_args_list];self.assertNotIn('Motivo de teste',texts[0]);self.assertNotIn('Motivo de teste',texts[1]);self.assertIn('Motivo de teste',texts[2]);self.assertIn('Excel sem precisão',texts[2])
 def test_contact_from_client_explicitly_linked_to_case(self):
  case=self.store.save('processos',{'dados':{'numero':RS,'titulo':'Processo de teste'}},self.actor)
  person=self.store.save('pessoas',{'dados':{'nome':'Cliente vinculado','tipo':'cliente','telefone':'(51) 97777-0000'}},self.actor)
  self.store.save('partes',{'processo_id':case['id'],'dados':{'nome':'Cliente vinculado','papel':'reu','pessoa_id':person['id']}},self.actor)
  self.add_run(RS,'sem_atualizacao')
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);text=send.call_args_list[0].args[2];self.assertIn('Cliente: Cliente vinculado',text);self.assertIn('97777-0000',text)
 def test_prepare_initializes_without_sending_and_does_not_skip_future_batch(self):
  with self.store.connect() as db:db.execute('DELETE FROM email_digest_state')
  with patch.object(mail,'smtp_send') as send:mail.prepare(self.store);send.assert_not_called()
  self.add_run(RS,'sem_atualizacao')
  with patch.object(mail,'smtp_send') as send:mail.process(self.store);self.assertEqual(send.call_count,3)
 def test_readable_dates_and_internal_failure_scope(self):
  self.add_run(RS,'falha')
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store)
   subjects=[c.args[1] for c in send.call_args_list]
   texts=[c.args[2] for c in send.call_args_list]
   self.assertIn('1/3 - processos consultados',subjects[0]);self.assertIn('2/3 - processos com alteração',subjects[1])
   self.assertIn('Não indicam falha na tramitação',texts[2]);self.assertNotIn('T11:',texts[0]);self.assertIn('Horários de Brasília',texts[0])
if __name__=='__main__':unittest.main()
