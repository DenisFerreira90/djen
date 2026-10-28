import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,gestao,planilhas,eproc_estruturado as eproc
from vendor import xlrd
from test_eproc_estruturado import sample, N

class TestNativeXls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'base.db')
        self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-segura-123'},setup=True)
    def tearDown(self):self.tmp.cleanup()
    def sheet(self):
        return {'linhas':[['Processos com prazo vencendo hoje','','Data geração: 27/10/2026 02:06:36'],['Processo','Órgão','Partes','Doc Partes','Classe','Assunto','Evento e Prazo','Data Envio requisição','Início Prazo','Final Prazo'],[N,'VARA1','Exequente \rPessoa A\r\r (11111111111)\rX\rExecutado \rPessoa B\r\r (22222222222)','Autor:\r11111111111\rReu:\r22222222222','CUMPRIMENTO DE SENTENÇA','Assunto','Intimação  15 dias','2026-10-20T12:30:44','2026-10-21T00:00:00','2026-10-27T23:59:59']],'epoca':'1899-12-30'}
    def test_second_row_header_and_explicit_flat_roles(self):
        s=self.sheet();h=planilhas.header_row(s['linhas']);self.assertEqual(h,1)
        mapping=planilhas.suggest(s['linhas'][h]);valid,errors=gestao.normalized_rows(s,h,mapping)
        self.assertEqual(errors,[])
        self.assertEqual([p['papel'] for p in valid[0]['dados']['partes_identificadas']],['exequente','executado'])
        self.assertEqual(valid[0]['dados']['vencimento'],'2026-10-27T23:59:59')
    def test_xls_branch_preserves_native_dates(self):
        class Cell:
            def __init__(self,ctype,value):self.ctype=ctype;self.value=value
        rows=[[Cell(1,'Processo'),Cell(1,'Final Prazo')],[Cell(1,N),Cell(3,46322.99998842593)]]
        sheet=MagicMock();sheet.nrows=2;sheet.ncols=2;sheet.name='Processos';sheet.cell.side_effect=lambda r,c:rows[r][c]
        book=MagicMock();book.sheets.return_value=[sheet];book.datemode=0
        with patch.object(xlrd,'open_workbook',return_value=book):parsed=planilhas.parse(b'xls-fixture','amostra.xls')
        self.assertEqual(parsed['abas'][0]['linhas'][1][1],'2026-10-27T23:59:59')
        book.release_resources.assert_called_once()
    def test_native_import_populates_grid_and_dates(self):
        s=self.sheet();h=planilhas.header_row(s['linhas']);m=planilhas.suggest(s['linhas'][h]);m['juizo_codigo']=m.pop('orgao')
        result=gestao.import_table(self.store,s,h,m,self.actor,'eproc.xls')
        self.assertEqual(result['processos_unicos'],1);self.assertEqual(result['partes'],2)
        case=self.store.list('processos')['itens'][0]
        self.assertTrue(case['partes_resumo']);self.assertEqual(case['dados']['juizo_codigo'],'VARA1')
        self.assertIn('Pessoa A',case['dados']['titulo'])
        self.assertEqual(self.store.list('prazos')['itens'][0]['dados']['data_inicio'],'2026-10-21T00:00:00')
    def test_native_xls_does_not_duplicate_exact_account_intimation(self):
        self.store.import_corpus(sample(),self.actor)
        s=self.sheet();s['linhas'][2][6]='Intimação 1 dia';s['linhas'][2][8]='2026-10-28T00:00:00';s['linhas'][2][9]='2026-10-28T23:59:59'
        h=planilhas.header_row(s['linhas']);m=planilhas.suggest(s['linhas'][h])
        before=self.store.list('prazos')['total'];result=gestao.import_table(self.store,s,h,m,self.actor,'eproc.xls')
        self.assertEqual(result['intimacoes_reconciliadas'],1)
        self.assertEqual(self.store.list('prazos')['total'],before)
    def test_event_without_duration_preserves_explicit_status_and_date(self):
        r=sample()['processos'][0]
        r['detalhes']['tabelas'][1]['linhas'][1][2]='Intimação do perito\n(PERITO - Pessoa Perita)\nStatus do Prazo: ABERTO\nData final: 13/11/2026 23:59:59'
        parsed=eproc.detail(r);d=next(d for d in parsed['prazos'] if d['evento']=='11')
        self.assertIsNone(d['quantidade_dias']);self.assertEqual(d['vencimento'],'2026-11-13T23:59:59')
        self.assertEqual(d['escopo'],'todas_as_partes')
    def test_professional_registration_with_inline_office_is_preserved(self):
        persons=eproc.parse_cell('Pessoa A (111.111.111-11) - Pessoa Física\nRepresentante A RS012345 (ESCRITÓRIO EXEMPLO/RS000001)','AUTOR')
        self.assertEqual(len(persons),2)
        self.assertEqual(persons[1]['registro'],'RS012345')
        self.assertEqual(persons[1]['representa_indice'],0)
        self.assertEqual(persons[1]['papel'],'representante')

    def test_plural_event_publication_links_each_explicit_reference(self):
        r=sample()['processos'][0]
        rows=r['detalhes']['tabelas'][1]['linhas'];rows.append(['12','21/10/2026 03:00:00','Publicado no DJEN - no dia 21/10/2026 - Refer. aos Eventos: 10, 11','sistema',''])
        deadlines=eproc.detail(r)['prazos']
        self.assertTrue(all(d.get('publicacao')=='2026-10-21' for d in deadlines))

if __name__=='__main__':unittest.main()
