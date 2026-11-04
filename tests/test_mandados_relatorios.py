import sys,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_email_resumos import DigestTests,RS,SC,OTHER
import mandados_relatorios as reports,email_alertas as mail,juridico as legal
class ReportTests(unittest.TestCase):
 setUp=DigestTests.setUp;tearDown=DigestTests.tearDown;cfg=DigestTests.cfg;add_run=DigestTests.add_run;event=DigestTests.event;combine=DigestTests.combine
 def fixture(self,dated='2026-10-30T09:00:00-03:00'):
  run=self.add_run(RS,'primeira_leitura');bad=self.add_run(SC,'falha');jid=self.combine([(run,RS),(bad,SC)],unsupported=[OTHER]);case=self.store.save('processos',{'dados':{'numero':RS,'titulo':'Teste'}},self.actor)
  with self.store.connect() as db:
   db.execute('CREATE TABLE IF NOT EXISTS source_events(id INTEGER PRIMARY KEY,case_id INTEGER,numero TEXT,data TEXT,payload TEXT,signature TEXT,import_id TEXT)')
   db.execute("INSERT INTO imports VALUES('fixture','2026-10-29T09:00:00-03:00',?,'{}')",(self.actor['id'],))
   db.execute("UPDATE monitor_runs SET fim='2026-10-30T23:00:00-03:00'")
   for n,t in ((49,'Expedição de mandado - CM0001'),(50,'Recebido o mandado para cumprimento - Refer. ao Evento: 49')):
    e={'numero':str(n),'data':dated,'descricao':t,'documentos_referencias':'MAND1' if n==49 else ''}
    db.execute('INSERT INTO source_events VALUES(?,?,?,?,?,?,?)',(n,case['id'],str(n),dated,json.dumps(e),str(n),'fixture'))
  return {'pedido':'pedido:'+jid,'inicio':'2026-10-30','fim':'2026-10-30'}
 def test_first_read_mandate_and_all_failures_in_same_request(self):
  body=self.fixture()
  with patch.object(mail,'smtp_send') as smtp:
   result=reports.create(self.store,self.actor,body);smtp.assert_not_called()
  self.assertEqual(result['previstos'],3);self.assertEqual(result['consultados'],1);self.assertEqual(len(result['falhas']),2);self.assertEqual(result['mandados'][0]['expedicao']['evento'],'49');self.assertEqual(result['mandados'][0]['ultimo_evento']['evento'],'50')
 def test_date_filter_does_not_remove_failures_or_mark_old_mandate_today(self):
  body=self.fixture('2026-10-19T09:00:00-03:00');r=reports.create(self.store,self.actor,body);self.assertEqual(r['mandados'],[]);self.assertEqual(len(r['falhas']),2)
  body['inicio']='2026-10-01';self.assertEqual(len(reports.create(self.store,self.actor,body)['mandados']),1)
 def test_source_data_after_round_not_included(self):
  body=self.fixture()
  with self.store.connect() as db:db.execute("UPDATE imports SET data='2026-11-01T00:00:00-03:00'")
  r=reports.create(self.store,self.actor,body);self.assertEqual(r['mandados'],[]);self.assertEqual(len(r['sem_evidencia']),1)
 def test_manual_send_selected_idempotent_and_wrong_recipient_rejected(self):
  r=reports.create(self.store,self.actor,self.fixture());body={'id':r['id'],'partes':['falhas'],'remetente':mail.DEFAULT,'destinatario':mail.DEFAULT}
  with patch.object(mail,'smtp_send') as smtp:
   reports.send(self.store,self.actor,body);reports.send(self.store,self.actor,body);self.assertEqual(smtp.call_count,1);self.assertIn(SC,smtp.call_args.args[2]);self.assertIn(OTHER,smtp.call_args.args[2]);self.assertNotIn('Expedição: evento 49',smtp.call_args.args[2])
   with self.assertRaises(legal.AppError):reports.send(self.store,self.actor,{**body,'destinatario':'outro@example.com'})
 def test_invalid_date_and_unfinished_job_rejected(self):
  body=self.fixture()
  with self.assertRaises(legal.AppError):reports.create(self.store,self.actor,{**body,'inicio':'2026-11-01'})
  with self.store.connect() as db:db.execute("UPDATE monitor_jobs SET state='ativo'")
  with self.assertRaises(legal.AppError):reports.create(self.store,self.actor,body)
 def test_timezone_day_and_unknown_date(self):
  body=self.fixture('2026-10-31T01:00:00+00:00');self.assertEqual(len(reports.create(self.store,self.actor,body)['mandados']),1)
  with self.store.connect() as db:db.execute("UPDATE source_events SET data=''")
  r=reports.create(self.store,self.actor,body);self.assertEqual(len(r['sem_data']),1);self.assertEqual(r['mandados'],[])
 def test_preview_is_deduplicated_and_no_smtp_on_creation(self):
  body=self.fixture()
  with patch.object(mail,'smtp_send') as smtp:
   a=reports.create(self.store,self.actor,body);b=reports.create(self.store,self.actor,body);self.assertEqual(a['id'],b['id']);smtp.assert_not_called()
 def test_non_admin_cannot_send(self):
  with self.assertRaises(legal.AppError):reports.send(self.store,{'role':'leitor'},{})
del DigestTests
if __name__=='__main__':unittest.main()
