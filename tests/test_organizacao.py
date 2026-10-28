import datetime as dt
import base64
import threading
from urllib.request import urlopen, Request
import servidor
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal
import gestao
import planilhas

NUMBER='5001234-12.2025.8.21.0001'
class TestOrganization(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'legal.db')
        self.admin=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-bem-segura'},setup=True)
    def tearDown(self):self.tmp.cleanup()
    def sample(self):return {'linhas':[['Processo','Autor','Réu','Vencimento','Evento'],[NUMBER,'Ana; Bia','Empresa X','30/10/2026','evento1']],'epoca':'1899-12-30'}
    def test_preview_does_not_write_and_mapping_preserves_multiple_parties(self):
        sheet=self.sample();mapping=planilhas.suggest(sheet['linhas'][0])
        preview=gestao.import_table(self.store,sheet,0,mapping,self.admin,preview=True)
        self.assertEqual(preview['validas'],1);self.assertEqual(self.store.list('processos')['total'],0)
        result=gestao.import_table(self.store,sheet,0,mapping,self.admin)
        self.assertEqual(result['partes'],3);self.assertEqual(result['prazos'],1)
        self.assertEqual(self.store.list('partes')['total'],3)
        self.assertEqual(self.store.list('prazos')['itens'][0]['dados']['vencimento'],'2026-10-30')
    def test_errors_reject_entire_import(self):
        sheet=self.sample();sheet['linhas'].append(['inválido','Nome','','amanhã',''])
        with self.assertRaises(legal.AppError):gestao.import_table(self.store,sheet,0,planilhas.suggest(sheet['linhas'][0]),self.admin)
        self.assertEqual(self.store.list('processos')['total'],0)
    def test_internal_review_is_five_days_and_never_moves(self):
        sheet={'linhas':[['Processo'],[NUMBER]]}
        with patch.object(legal,'now',return_value='2026-10-27T10:00:00-03:00'):
            gestao.import_table(self.store,sheet,0,{'numero':0},self.admin)
        task=self.store.list('tarefas')['itens'][0]
        self.assertEqual(task['dados']['vencimento'],'2026-11-01')
        with patch.object(legal,'now',return_value='2026-11-10T10:00:00-03:00'):
            again=gestao.import_table(self.store,sheet,0,{'numero':0},self.admin)
            gestao.organize(self.store,self.admin)
        self.assertTrue(again['repetido']);self.assertEqual(self.store.list('tarefas')['total'],1)
        self.assertEqual(self.store.list('tarefas')['itens'][0]['dados']['vencimento'],'2026-11-01')
    def test_official_deadline_cancels_internal_reminder_with_history(self):
        case=self.store.save('processos',{'dados':{'numero':NUMBER}},self.admin)
        reminder=self.store.list('tarefas')['itens'][0]
        self.store.save('prazos',{'dados':{'titulo':'Prazo','vencimento':'2026-11-02'},'processo_id':case['id']},self.admin)
        after=self.store.detail(reminder['id'])
        self.assertEqual(after['dados']['status'],'cancelada')
        self.assertEqual(after['dados']['vencimento'],reminder['dados']['vencimento'])
    def test_reimport_does_not_overwrite_manual_data_or_duplicate_deadlines(self):
        case=self.store.save('processos',{'dados':{'numero':NUMBER,'titulo':'Título manual'}},self.admin)
        sheet=self.sample();sheet['linhas'][0].append('Título');sheet['linhas'][1].append('Outro título')
        mapping=planilhas.suggest(sheet['linhas'][0]);gestao.import_table(self.store,sheet,0,mapping,self.admin)
        gestao.import_table(self.store,sheet,0,mapping,self.admin)
        self.assertEqual(self.store.detail(case['id'])['dados']['titulo'],'Título manual')
        self.assertEqual(self.store.list('prazos')['total'],1)
    def test_same_event_with_changed_date_is_flagged_not_overwritten(self):
        sheet=self.sample();mapping=planilhas.suggest(sheet['linhas'][0])
        gestao.import_table(self.store,sheet,0,mapping,self.admin)
        sheet['linhas'][1][3]='05/11/2026'
        result=gestao.import_table(self.store,sheet,0,mapping,self.admin)
        self.assertEqual(result['conflitos_de_prazo'],1)
        self.assertEqual(self.store.list('prazos')['total'],1)
        self.assertEqual(self.store.list('prazos')['itens'][0]['dados']['vencimento'],'2026-10-30')
        self.assertEqual(self.store.list('anotacoes')['total'],1)

    def test_task_completion_requires_explanation_and_preserves_origin(self):
        self.store.save('processos',{'dados':{'numero':NUMBER}},self.admin);task=self.store.list('tarefas')['itens'][0]
        with self.assertRaises(legal.AppError):self.store.save('tarefas',{'dados':{'status':'concluida'},'versao':task['versao']},self.admin,task['id'])
        done=self.store.save('tarefas',{'dados':{'status':'concluida','conclusao':'Conferido no tribunal; referência 123.'},'versao':task['versao']},self.admin,task['id'])
        self.assertEqual(done['dados']['origem'],'revisao_interna');self.assertEqual(done['dados']['concluido_por'],self.admin['id'])
    def test_date_filters_keep_internal_and_official_separate(self):
        case=self.store.save('processos',{'dados':{'numero':NUMBER}},self.admin)
        self.store.save('prazos',{'dados':{'titulo':'Prazo','vencimento':'2026-11-20'},'processo_id':case['id']},self.admin)
        items=gestao.agenda(self.store,{'origem':'oficial','de':'2026-11-19','ate':'2026-11-21'})['itens']
        self.assertEqual(len(items),1);self.assertEqual(items[0]['tipo'],'prazos')
    def test_incremental_retries_failed_skips_unchanged_and_reviews_stale(self):
        fingerprint='fp1'
        record={'detalhes':{'texto':NUMBER,'tabelas':[]},'situacao':'pagina_lida'}
        self.assertTrue(gestao.sync_plan(self.store,NUMBER,fingerprint)[0])
        gestao.sync_save(self.store,NUMBER,fingerprint,record,'exec1')
        self.assertFalse(gestao.sync_plan(self.store,NUMBER,fingerprint)[0])
        self.assertTrue(gestao.sync_plan(self.store,NUMBER,'changed')[0])
        self.assertTrue(gestao.sync_plan(self.store,NUMBER,fingerprint,'individual')[0])
        with self.store.connect() as db:db.execute("UPDATE sync_state SET checked_at='2020-01-01T00:00:00-03:00'")
        self.assertTrue(gestao.sync_plan(self.store,NUMBER,fingerprint)[0])
        self.assertFalse(gestao.sync_plan(self.store,NUMBER,fingerprint,'falhas')[0])
        gestao.sync_save(self.store,NUMBER,fingerprint,{'detalhes':None,'situacao':'falha'},'exec2')
        self.assertTrue(gestao.sync_plan(self.store,NUMBER,fingerprint,'falhas')[0])
    def test_fingerprint_tracks_multiple_rows_without_order_noise(self):
        rows=[[NUMBER,'Evento 1'],[NUMBER,'Evento 2']]
        a=gestao.fingerprints_from_pages([{'tabelas':[{'linhas':rows}]}])
        b=gestao.fingerprints_from_pages([{'tabelas':[{'linhas':rows[::-1]}]}])
        self.assertEqual(a,b)
        self.assertNotEqual(a,gestao.fingerprints_from_pages([{'tabelas':[{'linhas':rows[:1]}]}]))
    def test_excel_dates_csv_and_native_workbook_structure(self):
        self.assertEqual(planilhas.date('01/11/2026'),'2026-11-01')
        self.assertTrue(planilhas.date('46327').startswith('2026'))
        data=planilhas.xlsx([('Processos',[['Processo','Disponibilização'],[NUMBER,dt.datetime(2026,10,27,10,30)]])])
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for file in z.namelist():ET.fromstring(z.read(file))
            xml=z.read('xl/worksheets/sheet1.xml').decode()
            self.assertIn('t="inlineStr"',xml);self.assertIn(NUMBER,xml);self.assertIn('autoFilter',xml);self.assertIn('frozen',xml)
        parsed=planilhas.parse(data,'arquivo.xlsx')
        self.assertEqual(parsed['abas'][0]['linhas'][1][0],NUMBER)
        csv=planilhas.parse(('Processo;Autor\n'+NUMBER+';Ana\n').encode(),'arquivo.csv')
        self.assertEqual(csv['abas'][0]['linhas'][1],[NUMBER,'Ana'])
    def test_restorable_backup_keeps_data_audit_and_expires_sessions(self):
        self.store.save('processos',{'dados':{'numero':NUMBER}},self.admin)
        _,token=self.store.login('admin','senha-bem-segura')
        backup=gestao.backup(self.store,self.admin)
        self.store.save('pessoas',{'dados':{'nome':'Criada depois do backup'}},self.admin)
        restored=gestao.restore(self.store,backup,self.admin)
        self.assertTrue(restored['restaurado'])
        self.assertEqual(self.store.list('processos')['total'],1)
        self.assertEqual(self.store.list('pessoas')['total'],0)
        with self.assertRaises(legal.AppError):self.store.auth(token)
        self.assertTrue(any(e['acao']=='restaurar_backup' for e in self.store.audits(self.admin)['itens']))
        self.assertTrue((self.store.path.parent/'backups'/restored['backup_anterior']).is_file())

    def test_http_excel_preview_confirm_and_download(self):
        with patch.object(legal,'store',self.store):
            server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base='http://127.0.0.1:'+str(server.server_port)
            session,key=self.store.login('admin','senha-bem-segura')
            headers={'Cookie':'juridico_session='+key,'Content-Type':'application/json','X-CSRF-Token':session['csrf']}
            def post(route,body):
                with urlopen(Request(base+'/api/juridico/'+route,data=json.dumps(body).encode(),headers=headers)) as r:return json.load(r)['resultado']
            try:
                parsed=post('planilha/ler',{'nome':'teste.csv','arquivo_base64':base64.b64encode(('Processo;Autor;Vencimento\n'+NUMBER+';Ana;30/10/2026').encode()).decode()})
                sheet=parsed['abas'][0];body={'aba':sheet,'cabecalho':0,'mapa':sheet['sugestao'],'previa':True}
                self.assertEqual(post('planilha/importar',body)['validas'],1)
                self.assertEqual(self.store.list('processos')['total'],0)
                body['previa']=False
                self.assertEqual(post('planilha/importar',body)['criados'],1)
                with urlopen(Request(base+'/api/juridico/planilha/exportar',headers=headers)) as r:
                    self.assertIn('spreadsheetml',r.headers['Content-Type'])
                    self.assertIn('Processos',[x['nome'] for x in planilhas.parse(r.read(),'resultado.xlsx')['abas']])
            finally:server.shutdown();server.server_close();worker.join()

    def test_excel_export_separates_entities_and_keeps_long_id_text(self):
        self.store.save('processos',{'dados':{'numero':NUMBER}},self.admin)
        sheets=gestao.export_sheets(self.store,self.admin);names=[name for name,_ in sheets]
        self.assertIn('Processos',names);self.assertIn('Prazos',names);self.assertIn('Partes',names);self.assertIn('Auditoria',names)
        parsed=planilhas.parse(planilhas.xlsx(sheets),'export.xlsx')
        process=next(s for s in parsed['abas'] if s['nome']=='Processos')
        self.assertEqual(process['linhas'][1][1],NUMBER)

if __name__=='__main__':unittest.main()
