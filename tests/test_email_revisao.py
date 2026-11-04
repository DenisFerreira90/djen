import unittest
from unittest.mock import patch
from test_email_resumos import DigestTests,RS
import email_alertas as mail,juridico as legal

class ManualReviewTests(DigestTests):
 def setUp(self):
  super().setUp()
  self.review_patch.stop()
 def test_no_automatic_send_with_old_enabled_config(self):
  self.add_run(RS,'atualizado',[self.event()])
  with patch.object(mail,'smtp_send') as send:mail.prepare(self.store);mail.process(self.store);send.assert_not_called()
  self.assertFalse(mail.status(self.store,self.actor)['automatico'])
 def test_preview_does_not_send_and_only_selected_part_is_sent_once(self):
  self.add_run(RS,'atualizado',[self.event()])
  with patch.object(mail,'smtp_send') as send:
   draft=mail.drafts(self.store,self.actor)['itens'][0];send.assert_not_called()
   self.assertEqual(len(draft['resumos']),3)
   body={'id':draft['id'],'partes':['alteracoes'],'remetente':mail.DEFAULT,'destinatario':mail.DEFAULT}
   mail.send_selected(self.store,self.actor,body);mail.send_selected(self.store,self.actor,body)
   self.assertEqual(send.call_count,1);self.assertIn('2/3',send.call_args.args[1])
   refreshed=mail.drafts(self.store,self.actor)['itens'][0]['resumos']
   self.assertEqual([r['envio'] for r in refreshed],['nao_enviado','aceito_smtp','nao_enviado'])
 def test_permissions_and_recipient_change_block_send(self):
  self.add_run(RS,'sem_atualizacao');draft=mail.drafts(self.store,self.actor)['itens'][0]
  with patch.object(mail,'smtp_send') as send:
   with self.assertRaises(legal.AppError):mail.drafts(self.store,{'role':'leitor'})
   with self.assertRaises(legal.AppError):mail.send_selected(self.store,self.actor,{'id':draft['id'],'partes':['erros'],'remetente':mail.DEFAULT,'destinatario':'outro@example.com'})
   send.assert_not_called()

# Only the three new manual-flow tests belong to this subclass.
for name in list(DigestTests.__dict__):
 if name.startswith('test_'):setattr(ManualReviewTests,name,None)
del DigestTests
if __name__=='__main__':unittest.main()
