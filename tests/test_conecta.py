import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import eproc
class ConectaTests(unittest.TestCase):
 def test_inventory_no_session_secrets(self):
  snapshot={'links':[{'texto':'Audiência','url':'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=audiencia_listar&num_processo=50043104020268210018&hash=SECRET'}, {'texto':'Agravo','url':'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=processo_agravar&txtNumProcesso=50043104020268210018&hash=SECRET'}]}
  result=eproc.action_inventory(snapshot,'5004310-40.2026.8.21.0018')
  self.assertEqual(result[0]['situacao'],'consulta_disponivel')
  self.assertEqual(result[1]['situacao'],'nao_navegada')
  self.assertNotIn('SECRET',str(result));self.assertNotIn('https',str(result))
 def test_foreign_case_not_available(self):
  result=eproc.action_inventory({'links':[{'url':'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=exame_listar&num_processo=99999999999999999999'}]},'5004310-40.2026.8.21.0018')
  self.assertEqual(result[0]['situacao'],'nao_navegada')
 def test_dynamic_columns_preserve_duplicates_and_extra_cells(self):
  result=eproc.adaptive_tables({'tabelas':[{'linhas':[['Data','Data',''],['a','b','c','d'],['e']]}]})[0]
  self.assertEqual(len(result['campos']),4)
  self.assertEqual(result['registros'][0]['coluna_4'],'d')
  self.assertEqual(result['registros'][1]['coluna_2'],'')
  self.assertTrue(result['conferencia_pendente'])
 def test_inventory_unknown_action(self):
  rows=eproc.action_inventory({'links':[{'url':'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=nova_acao&hash=SECRET'}]},'5004310-40.2026.8.21.0018')
  self.assertEqual(rows[0]['tipo'],'nao_mapeada')
