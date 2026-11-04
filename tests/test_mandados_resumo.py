import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mandados_resumo import summarize
import mandados
class SummaryTest(unittest.TestCase):
 def test_three_separate_mandates(self):
  texts={17:'Concedida a Medida Liminar',25:'Expedição de mandado',27:'Juntada de mandado cumprido negativo - Refer. ao Evento: 25',34:'Expedição de mandado',36:'Juntada de mandado cumprido negativo - Refer. ao Evento: 34',49:'Expedição de mandado',50:'Recebido o mandado para cumprimento pelo oficial de justiça - Refer. ao Evento: 49'}
  r=summarize([{'numero':str(n),'descricao':t,'data':'2026-10-19'} for n,t in reversed(list(texts.items()))])
  self.assertEqual(len(r['mandados']),3)
  self.assertIn('negativo',r['mandados'][0]['situacao'])
  self.assertEqual(r['mandados'][-1]['atualizacao']['evento'],'50')
  self.assertIn('Recebido',r['situacao'])
  self.assertEqual(mandados.classify(texts[27]),'revisar_negativa_ou_alteracao')
 def test_unlinked_return_does_not_close_latest(self):
  r=summarize([{'numero':'49','descricao':'Expedição de mandado'},{'numero':'51','descricao':'Mandado cumprido negativo - Refer. ao Evento: 34'}])
  self.assertIn('Expedido',r['situacao'])
 def test_no_events_is_not_absence(self):
  self.assertIn('não identificada',summarize([])['situacao'])
