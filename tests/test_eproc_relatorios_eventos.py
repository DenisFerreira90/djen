import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,eproc,eproc_relatorios as reports,eproc_eventos as events,gestao,fila_coleta
N='5001234-12.2025.8.21.0001';A='5001235-12.2025.8.21.7000'
def report(kind,rows,total):return {'texto':'','links':[], 'origem_relatorio':kind,'tabelas':[{'titulo':f'Lista ({total:,} registros):'.replace(',','.'),'linhas':[reports.HEADERS[kind],*rows]}]}
class ReportTests(unittest.TestCase):
 def test_agravo_belongs_to_origin_and_fingerprint_changes(self):
  page=report('agravos_distribuidos',[[N,A,'28/10/2026']],7289);rows,total=reports.report_rows(page,'agravos_distribuidos');self.assertEqual(total,7289);self.assertEqual(rows[0]['numero'],N)
  self.assertEqual(set(eproc.case_pages([page])),{N});fp=gestao.fingerprints_from_pages([page]);self.assertEqual(set(fp),{N})
  page['tabelas'][0]['linhas'][1][2]='29/10/2026';self.assertNotEqual(fp,gestao.fingerprints_from_pages([page]))
 def test_deadline_report_preserves_occurrences(self):
  row=[N,'Advogado','25/10/2026','26/10/2026','30/10/2026','Intimação'];page=report('prazos_a_encerrar',[row,row],264)
  self.assertEqual(len(reports.report_rows(page,'prazos_a_encerrar')[0]),2);self.assertEqual(len(eproc.case_pages([page])[N][0]['tabelas'][0]['linhas']),3)
 def test_url_validation_rejects_external_actions(self):
  action='recursos_tribunal_agravo_listar';url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao='+action+'&hash=example'
  self.assertTrue(reports.valid_url(url,action))
  for bad in (url.replace('https:','http:'),url.replace('eproc1g.tjrs.jus.br','evil.test'),url.replace(action,'processo_movimentar'),url+'&acao=outra',url+'#fragment'):
   self.assertFalse(reports.valid_url(bad,action))
 def test_two_report_pages_and_count_reconciliation(self):
  kind='agravos_distribuidos';one=report(kind,[[N,A,'28/10/2026']],2);two=report(kind,[[N,A,'29/10/2026']],2)
  page=MagicMock();page.url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=recursos_tribunal_agravo_listar'
  index=[0];page.evaluate.side_effect=lambda js:[one,two][index[0]];page.locator.return_value.count.return_value=0
  next_link=MagicMock();next_link.click.side_effect=lambda **kwargs:index.__setitem__(0,1)
  context=MagicMock();context.new_page.return_value=page;collector=MagicMock();collector.options={'url_'+kind:page.url};pages=[];found={}
  from unittest.mock import patch
  with patch.object(reports,'next_enabled',return_value=[next_link]):coverage,priority=reports.collect(collector,context,'recursos_tribunal_agravo_listar',eproc.SNAPSHOT,pages,found,eproc.process_links)
  self.assertTrue(coverage['completo']);self.assertEqual(coverage['registros'],2);self.assertEqual(priority,{N});self.assertEqual(len(pages),2);page.close.assert_called_once()
 def test_report_import_does_not_invent_duplicate_deadlines(self):
  with tempfile.TemporaryDirectory() as folder:
   store=legal.Store(Path(folder)/'db.sqlite');actor=store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
   p=report('prazos_a_encerrar',[[N,'Advogado','25/10/2026','26/10/2026','30/10/2026','Intimação']],1)
   a=report('agravos_distribuidos',[[N,A,'28/10/2026']],1)
   result=store.import_corpus({'execucao':{'id':'report-test-1'},'processos':[],'paginas_da_lista':[p,a]},actor)
   self.assertEqual(result['total'],1)
   with store.connect() as db:
    self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='prazos' AND json_extract(data,'$.origem')='eproc'").fetchone()[0],0)
    self.assertEqual(db.execute('SELECT COUNT(*) FROM source_complements').fetchone()[0],2)
   result=store.import_corpus({'execucao':{'id':'report-test-2'},'processos':[],'paginas_da_lista':[p,a]},actor)
   with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM source_complements').fetchone()[0],2)
class EventTests(unittest.TestCase):
 def state(self,total=0,loaded=0,nums=None):return {'tabela':True,'total':total,'carregadas':loaded,'funcao':True,'eventos':list(range(1,64)) if nums is None else nums}
 def test_gaps_and_unknown_counters_never_complete(self):
  self.assertTrue(events.coverage(self.state())['completo'])
  self.assertFalse(events.coverage(self.state(nums=[63,62,61]))['completo'])
  self.assertFalse(events.coverage(self.state(total=None))['completo'])
  self.assertFalse(events.coverage(self.state(total=2))['completo'])
 def test_incremental_event_loader_is_called_and_stall_detected(self):
  collector=MagicMock();page=MagicMock();state=self.state(total=1,nums=[63,62]);page.evaluate.side_effect=lambda script:state.copy() if script==events.STATE else state.update(carregadas=1,eventos=list(range(1,64)))
  result=events.expand(collector,page);self.assertTrue(result['completo']);self.assertEqual(result['eventos_visiveis'],63)
  page=MagicMock();page.evaluate.return_value=self.state(total=1,nums=[63]);result=events.expand(collector,page);self.assertFalse(result['completo']);self.assertEqual(result['motivo'],'sem_avanco_no_carregamento')
 def test_partial_history_stays_pending_after_import(self):
  with tempfile.TemporaryDirectory() as folder:
   store=legal.Store(Path(folder)/'db.sqlite');record={'processo':N,'gravado_no_sistema':True,'situacao':'historico_parcial','detalhes':{'texto':'Nº do processo '+N,'cobertura_eventos':{'completo':False}}}
   gestao.sync_save(store,N,'fingerprint',record,'run');self.assertTrue(gestao.sync_plan(store,N,'fingerprint')[0])
   fila_coleta.prepare(store,{N:None},{N:'fingerprint'},'completa',set());fila_coleta.finish(store,N,record);self.assertTrue(fila_coleta.pending(store,N))
