import datetime as dt
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.runtime import Runtime,detail_scope,collect
from conectacoletor.storage import Vault
from conectacoletor.cli import parser
import fila_coleta,gestao,juridico

def cipher(raw,decrypt=False):return raw

class FullRoundTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.runtime=Runtime(self.tmp.name,Vault(Path(self.tmp.name)/'cofre',cipher))
  self.store=self.runtime.local
 def tearDown(self):self.tmp.cleanup()
 def seed(self):
  numbers=[f'{5000000+i:07d}-00.2026.8.24.0001' for i in range(55)]
  found={n:'https://example.invalid' for n in numbers};fingerprints={n:'fp' for n in numbers}
  fila_coleta.prepare(self.store,found,fingerprints,'completa',set())
  for n in numbers[:25]:
   record={'detalhes':{'cobertura_eventos':{'completo':True}},'gravado_no_sistema':True}
   gestao.sync_save(self.store,n,'fp',record,'previous');fila_coleta.finish(self.store,n,record)
  return numbers,found,fingerprints
 def test_incremental_explains_55_found_30_selected_25_previously_read(self):
  numbers,found,fp=self.seed();selection={}
  order=fila_coleta.prepare(self.store,found,fp,'incremental',set(),selection=selection)
  self.assertEqual(set(order),set(numbers[25:]))
  self.assertEqual(selection['selecionados'],30)
  self.assertEqual(selection['dispensados_incremental'],25)
  self.assertEqual(sum(selection[k] for k in ('selecionados','dispensados_incremental','aguardando_retentativa','fora_da_fila')),55)
 def test_full_round_includes_all_55_and_overrides_internal_retry_delay(self):
  numbers,found,fp=self.seed()
  for n in numbers[25:]:
   record={'detalhes':{'cobertura_eventos':{'completo':False}},'gravado_no_sistema':True}
   gestao.sync_save(self.store,n,'fp',record,'partial');fila_coleta.finish(self.store,n,record)
  selection={};self.assertEqual(len(fila_coleta.prepare(self.store,found,fp,'incremental',set(),selection=selection)),0)
  self.assertEqual(selection['aguardando_retentativa'],30)
  full={};self.assertEqual(set(fila_coleta.prepare(self.store,found,fp,'completa',set(),selection=full)),set(numbers))
  self.assertEqual(full['selecionados'],55);self.assertEqual(full['aguardando_retentativa'],0)
  # Replanning cannot certify an incomplete history as complete.
  with self.store.connect() as db:
   self.assertEqual(db.execute("SELECT COUNT(*) FROM collection_queue WHERE estado='concluido'").fetchone()[0],0)
   self.assertEqual(db.execute("SELECT COUNT(*) FROM sync_state WHERE situacao='falha'").fetchone()[0],30)
 def test_large_inventory_uses_total_not_smaller_pending_queue(self):
  n='5000001-00.2026.8.24.0001'
  pages=[{'tabelas':[{'linhas':[['Processo','Evento e Prazo','Final Prazo'],[n,'Intimação','31/12/2026']]}]}]
  self.assertEqual(detail_scope([n],pages,{'dias':20,'total_processos':500},dt.date(2026,11,6))[0],[n])
  self.assertEqual(detail_scope([n],pages,{'dias':20,'total_processos':501},dt.date(2026,11,6))[0],[])
 def test_full_is_cli_default_with_incremental_only_explicit(self):
  self.assertEqual(parser().parse_args(['coletar','TJSC']).modo,'completa')
  self.assertEqual(parser().parse_args(['coletar','TJSC','--modo','incremental']).modo,'incremental')
 def test_time_budget_continues_without_repeating_attempted_cases(self):
  runtime=MagicMock();runtime.db.get.return_value=False;seen=[]
  def step(runtime,court,scope,visible):
   seen.append(list(scope.get('_tentados_rodada',[])))
   scope['_tentados_rodada']=['case1'] if len(seen)==1 else ['case1','case2']
   return 'pausado_orcamento' if len(seen)==1 else 'parcial'
  with patch('conectacoletor.runtime._collect_round',side_effect=step):
   self.assertEqual(collect(runtime,'TJSC',{},True),'parcial')
  self.assertEqual(seen,[[],['case1']])
 def test_manual_pause_and_no_progress_do_not_create_infinite_retry(self):
  runtime=MagicMock();runtime.db.get.return_value=True
  with patch('conectacoletor.runtime._collect_round',return_value='pausado_orcamento') as run:
   self.assertEqual(collect(runtime,'TJSC',{}),'pausado_orcamento');self.assertEqual(run.call_count,1)
  runtime.db.get.return_value=False
  with patch('conectacoletor.runtime._collect_round',return_value='pausado_orcamento') as run:
   self.assertEqual(collect(runtime,'TJSC',{}),'pausado_orcamento');self.assertEqual(run.call_count,1)
  runtime.db.issue.assert_called_once()
