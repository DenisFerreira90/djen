import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.runtime import Runtime
from conectacoletor.storage import Vault
import eproc,eproc_relatorios as reports,eproc_estruturado

KIND='pendentes_citacao_intimacao'
ACTION='citacao_intimacao_pendente_listar'
HEADERS=['','Processo','Classe','Assunto','Evento e Prazo','Data envio requisição','Início Prazo','Final Prazo']

def snapshot(total=7):
 rows=[['',f'{5000100+i:07d}-00.2026.8.24.0001','Classe de teste','Assunto de teste','Intimação eletrônica — 15 dias','05/11/2026 15:36:10','','Aguarda publicação no DJEN'] for i in range(total)]
 return {'texto':'','links':[], 'tabelas':[{'titulo':f'Lista de Citações e Intimações Pendentes ({total} registros):','linhas':[HEADERS,*rows]}]}

class PendingCategoryTests(unittest.TestCase):
 def test_seven_occurrences_from_four_cases_are_not_dropped_as_duplicates(self):
  snap=snapshot()
  for i,row in enumerate(snap['tabelas'][0]['linhas'][1:]):row[1]=f'{5000100+i%4:07d}-00.2026.8.24.0001'
  snap['origem_relatorio']=KIND
  rows,total=reports.report_rows(snap,KIND)
  self.assertEqual((len(rows),total), (7,7));self.assertEqual(len({r['numero'] for r in rows}),4)
  pages=eproc.case_pages([snap]);self.assertEqual(len(pages),4)
  self.assertEqual(sum(len(t['linhas'])-1 for p in pages.values() for page in p for t in page['tabelas']),7)
 def test_observed_checkbox_column_and_seven_rows_are_preserved(self):
  page=snapshot();rows,total=reports.report_rows(page,KIND)
  self.assertEqual(total,7);self.assertEqual(len(rows),7)
  self.assertTrue(all(len(r['celulas'])==8 for r in rows))
  self.assertEqual(rows[0]['numero'],'5000100-00.2026.8.24.0001')
  self.assertEqual(rows[0]['celulas'][-1],'Aguarda publicação no DJEN')
 def test_pending_category_does_not_inflate_70_open_deadline_rows(self):
  pending={**snapshot(),'origem_relatorio':KIND}
  opened=snapshot(70)
  rows=reports.open_listing_rows([pending,opened])
  self.assertEqual(len(rows),70)
  self.assertEqual(len(reports.report_rows(pending,KIND)[0]),7)
 def test_list_navigation_discovers_current_hash_and_never_clicks_actions(self):
  url='https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao='+ACTION+'&hash=TEST_ONLY'
  page=MagicMock();page.url=url;page.evaluate.return_value=snapshot();page.locator.return_value.count.return_value=0
  frame=MagicMock();frame.url='https://eproc1g.tjsc.jus.br/eproc/'
  frame.locator.return_value.evaluate_all.return_value=[url]
  context=MagicMock();context.new_page.return_value=page
  collector=MagicMock();collector.options={'tribunal':'TJSC'};collector.surfaces.return_value=[frame]
  pages=[];found={}
  coverage,numbers=reports.collect(collector,context,ACTION,eproc.SNAPSHOT,pages,found,lambda snap:{})
  self.assertTrue(coverage['completo']);self.assertEqual(coverage['registros'],7)
  self.assertEqual(coverage['processos_distintos'],7);self.assertEqual(len(found),7)
  self.assertEqual(pages[0]['origem_relatorio'],KIND)
  self.assertNotIn('TEST_ONLY',str(pages))
  page.goto.assert_called_once_with(url,wait_until='domcontentloaded',timeout=60000)
  page.locator.return_value.click.assert_not_called();page.close.assert_called_once()
 def test_import_keeps_pending_category_and_does_not_invent_a_deadline(self):
  with tempfile.TemporaryDirectory() as folder:
   runtime=Runtime(folder,Vault(Path(folder)/'vault',lambda value,decrypt=False:value))
   pending={**snapshot(),'origem_relatorio':KIND}
   runtime.local.import_corpus({'execucao':{'id':'pending-test','tribunal':'TJSC'},'processos':[],'paginas_da_lista':[pending]},runtime.actor)
   with runtime.local.connect() as db:
    self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='processos'").fetchone()[0],7)
    self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='prazos'").fetchone()[0],0)
    self.assertEqual(db.execute('SELECT COUNT(*) FROM source_complements WHERE tipo=?',(KIND,)).fetchone()[0],7)
 def test_unknown_columns_are_not_certified_as_an_empty_list(self):
  page=snapshot();page['tabelas'][0]['linhas'][0]=['Coluna desconhecida']
  self.assertEqual(reports.report_rows(page,KIND),([],None))
 def test_read_route_validation_rejects_acknowledgement_and_other_courts(self):
  base='https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao='
  self.assertTrue(reports.valid_url(base+ACTION,ACTION,'TJSC'))
  self.assertFalse(reports.valid_url(base+'citacao_intimacao_confirmar',ACTION,'TJSC'))
  self.assertFalse(reports.valid_url((base+ACTION).replace('tjsc','tjrs'),ACTION,'TJSC'))
