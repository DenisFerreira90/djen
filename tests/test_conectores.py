import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import conectores,coleta_evidencias,servidor
class ConnectorTest(unittest.TestCase):
 def test_catalog_separates_planned_from_installed(self):
  items=conectores.catalog()['itens']
  self.assertEqual({i['tribunal'] for i in items if i['estado']=='instalado'},{'TJRS'})
  self.assertEqual({i['tribunal'] for i in items if i['estado']=='desativado_temporariamente'},{'TJSC'})
  self.assertEqual({i['tribunal'] for i in items if i['estado']=='teste_manual'},{'TJRJ'})
  for item in items:
   if item['estado']=='planejado':self.assertFalse(any(item['capacidades'].values()))
  self.assertIn('/js/conectores.js',servidor.ALLOWED_STATIC)
 def test_evidence_is_portable_and_escaped(self):
  with tempfile.TemporaryDirectory() as d:
   snap={'tabelas':[{'linhas':[['<script>alert(1)</script>','Evento 49']]}],'links':[{'url':'SECRET'}]}
   p=coleta_evidencias.save_tables(d,'5194330-39.2026.8.21.0001',snap,{'completo':False},sistema='futuro',tribunal='teste',coletado_em='2026-10-30')
   text=p.read_text();self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>',text);self.assertNotIn('SECRET',text)
 def test_number_cannot_escape_directory(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):coleta_evidencias.save_tables(d,'../../x',{}, {},sistema='x',tribunal='y',coletado_em='z')
