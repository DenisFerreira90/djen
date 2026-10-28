import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal
import eproc_estruturado as parser
import gestao
N='5001234-12.2025.8.21.0001'


def sample():
    return {'execucao':{'id':'amostra','fim':legal.now(),'esperados':2},'processos':[{'processo':N,'situacao':'pagina_lida_requer_conferencia','detalhes':{
      'texto':f'Consulta Processual - Detalhes do Processo\nNº do processo\n{N}\nClasse da ação:\nPROCEDIMENTO COMUM\nCompetência\nCível\nData de autuação:\n01/10/2026 10:30:45\nSituação\nMOVIMENTO\nÓrgão Julgador:\nVara de Teste\nJuiz(a):\nPessoa Magistrada\nAssuntos',
      'tabelas':[{'titulo':'Partes e Representantes','linhas':[['AUTOR','RÉU'],['Pessoa A (111.111.111-11) - Pessoa Física\nProfissional A RS012345\nTipo de Usuário: ADVOGADO-TITULAR','Pessoa B (222.222.222-22) - Pessoa Física\nProfissional B (DPE) DPE-123456\nTipo de Usuário: PROCURADOR']]},
       {'titulo':'Configurar monitores','linhas':[['Evento','Data/Hora','Descrição','Usuário','Documentos'],['11','20/10/2026 12:30:44','Expedida/certificada a intimação eletrônica\n(AUTOR - Pessoa A)\nPrazo: 1 dia Status:ABERTO\nData inicial da contagem do prazo: 28/10/2026 00:00:00\nData final: 28/10/2026 23:59:59','Usuário na origem','REF1'],['10','19/10/2026 12:30:00','Expedida/certificada a intimação eletrônica\n(RÉU - Pessoa B)\nPrazo: 5 dias Status:FECHADO (ciência)\nData inicial da contagem do prazo: 20/10/2026 00:00:00\nData final: 27/10/2026 23:59:59','Outro usuário','']]}]}}],
      'paginas_da_lista':[{'tabelas':[{'titulo':'Lista de Citações','linhas':[['','Processo','Classe','Assunto','Evento e Prazo','Data envio requisição','Início Prazo','Final Prazo'],['',N,'PROCEDIMENTO COMUM','Assunto explícito','Intimação\n1 dia','20/10/2026 12:30:44','28/10/2026 00:00:00','28/10/2026 23:59:59'],['',N,'PROCEDIMENTO COMUM','Assunto explícito','Intimação\n1 dia','20/10/2026 12:30:44','28/10/2026 00:00:00','28/10/2026 23:59:59']]}]}]}

class TestEprocStructure(unittest.TestCase):
    def test_fields_roles_and_seconds_are_explicit(self):
        d=parser.detail(sample()['processos'][0]);self.assertTrue(d['validado'])
        self.assertEqual(d['campos']['orgao'],'Vara de Teste')
        self.assertEqual(d['campos']['autuacao'],'2026-10-01T10:30:45')
        self.assertEqual([p['papel'] for p in d['partes']],['autor','advogado','reu','defensor'])
        self.assertEqual(d['partes'][1]['representa_indice'],0)
        self.assertEqual(d['partes'][3]['representa_indice'],2)
        self.assertEqual(d['prazos'][0]['vencimento'],'2026-10-28T23:59:59')
        self.assertEqual(d['prazos'][1]['status'],'encerrado_na_origem')
    def test_related_number_does_not_validate_wrong_main_process(self):
        r=sample()['processos'][0];r['detalhes']['texto']=r['detalhes']['texto'].replace(N,'5001235-12.2025.8.21.0001')+'\nRelacionado: '+N
        self.assertFalse(parser.detail(r)['validado'])
    def test_repeated_intimations_do_not_become_missing_processes(self):
        rows=parser.listing(sample()['paginas_da_lista']);self.assertEqual(len(rows),2)
        self.assertEqual(len({r['numero'] for r in rows}),1)
    def test_import_keeps_account_agenda_separate_from_other_parties(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=legal.Store(Path(tmp)/'legal.sqlite3')
            actor=store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-aqui'},setup=True)
            result=store.import_corpus(sample(),actor)
            self.assertEqual(result['estruturado']['registros_lista'],2)
            self.assertEqual(result['estruturado']['eventos'],2)
            self.assertEqual(store.list('prazos')['total'],2)
            agenda=gestao.agenda(store)['itens'];self.assertEqual(len(agenda),2)
            self.assertTrue(all(r['dados']['escopo']=='lista_da_conta' for r in agenda))
            with store.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='prazos'").fetchone()[0],4)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM source_events').fetchone()[0],2)
            case=store.list('processos')['itens'][0]
            lawyers=[p for p in store.detail(case['id'])['vinculos'] if p['tipo']=='partes' and p['dados']['papel'] in ('advogado','defensor')]
            self.assertEqual(len(lawyers),2)
            self.assertTrue(all(p['dados']['representa_id'] for p in lawyers))
            again=store.import_corpus(sample(),actor)
            # Sample time is generated per call; the semantic corpus hash remains the same.
            self.assertTrue(again['repetido']);self.assertEqual(store.list('prazos')['total'],2)

if __name__=='__main__':unittest.main()
