import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.runtime import Runtime,detail_scope
from conectacoletor.storage import Vault
from conectacoletor.cli import parser
import fila_coleta,gestao,eproc_relatorios as reports


class FinishPendingTests(unittest.TestCase):
    def test_current_panel_menu_recovers_missing_category_without_guessing_hashes(self):
        panel='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=painel_advogado_listar&hash=TEST_PANEL'
        category='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=citacao_intimacao_pendente_listar&hash=TEST_CATEGORY'
        frame=MagicMock(url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=citacao_intimacao_prazo_aberto_listar')
        frame.locator.return_value.evaluate_all.return_value=[panel,panel.replace('tjrs','tjsc')]
        page=MagicMock(url=panel);page.locator.return_value.evaluate_all.return_value=[category,category.replace('tjrs','tjsc')]
        context=MagicMock();context.new_page.return_value=page
        collector=MagicMock();collector.options={'tribunal':'TJRS'};collector.surfaces.return_value=[frame]
        collector.report_panel_checked=False;collector.report_routes={}
        self.assertEqual(reports.recover_panel_routes(collector,context,'citacao_intimacao_pendente_listar'),category)
        page.goto.assert_called_once_with(panel,wait_until='domcontentloaded',timeout=60000)
        page.close.assert_called_once()
        self.assertEqual(collector.report_routes,{'citacao_intimacao_pendente_listar':category})
        self.assertNotIn('TEST_PANEL',str(collector.log.call_args_list))
        self.assertNotIn('TEST_CATEGORY',str(collector.log.call_args_list))

    def test_no_observed_panel_route_does_not_construct_or_retry_urls(self):
        collector=MagicMock();collector.options={'tribunal':'TJRS'};collector.report_panel_checked=False
        frame=MagicMock(url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=citacao_intimacao_prazo_aberto_listar')
        frame.locator.return_value.evaluate_all.return_value=['https://outside.invalid/','https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=peticao_excluir']
        collector.surfaces.return_value=[frame];context=MagicMock()
        self.assertEqual(reports.recover_panel_routes(collector,context,'citacao_intimacao_pendente_listar'),'')
        self.assertEqual(reports.recover_panel_routes(collector,context,'citacao_intimacao_pendente_listar'),'')
        context.new_page.assert_not_called()

    def test_refused_access_propagates_without_retries_and_closes_auxiliary_page(self):
        panel='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=painel_adv_listar'
        collector=MagicMock();collector.options={'tribunal':'TJRS'};collector.report_panel_checked=False
        collector.surfaces.return_value=[MagicMock(url=panel)];collector.check.side_effect=RuntimeError('HTTP_403')
        context=MagicMock();page=MagicMock(url=panel);context.new_page.return_value=page
        with self.assertRaisesRegex(RuntimeError,'HTTP_403'):
            reports.recover_panel_routes(collector,context,'citacao_intimacao_pendente_listar')
        page.goto.assert_called_once();page.close.assert_called_once()

    def test_pending_mode_preserves_confirmed_even_when_fingerprint_changes_and_retries_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Runtime(folder,Vault(Path(folder)/'vault',lambda value,decrypt=False:value))
            numbers=[f'{5000000+i:07d}-00.2026.8.21.0001' for i in range(12)]
            found={n:'https://example.invalid' for n in numbers}
            with runtime.local.connect() as db:
                gestao.schema(db);fila_coleta.schema(db)
                for i,n in enumerate(numbers[:9]):
                    db.execute('INSERT OR REPLACE INTO sync_state VALUES(?,?,?,?,?,?,?)',(n,'old','2026-11-07T10:00:00-03:00','lido' if i<7 else 'falha',None,'','seed'))
                    db.execute('INSERT INTO collection_queue(numero,fingerprint,prioridade,estado,atualizado,retentar_em) VALUES(?,?,?,?,?,?)',(n,'old',0,'concluido' if i<7 else 'retentar','2026-11-07T10:00:00-03:00','2099-01-01T00:00:00-03:00' if i>=7 else None))
            order=fila_coleta.prepare(runtime.local,found,{n:'new' for n in numbers},'pendentes',set(numbers[:7]))
            self.assertEqual(set(order),set(numbers[7:]))
            with runtime.local.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM collection_queue WHERE estado='concluido'").fetchone()[0],7)

    def test_1587_read_5_failures_46_unread_170_later_produces_51_detail_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Runtime(folder,Vault(Path(folder)/'vault',lambda value,decrypt=False:value))
            numbers=[f'{5000000+i:07d}-00.2026.8.21.0001' for i in range(1808)]
            with runtime.local.connect() as db:
                gestao.schema(db)
                db.executemany('INSERT OR REPLACE INTO sync_state VALUES(?,?,?,?,?,?,?)',[(n,'old','2026-11-07T10:00:00-03:00','lido' if i<1587 else 'falha',None,'','seed') for i,n in enumerate(numbers[:1592])])
            order=fila_coleta.prepare(runtime.local,{n:'https://example.invalid' for n in numbers},{n:'changed' for n in numbers},'pendentes',set())
            pages=[{'tabelas':[{'linhas':[['Processo','Evento e Prazo','Final Prazo'],*[[n,'Intimação','31/12/2026' if i>=1638 else ''] for i,n in enumerate(numbers)]]}]}]
            selected,deferred,_=detail_scope(order,pages,{'total_processos':1808},dt.date(2026,11,7))
            self.assertEqual(set(selected),set(numbers[1587:1638]));self.assertEqual(len(selected),51)
            self.assertEqual(deferred,170)

    def test_cli_exposes_explicit_pending_mode(self):
        self.assertEqual(parser().parse_args(['coletar','TJRS','--modo','pendentes']).modo,'pendentes')
