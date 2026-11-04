import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mandados_resumo import summarize
import mandados_documentos as docs,juridico as legal
N='5000425-89.2026.8.21.0059'
def e(n,text,doc=''):
 return {'numero':str(n),'descricao':text,'data':'2026-10-19T13:55:23-03:00','usuario_origem':'joaopaulo','documentos_referencias':doc}
class MandateEventTests(unittest.TestCase):
 def test_requested_example_preserves_link_user_document_and_pending_return(self):
  r=summarize([e(49,'Expedição de mandado - CM0001','MAND1'),e(50,'Recebido o mandado para cumprimento pelo oficial de justiça - Refer. ao Evento: 49')])
  m=r['destaque'];self.assertEqual(m['expedicao']['evento'],'49');self.assertEqual(m['atualizacao']['evento'],'50');self.assertFalse(m['retorno_localizado']);self.assertEqual(m['expedicao']['documentos'],['MAND1']);self.assertEqual(m['atualizacao']['usuario'],'joaopaulo')
 def test_later_return_can_reference_intermediate_event(self):
  r=summarize([e(49,'Expedição de mandado'),e(50,'Recebido o mandado para cumprimento - Refer. ao Evento: 49'),e(55,'Juntada de certidão negativa - Refer. ao Evento: 50')]);m=r['destaque'];self.assertTrue(m['retorno_localizado']);self.assertIn('negativo',m['situacao']);self.assertEqual(m['expedicao']['evento'],'49')
 def test_receipt_does_not_count_as_completed_and_unlinked_not_assigned(self):
  r=summarize([e(49,'Expedição de mandado'),e(50,'Recebido o mandado para cumprimento - Refer. ao Evento: 49'),e(60,'Mandado cumprido negativo - Refer. ao Evento: 34')]);self.assertEqual(r['destaque']['atualizacao']['evento'],'50');self.assertFalse(r['destaque']['retorno_localizado'])
 def test_highlight_uses_latest_update_not_latest_issuance(self):
  r=summarize([e(10,'Expedição de mandado'),e(49,'Expedição de mandado'),e(55,'Mandado cumprido negativo - Refer. ao Evento: 10')]);self.assertEqual(r['destaque']['expedicao']['evento'],'10');self.assertEqual(r['destaque']['atualizacao']['evento'],'55')
 def test_cancellation_before_negative_wins_and_other_mandate_unchanged(self):
  r=summarize([e(49,'Expedição de mandado'),e(50,'Mandado não cumprido, cancelado - Refer. ao Evento: 49')]);self.assertIn('Alteração da ordem',r['situacao'])
 def test_document_link_validated_expired_and_not_exported(self):
  url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=acessar_documento&id_documento=example'
  snapshot={'texto':N,'documentos_eventos':[{'evento':'49','nome':'MAND1','url':url}]}
  with tempfile.TemporaryDirectory() as folder:
   store=legal.Store(Path(folder)/'test.sqlite');actor=store.create_user({'nome':'Administrador','login':'admin','senha':'senha-forte-123'},setup=True);store.save('processos',{'dados':{'numero':N,'titulo':'Teste'}},actor)
   docs.capture(N,snapshot);self.assertTrue(docs.available(N,'49','MAND1'));self.assertEqual(docs.resolve(store,actor,{'numero':N,'evento':'49','documento':'MAND1'})['url'],url)
   import eproc
   self.assertNotIn('documentos_eventos',eproc.public_snapshot({**snapshot,'tabelas':[]}))
   with patch.object(docs.time,'monotonic',return_value=10**15):
    self.assertFalse(docs.available(N,'49','MAND1'))
    with self.assertRaises(legal.AppError):docs.resolve(store,actor,{'numero':N,'evento':'49','documento':'MAND1'})
 def test_foreign_host_write_action_and_other_case_rejected(self):
  for url in ('https://evil.test/eproc/controlador.php?acao=acessar_documento','https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=processo_movimentar','https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=acessar_documento&num_processo=999'):
   docs.capture(N,{'texto':N,'documentos_eventos':[{'evento':'49','nome':'MAND1','url':url}]});self.assertFalse(docs.available(N,'49','MAND1'))
if __name__=='__main__':unittest.main()
