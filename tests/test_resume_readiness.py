import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.runtime import Runtime,resume_scope
from conectacoletor.storage import Vault
from conectacoletor.cli import parser
import eproc
import eproc_relatorios as reports
from eproc_paginacao import wait_initial

NUMBER='5000001-00.2026.8.21.0001'
def table():
    return {'tabelas':[{'titulo':'Lista (1 registro - 1 a 1)',
        'linhas':[['Processo','Evento e Prazo','Final Prazo'],[NUMBER,'Intimação','20/11/2026']]}]}


class ResumeReadinessTests(unittest.TestCase):
    def test_url_and_stale_zero_are_not_enough_before_table_loads(self):
        page=MagicMock();page.evaluate.side_effect=[{'tabelas':[]}, {'tabelas':[]},table(),table(),table()]
        result=wait_initial(MagicMock(),page,'',reports.open_page)
        self.assertEqual(result,table());self.assertEqual(page.evaluate.call_count,5)

    def test_table_never_loaded_is_not_a_confirmed_zero_and_pause_propagates(self):
        page=MagicMock();page.evaluate.return_value={'tabelas':[]}
        self.assertIsNone(wait_initial(MagicMock(),page,'',reports.open_page,attempts=4))
        collector=MagicMock();collector.check.side_effect=InterruptedError()
        with self.assertRaises(InterruptedError):wait_initial(collector,page,'',reports.open_page)

    def test_visible_incomplete_table_keeps_window_for_manual_confirmation(self):
        collector=eproc.Collector();collector.options={'tribunal':'TJRS','invisivel':False}
        collector.log=MagicMock();collector.wait_user=MagicMock()
        context=MagicMock()
        with patch('eproc_paginacao.wait_initial',return_value=None):
            self.assertIsNone(collector.ready_listing(MagicMock(),context))
        self.assertIs(collector.wait_user.call_args.kwargs['context'],context)

    def test_background_incomplete_table_requires_access_instead_of_proceeding_empty(self):
        collector=eproc.Collector();collector.options={'tribunal':'TJRS','invisivel':True}
        collector.log=MagicMock();collector.update=MagicMock()
        with patch('eproc_paginacao.wait_initial',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'LISTA_NAO_CONFIRMADA'):
                collector.ready_listing(MagicMock(),MagicMock())
        collector.update.assert_called_with(estado='requer_login')

    def test_report_links_are_remembered_only_in_current_session_and_court(self):
        collector=eproc.Collector();collector.options={'tribunal':'TJRS'}
        frame=MagicMock(url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=painel_adv_listar')
        valid='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=movimentacao_preparada_listar&hash=TEST_ONLY'
        frame.locator.return_value.evaluate_all.return_value=[valid,valid.replace('tjrs','tjsc'),valid.replace('movimentacao_preparada_listar','movimentacao_excluir')]
        collector.surfaces=MagicMock(return_value=[frame]);collector.remember_reports(MagicMock())
        self.assertEqual(collector.report_routes,{'movimentacao_preparada_listar':valid})
        self.assertNotIn('report_routes',collector.current or {})

    def test_resume_after_empty_stage_recovers_previous_attempts_without_resetting_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Runtime(folder,Vault(Path(folder)/'vault',lambda value,decrypt=False:value))
            numbers=[f'{5000000+i:07d}-00.2026.8.21.0001' for i in range(925)]
            job=runtime.db.new_job('TJRS',{'dias':20,'modo':'completa','_tentados_rodada':numbers,'_falhas_rodada':4})
            run='empty-stage';runtime.db.update(job,'parcial',run)
            dest=runtime.data/'coletas'/run;dest.mkdir(parents=True)
            (dest/'processos.json').write_text(json.dumps({'execucao':{'tribunal':'TJRS','falhas_rodada':4},'processos':[]}))
            with patch('builtins.print'):
                scope=resume_scope(runtime,'TJRS',{'dias':10})
            self.assertEqual(len(scope['_tentados_rodada']),925)
            self.assertEqual(scope['_falhas_rodada'],4);self.assertEqual(scope['dias'],20)
            self.assertTrue(parser().parse_args(['coletar','TJRS','--retomar-rodada']).retomar_rodada)

    def test_resume_merges_latest_checkpoint_and_does_not_mix_other_court(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Runtime(folder,Vault(Path(folder)/'vault',lambda value,decrypt=False:value))
            job=runtime.db.new_job('TJRS',{'_tentados_rodada':[NUMBER]})
            runtime.db.update(job,'interrompido','rs-checkpoint')
            dest=runtime.data/'coletas'/'rs-checkpoint';dest.mkdir(parents=True)
            other='5000002-00.2026.8.21.0001'
            (dest/'checkpoint.json').write_text(json.dumps({'execucao':{'tribunal':'TJRS'},'processos':[{'processo':other}]}))
            runtime.db.new_job('TJSC',{'_tentados_rodada':['5000003-00.2026.8.24.0001']})
            with patch('builtins.print'):scope=resume_scope(runtime,'TJRS',{})
            self.assertEqual(set(scope['_tentados_rodada']),{NUMBER,other})

    def test_manual_recheck_does_not_ask_for_enter_twice(self):
        collector=eproc.Collector();collector.options={'tribunal':'TJRS'}
        collector.check=MagicMock();collector.log=MagicMock();collector.wait_user=MagicMock()
        frame=MagicMock();page=MagicMock();page.is_closed.return_value=False
        context=MagicMock(pages=[page])
        collector.find_list=MagicMock(side_effect=[None,None,frame,frame])
        collector.listing=MagicMock(return_value=False)
        collector.ready_listing=MagicMock(side_effect=[None,frame])
        with patch('eproc_login.step'):
            self.assertIs(collector.await_listing(context),frame)
        collector.wait_user.assert_not_called()
