import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen, Request
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal
import servidor

class TestLegal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=legal.Store(Path(self.tmp.name)/'db.sqlite3')
        self.admin=self.store.create_user({'nome':'Ana Admin','login':'ana','senha':'senha-forte-123'},setup=True)
    def tearDown(self): self.tmp.cleanup()
    def user(self,role):
        return self.store.create_user({'nome':role,'login':role,'senha':'senha-equipe-123','role':role},self.admin)
    def process(self):
        return self.store.save('processos',{'dados':{'numero':'5001234-12.2025.8.21.0001','titulo':'Teste','revisao':0}},self.admin)
    def test_individual_login_and_logout_and_no_plain_password(self):
        session,token=self.store.login('ANA','senha-forte-123')
        self.assertEqual(self.store.auth(token)[0]['id'],self.admin['id'])
        self.assertEqual(self.store.auth(token)[1],session['csrf'])
        self.store.logout(token,self.admin)
        with self.assertRaises(legal.AppError): self.store.auth(token)
        with self.store.connect() as db:
            row=db.execute('SELECT password FROM users').fetchone()
            self.assertNotIn('senha-forte',row[0])
    def test_reader_cannot_write_or_read_audit_or_export(self):
        reader=self.user('leitor')
        for call in (lambda:self.store.save('pessoas',{'dados':{'nome':'X'}},reader),lambda:self.store.audits(reader),lambda:self.store.export(reader),lambda:self.store.create_user({},reader)):
            with self.assertRaises(legal.AppError) as error: call()
            self.assertEqual(error.exception.code,403)
    def test_audit_records_actor_before_after_and_cannot_be_rewritten(self):
        team=self.user('equipe');p=self.process()
        self.store.save('processos',{'dados':{**p['dados'],'titulo':'Alterado'},'versao':p['versao']},team,p['id'])
        events=self.store.audits(self.admin)['itens']
        changed=next(e for e in events if e['acao']=='alterar')
        self.assertEqual(changed['actor_id'],team['id'])
        self.assertEqual(json.loads(changed['antes'])['dados']['titulo'],'Teste')
        self.assertEqual(json.loads(changed['depois'])['dados']['titulo'],'Alterado')
        self.assertIn('-03:00',changed['data'])
        with self.store.connect() as db,self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM audit')
    def test_conflicting_edits_preserve_latest(self):
        p=self.process()
        payload={'dados':{**p['dados'],'titulo':'Novo'},'versao':1}
        self.store.save('processos',payload,self.admin,p['id'])
        with self.assertRaises(legal.AppError) as err:self.store.save('processos',payload,self.admin,p['id'])
        self.assertEqual(err.exception.code,409)
        self.assertEqual(self.store.detail(p['id'])['dados']['titulo'],'Novo')
    def test_same_number_is_not_duplicated(self):
        self.process()
        with self.assertRaises(legal.AppError): self.process()
    def test_representative_must_reference_party_in_same_case(self):
        p=self.process()
        person=self.store.save('pessoas',{'dados':{'nome':'Cliente'}},self.admin)
        party=self.store.save('partes',{'dados':{'nome':'Cliente','papel':'autor','pessoa_id':person['id']},'processo_id':p['id']},self.admin)
        lawyer=self.store.save('partes',{'dados':{'nome':'Advogado','papel':'advogado','representa_id':party['id']},'processo_id':p['id']},self.admin)
        self.assertEqual(lawyer['dados']['representa_id'],party['id'])
        other=self.store.save('processos',{'dados':{'numero':'5001235-12.2025.8.21.0001'}},self.admin)
        with self.assertRaises(legal.AppError):self.store.save('partes',{'dados':{'nome':'Outro','representa_id':party['id']},'processo_id':other['id']},self.admin)
    def test_deadlines_keep_separate_dates_and_validation(self):
        p=self.process()
        for date in ('2026-10-27T18:00','2026-11-10T23:59'):
            self.store.save('prazos',{'dados':{'titulo':'Intimação','vencimento':date,'data_fatal':date,'fonte':'eproc','conferido':1},'processo_id':p['id']},self.admin)
        self.assertEqual(len([v for v in self.store.detail(p['id'])['vinculos'] if v['tipo']!='tarefas']),2)
        with self.assertRaises(legal.AppError):self.store.save('prazos',{'dados':{'titulo':'Inválido','vencimento':'2026-99-77'},'processo_id':p['id']},self.admin)
    def test_partial_old_export_imports_list_without_inventing_parties_or_deadlines(self):
        payload={'execucao':{'id':'antiga'},'processos':[],'paginas_da_lista':[{'tabelas':[{'linhas':[['Processo','Partes','Final'],['5001234-12.2025.8.21.0001','Autor X Réu Y','27/10/2026'],['5001235-12.2025.8.21.0001','Outras partes','28/10/2026']]}]}]}
        first=self.store.import_corpus(payload,self.admin)
        self.assertEqual(first['criados'],2)
        again=self.store.import_corpus(payload,self.admin)
        self.assertTrue(again['repetido'])
        listing=self.store.list('processos')
        self.assertEqual(listing['total'],2)
        record=self.store.detail(listing['itens'][0]['id'])
        self.assertEqual(record['dados']['revisao'],1)
        self.assertTrue(all(v['tipo']=='tarefas' and v['dados'].get('origem')=='revisao_interna' for v in record['vinculos']))
        self.assertTrue(record['evidencias'])
        self.assertEqual(self.store.list('prazos')['total'],0)
    def test_reimport_never_overwrites_manual_changes(self):
        p=self.process()
        payload={'processos':[{'processo':p['dados']['numero'],'detalhes':{'texto':'Dados novos'}}]}
        imported=self.store.import_corpus(payload,self.admin)
        self.assertEqual(imported['existentes'],1)
        self.assertEqual(self.store.detail(p['id'])['dados']['titulo'],'Teste')
    def test_deactivate_revokes_sessions_and_protects_last_admin(self):
        user=self.user('equipe');_,token=self.store.login('equipe','senha-equipe-123')
        self.store.update_user(user['id'],{'ativo':0},self.admin)
        with self.assertRaises(legal.AppError): self.store.auth(token)
        with self.assertRaises(legal.AppError): self.store.update_user(self.admin['id'],{'ativo':0},self.admin)
    def test_export_contains_audit_but_no_credentials(self):
        self.process();export=self.store.export(self.admin)
        self.assertTrue(export['auditoria']);self.assertNotIn('password',json.dumps(export));self.assertNotIn('sessions',export)
    def test_financial_amounts_and_document_references(self):
        p=self.process()
        finance=self.store.save('financeiro',{'dados':{'titulo':'Honorários','natureza':'receber','valor_centavos':12345,'vencimento':'2026-11-10'},'processo_id':p['id']},self.admin)
        self.assertEqual(finance['dados']['valor_centavos'],12345)
        with self.assertRaises(legal.AppError):self.store.save('financeiro',{'dados':{'titulo':'Inválido','natureza':'receber','valor_centavos':-1}},self.admin)
        doc=self.store.save('documentos',{'dados':{'titulo':'Contrato','referencia':'Pasta do escritório/contrato.pdf'},'processo_id':p['id']},self.admin)
        self.assertEqual(doc['dados']['status'],'rascunho')
        self.assertEqual(len([v for v in self.store.detail(p['id'])['vinculos'] if v['tipo']!='tarefas']),2)

    def test_login_rate_limit(self):
        for i in range(5):
            with self.assertRaises(legal.AppError):self.store.login('ana','errada')
        with self.assertRaises(legal.AppError) as err:self.store.login('ana','senha-forte-123')
        self.assertEqual(err.exception.code,429)
    def test_http_end_to_end_auth_csrf_create_and_dashboard(self):
        with patch.object(legal,'store',self.store):
            server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler)
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            base='http://127.0.0.1:'+str(server.server_port)
            def request(route,data=None,headers=None):
                req=Request(base+'/api/juridico/'+route,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
                with urlopen(req) as r:return json.load(r),r.headers
            try:
                with self.assertRaises(HTTPError) as denied:request('painel')
                self.assertEqual(denied.exception.code,401)
                result,headers=request('entrar',{'login':'ana','senha':'senha-forte-123'})
                auth={'Cookie':headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':result['csrf'],'Origin':base}
                with self.assertRaises(HTTPError) as denied:request('registros',{'tipo':'processos','dados':{'numero':'50012341220258210001'}},{'Cookie':auth['Cookie']})
                self.assertEqual(denied.exception.code,403)
                created,_=request('registros',{'tipo':'processos','dados':{'numero':'50012341220258210001'}},auth)
                self.assertEqual(created['resultado']['dados']['numero'],'5001234-12.2025.8.21.0001')
                panel,_=request('painel',headers=auth)
                self.assertEqual(panel['resultado']['contagens']['processos'],1)
                audit,_=request('auditoria',headers=auth)
                self.assertTrue(any(a['acao']=='criar' for a in audit['resultado']['itens']))
            finally:server.shutdown();server.server_close();t.join()

if __name__=='__main__':unittest.main()
