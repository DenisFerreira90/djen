import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import email_alertas as mail,juridico,mandados

class EmailTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=juridico.Store(Path(self.tmp.name)/'db.sqlite')
  self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  self.path=Path(self.tmp.name)/'mail.bin'
  self.p1=patch.object(mail,'config_path',return_value=self.path);self.p1.start()
  self.p2=patch.object(mail,'crypt',side_effect=lambda b,decrypt=False:b);self.p2.start()
 def tearDown(self):self.p1.stop();self.p2.stop();self.tmp.cleanup()
 def configure(self,auto=False):return mail.save(self.store,self.actor,{'remetente':mail.DEFAULT,'destinatario':mail.DEFAULT,'senha_app':'abcdefghijklmnop','automatico':auto})
 def test_no_secret_in_status_or_database(self):
  result=self.configure();self.assertNotIn('abcdefghijklmnop',json.dumps(result));self.assertTrue(result['configurado'])
  self.assertNotIn(b'abcdefghijklmnop',self.store.path.read_bytes())
  with self.assertRaises(juridico.AppError):mail.status(self.store,{**self.actor,'role':'equipe'})
 def test_smtp_ssl_and_test(self):
  self.configure()
  with patch.object(mail.smtplib,'SMTP_SSL') as smtp:
   smtp.return_value.__enter__.return_value.send_message.return_value={}
   mail.test(self.store,self.actor)
   self.assertEqual(smtp.call_args.args,('smtp.gmail.com',465))
   smtp.return_value.__enter__.return_value.login.assert_called_once_with(mail.DEFAULT,'abcdefghijklmnop')
  self.assertEqual(mail.status(self.store,self.actor)['historico'][0]['status'],'aceito_smtp')
 def add_alert(self,ident):
  with self.store.connect() as db:
   mandados.schema(db)
   db.execute('INSERT INTO mandate_alerts(id,event_id,case_id,numero,evento,data_evento,trecho,categoria,criado) VALUES(?,?,?,?,?,?,?,?,?)',(ident,ident,1,'5004310-40.2026.8.21.0018','1','2026-10-27','Mandado expedido','possivel_expedicao',juridico.now()))
 def test_auto_future_only_and_no_repeat_after_ambiguous_send(self):
  self.add_alert(1);self.configure(True)
  with patch.object(mail,'smtp_send') as send:
   mail.process(self.store);send.assert_not_called()
   self.add_alert(2);send.side_effect=TimeoutError('private detail must never be recorded')
   with self.assertRaises(juridico.AppError):mail.process(self.store)
   mail.process(self.store);self.assertEqual(send.call_count,1)
  r=mail.status(self.store,self.actor)['historico'][0];self.assertEqual(r['status'],'incerto');self.assertNotIn('private',r['erro'])
 def test_reader_cannot_save_or_send(self):
  reader={**self.actor,'role':'leitor'}
  with self.assertRaises(juridico.AppError):mail.save(self.store,reader,{})
  with self.assertRaises(juridico.AppError):mail.test(self.store,reader)
