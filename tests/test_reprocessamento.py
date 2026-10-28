import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib.request import urlopen,Request
import servidor
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal
import gestao,reprocessamento,eproc
from test_eproc_estruturado import sample,N

class TestRepair(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'base.db')
        self.actor=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
        self.case=self.store.save('processos',{'dados':{'numero':N,'titulo':'Processo importado do eproc','observacoes':'Nota manual'}},self.actor)
    def tearDown(self):self.tmp.cleanup()
    def source(self):
        payload=sample();raw=payload['processos'][0]['detalhes']
        with self.store.connect() as db:
            db.execute('INSERT INTO imports VALUES(?,?,?,?)',('legado',legal.now(),self.actor['id'],'{}'))
            db.execute('INSERT INTO evidence(import_id,case_id,source,payload) VALUES(?,?,?,?)',('legado',self.case['id'],'detalhes:0',legal.dumps(raw)))
            for i,row in enumerate(payload['paginas_da_lista'][0]['tabelas'][0]['linhas'][1:]):db.execute('INSERT INTO evidence(import_id,case_id,source,payload) VALUES(?,?,?,?)',('legado',self.case['id'],'lista:'+str(i),legal.dumps({'celulas':row})))
    def test_diagnose_and_repair_fills_legacy_without_fetch(self):
        self.source();diagnostic=reprocessamento.diagnose(self.store,self.case['id'])
        self.assertTrue(diagnostic['origem_detalhada_disponivel']);self.assertIn('orgao',diagnostic['campos_vazios'])
        with patch('urllib.request.urlopen',side_effect=AssertionError('Sem rede')):
            result=reprocessamento.repair(self.store,self.actor,self.case['id'])
        fresh=self.store.detail(self.case['id'])
        self.assertEqual(fresh['dados']['orgao'],'Vara de Teste');self.assertEqual(fresh['dados']['observacoes'],'Nota manual')
        self.assertFalse(result['consulta_tribunal_realizada']);self.assertEqual(result['detalhes_validos'],1)
        second=reprocessamento.repair(self.store,self.actor,self.case['id'])
        self.assertEqual(second['eventos'],0);self.assertEqual(second['partes'],0)
    def test_no_source_is_an_explicit_error(self):
        with self.assertRaises(legal.AppError) as error:reprocessamento.repair(self.store,self.actor,self.case['id'])
        self.assertEqual(error.exception.code,409)
        self.assertFalse(reprocessamento.diagnose(self.store,self.case['id'])['origem_detalhada_disponivel'])
    def test_repair_requires_write_permission(self):
        self.source()
        with self.assertRaises(legal.AppError) as error:reprocessamento.repair(self.store,{**self.actor,'role':'leitor'},self.case['id'])
        self.assertEqual(error.exception.code,403)
    def test_supplement_links_accept_only_read_actions_matching_case(self):
        digits=N.replace('-','').replace('.','')
        actions=[*eproc.READ_ACTIONS,'processo_agravar','certidao_narratoria_gerar','processo_movimento_consultar','incluirIntimados/selecionar','advogado/endereco_parte/index']
        snapshot={'links':[{'url':f'https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao={a}&num_processo={digits}&hash=temporario','texto':a} for a in actions]}
        selected=eproc.supplement_links(snapshot,N,list(eproc.READ_ACTIONS.values()))
        self.assertEqual(set(selected),set(eproc.READ_ACTIONS.values()))
        self.assertNotIn('certidao_narratoria_gerar',str(selected))
        self.assertEqual(eproc.supplement_links(snapshot,'5001235-12.2025.8.21.0001',['pericias']),{})
    def test_supplement_links_reject_js_host_and_invalid_port(self):
        digits=N.replace('-','').replace('.','')
        snapshot={'links':[{'url':u} for u in ['javascript:alert(1)',f'https://evil.test/eproc/controlador.php?acao=exame_listar&num_processo={digits}',f'https://eproc1g.tjrs.jus.br:evil/eproc/controlador.php?acao=exame_listar&num_processo={digits}']]}
        self.assertEqual(eproc.supplement_links(snapshot,N,['pericias']),{})
    def test_listing_is_grouped_before_detail_persistence(self):
        pages=sample()['paginas_da_lista'];grouped=eproc.case_pages(pages)
        self.assertEqual(set(grouped),{N});self.assertEqual(len(grouped[N][0]['tabelas'][0]['linhas']),3)
        initial=self.store.import_corpus({'execucao':{'id':'somente-lista'},'processos':[],'paginas_da_lista':pages},self.actor)
        fresh=self.store.detail(self.case['id'])
        self.assertEqual(fresh['dados']['classe'],'PROCEDIMENTO COMUM')
        self.assertEqual(self.store.list('prazos')['total'],2)
    def test_authenticated_api_returns_filled_process_after_repair(self):
        self.source()
        with patch.object(legal,'store',self.store):
            server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base='http://127.0.0.1:'+str(server.server_port)
            session,key=self.store.login('admin','senha-forte-123')
            headers={'Cookie':'juridico_session='+key,'X-CSRF-Token':session['csrf'],'Content-Type':'application/json'}
            try:
                with urlopen(Request(base+'/api/juridico/diagnostico/'+str(self.case['id']),headers=headers)) as r:self.assertTrue(json.load(r)['resultado']['origem_detalhada_disponivel'])
                with urlopen(Request(base+'/api/juridico/reprocessar/'+str(self.case['id']),data=b'{}',headers=headers)) as r:self.assertEqual(json.load(r)['resultado']['detalhes_validos'],1)
                with urlopen(Request(base+'/api/juridico/processos/'+N+'/dados',headers=headers)) as r:
                    data=json.load(r)['resultado'];self.assertEqual(data['dados']['orgao'],'Vara de Teste');self.assertTrue(data['vinculos'])
            finally:server.shutdown();server.server_close();worker.join()

    def test_read_complements_are_persisted_and_exported(self):
        payload=sample();payload['processos'][0]['detalhes']['complementos']=[{'tipo':'pericias','situacao':'pagina_lida_requer_conferencia','texto':'Lista de perícias de teste','tabelas':[]}]
        result=self.store.import_corpus(payload,self.actor)
        self.assertEqual(result['estruturado']['complementos'],1)
        self.assertEqual(len(self.store.export(self.actor)['complementos_origem']),1)

if __name__=='__main__':unittest.main()
