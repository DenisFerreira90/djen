import sys,tempfile,unittest,json,hashlib,io
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor import runtime
from conectacoletor.storage import AgentDB
from conectacoletor.history_audit import analyze,latest
from conectacoletor.cli import main
import eproc_eventos as events

HEADER=['Evento','Data/Hora','Descrição','Usuário','Documentos']
def snapshot(descriptions):return {'tabelas':[{'linhas':[HEADER,*[[str(n),'06/11/2026 10:00:00',description,'Usuário',''] for n,description in descriptions.items()]]}]}
def coverage(numbers,total=0,loaded=0):return events.coverage({'tabela':True,'total':total,'carregadas':loaded,'eventos':numbers})

class HistoryAuditTests(unittest.TestCase):
 def test_alternate_cancellation_wording_from_received_html_is_recognized(self):
  snap=snapshot({1:'Distribuição',2:'Autos incluídos',3:'Guia gerada',5:'Cancelamento de Movimentação Processual -  (Evento 4 - Link para pagamento - 31/07/2025 05:45:22)',6:'Juntada - Boleto Cancelado - Refer. Evento 4'})
  result=events.reconcile(coverage([1,2,3,5,6]),snap)
  self.assertTrue(result['completo']);self.assertEqual(result['lacunas_justificadas_por_cancelamento'],[4])
  self.assertEqual(result['cancelamentos_referenciados'],[{'evento_cancelado':4,'evento_que_registra':5}])
 def test_explicit_movement_cancellation_explains_gap_without_inventing_row(self):
  snap=snapshot({1:'Distribuição',3:'Petição',4:'Cancelada a movimentação processual - (Evento 2 - Conclusos para despacho - 01/11/2026 10:00:00)'})
  before=json.dumps(snap);result=events.reconcile(coverage([1,3,4]),snap)
  self.assertTrue(result['completo']);self.assertFalse(result['sequencia_continua'])
  self.assertEqual(result['lacunas_justificadas_por_cancelamento'],[2]);self.assertEqual(result['eventos_visiveis'],3)
  self.assertIn('sem_recuperar_conteudo_cancelado',result['escopo']);self.assertEqual(json.dumps(snap),before)
 def test_reference_style_cancellation_is_accepted_only_for_an_earlier_event(self):
  snap=snapshot({1:'Distribuição',3:'Cancelada a movimentação processual - (Intimação - 01/11/2026). Refer. Evento 2'})
  self.assertTrue(events.reconcile(coverage([1,3]),snap)['completo'])
  future=snapshot({1:'Distribuição',2:'Cancelada a movimentação processual - (Evento 3 - Texto)',4:'Petição'})
  self.assertFalse(events.reconcile(coverage([1,2,4]),future)['completo'])
 def test_bill_hearing_party_or_ambiguous_cancellations_cannot_explain_gap(self):
  for description in ['Juntada - Boleto Cancelado - Refer. Evento 2','Cancelamento de boleto - Refer. Evento 2','Audiência cancelada. Refer. Evento 2','Alterada a parte - exclusão. Refer. Evento 2','Cancelada a movimentação processual - (Evento 2 - Texto). Refer. Evento 3']:
   with self.subTest(description=description):
    result=events.reconcile(coverage([1,4]),snapshot({1:'Distribuição',4:description}))
    self.assertFalse(result['completo']);self.assertEqual(result['lacunas_justificadas_por_cancelamento'],[])
 def test_loaded_pages_with_unexplained_gap_stay_pending(self):
  result=events.reconcile(coverage([1,3],1,1),snapshot({1:'Distribuição',3:'Petição'}))
  self.assertTrue(result['paginacao_conferida']);self.assertFalse(result['completo'])
  self.assertEqual(result['lacunas_nao_justificadas_amostra'],[2]);self.assertEqual(result['motivo'],'paginas_carregadas_com_lacunas_nao_justificadas')
 def test_unloaded_pages_or_stalled_loader_are_not_certified(self):
  snap=snapshot({1:'Distribuição',3:'Cancelada a movimentação processual - (Evento 2 - Texto)'})
  result=events.reconcile(coverage([1,3],1,0),snap);self.assertFalse(result['completo'])
  base=coverage([1,3]);base['motivo']='sem_avanco_no_carregamento'
  result=events.reconcile(base,snap);self.assertFalse(result['completo']);self.assertEqual(result['motivo'],'sem_avanco_no_carregamento')
 def test_state_and_snapshot_numbers_must_match_even_with_equal_count_and_max(self):
  result=events.reconcile(coverage([1,4]),snapshot({2:'Petição',4:'Petição'}))
  self.assertFalse(result['tabela_confere_com_contagem']);self.assertEqual(result['motivo'],'tabela_divergente_da_contagem')
 def test_only_primary_event_rows_can_supply_cancellation_evidence(self):
  snap=snapshot({1:'Distribuição',3:'Petição'});table=snap['tabelas'][0]
  table.update(tabela_eventos=True,numeros_eventos_linhas=[None,1,3])
  extra=snapshot({2:'Cancelada a movimentação processual - (Evento 2 - Texto)'})['tabelas'][0]
  snap['tabelas'].append(extra)
  result=events.reconcile(coverage([1,3]),snap)
  self.assertFalse(result['completo']);self.assertEqual(result['eventos_visiveis'],2)
 def test_conflicting_descriptions_are_not_used_as_cancellation_proof(self):
  snap=snapshot({1:'Distribuição',3:'Cancelada a movimentação processual - (Evento 2 - Texto)'})
  snap['tabelas'][0]['linhas'].append(['3','','Petição diferente','',''])
  result=events.reconcile(coverage([1,3]),snap)
  self.assertFalse(result['completo']);self.assertEqual(result['eventos_com_descricoes_multiplas'],[3])
 def test_large_event_number_has_bounded_missing_number_sample(self):
  result=coverage([10**9]);self.assertEqual(result['lacunas_quantidade'],10**9-1)
  self.assertEqual(len(result['lacunas_amostra']),200);self.assertFalse(result['completo'])
 def test_offline_audit_leaves_original_file_and_database_untouched(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'processos.json';nums=[1,3]
   payload={'execucao':{'id':'audit-test'},'processos':[{'processo':'5000001-00.2026.8.24.0001','situacao':'historico_parcial','detalhes':{**snapshot({1:'Distribuição',3:'Cancelada a movimentação processual - (Evento 2 - Texto)'}),'cobertura_eventos':coverage(nums)}}]}
   path.write_text(json.dumps(payload));before=hashlib.sha256(path.read_bytes()).hexdigest()
   with patch('conectacoletor.cli.Runtime',side_effect=AssertionError('Não deve abrir o cofre/banco')),redirect_stdout(io.StringIO()):
    self.assertEqual(main(['--pasta',tmp,'auditar-historicos',str(path)]),0)
    self.assertEqual(main(['--pasta',tmp,'auditar-historicos',str(path),'--saida',str(path)]),1)
   self.assertEqual(analyze(path)['resumo']['conferidos_com_cancelamentos_referenciados'],1)
   self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
   self.assertFalse((Path(tmp)/'dados').exists())
 def test_issue_resolution_is_specific_to_one_process(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=AgentDB(Path(tmp)/'db');db.issue('TJSC','historico_eventos','Conferir','one');db.issue('TJSC','historico_eventos','Conferir','two')
   db.resolve_issue('TJSC','historico_eventos','one')
   self.assertEqual([r['local'] for r in db.issues()],['two'])
 def test_latest_uses_requested_tribunal_without_opening_other_payloads(self):
  with tempfile.TemporaryDirectory() as tmp:
   for court in ('TJSC','TJRS'):
    folder=Path(tmp)/'dados'/'coletas'/court;folder.mkdir(parents=True)
    (folder/'execucao.json').write_text(json.dumps({'tribunal':court}))
    (folder/'processos.json').write_text('{}')
   self.assertEqual(latest(tmp,'TJSC').parent.name,'TJSC')
