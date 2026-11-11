import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal
import mandados_triagem


CNJ = '5001234-12.2025.8.21.0001'
CPF = '111.111.111-11'
CLASS = 'Busca e Apreensão em Alienação Fiduciária'


class MandateTriageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = legal.Store(Path(self.folder.name)/'triage.sqlite3')
        self.actor = self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-aqui'},setup=True)

    def load(self, client_text, number=CNJ, category=CLASS, run='test'):
        self.store.import_corpus({'execucao':{'id':run,'fim':legal.now(),'tribunal':'TJRS'},
            'processos':[{'processo':number,'detalhes':{
                'texto':f'Nº do processo\n{number}\nClasse da ação: {category}\nCompetência Cível',
                'tabelas':[{'titulo':'Partes e Representantes','linhas':[
                    ['AUTOR','RÉU'], ['Outra parte (222.222.222-22)\nAdvogado da outra parte RS000999\nTipo de Usuário: ADVOGADO-TITULAR',
                                      'Cliente de teste ('+CPF+')\n'+client_text]]}]
            }}]}, self.actor)

    def test_shows_only_the_lawyer_linked_to_the_exact_cpf(self):
        self.load('Representante do cliente RS012345\nTipo de Usuário: ADVOGADO-TITULAR')
        record = mandados_triagem.search(self.store,{'cpf':CPF,'numero':CNJ},1)['itens'][0]
        self.assertEqual(record['numero'],CNJ)
        self.assertEqual(record['representacao'],'com_advogado')
        self.assertEqual(record['advogados'],[{'nome':'Representante do cliente','oab':'012345','uf':'RS','registro':'RS012345'}])
        self.assertNotIn(CPF,str(record))

    def test_distinguishes_missing_representation_from_explicit_absence(self):
        self.load('')
        result = mandados_triagem.search(self.store,{'cpf':CPF},1)['itens'][0]
        self.assertEqual(result['representacao'],'a_conferir')
        self.load('Sem advogado', run='next')
        result = mandados_triagem.search(self.store,{'cpf':CPF},1)['itens'][0]
        self.assertEqual(result['representacao'],'sem_advogado')
        self.assertEqual(result['advogados'],[])

    def test_older_lawyer_link_is_not_shown_as_current_after_explicit_absence(self):
        self.load('Advogada da cliente RS012345\nTipo de Usuário: ADVOGADO-TITULAR')
        self.load('Sem advogado', run='latest')
        result = mandados_triagem.search(self.store,{'cpf':CPF},1)['itens'][0]
        self.assertEqual(result['representacao'],'sem_advogado')
        self.assertEqual(result['advogados'],[])

    def test_filters_classes_courts_and_cpf(self):
        self.load('')
        self.load('',number='5001235-12.2025.8.21.0001',category='Procedimento Comum',run='other-class')
        self.load('',number='5001236-12.2025.8.24.0001',run='other-court')
        results = mandados_triagem.search(self.store,{},1)
        self.assertEqual(results['total'],1)
        self.assertEqual(results['itens'][0]['representacao'],'cpf_nao_informado')
        self.assertEqual(mandados_triagem.search(self.store,{'cpf':'333.333.333-33'},1)['total'],0)

    def test_unfiltered_results_identify_defendant_and_their_own_representation(self):
        self.load('Sem advogado')
        item = mandados_triagem.search(self.store,{'numero':CNJ},1)['itens'][0]
        self.assertEqual(len(item['partes']), 1)
        party = item['partes'][0]
        self.assertEqual((party['nome'], party['papel']), ('Cliente de teste', 'reu'))
        self.assertEqual(party['representacao'], 'sem_advogado')
        self.assertEqual(party['advogados'], [])
        self.assertNotIn(CPF, str(item))
        self.load('Representante do cliente RS012345\nTipo de Usuário: ADVOGADO-TITULAR', run='latest')
        party = mandados_triagem.search(self.store,{},1)['itens'][0]['partes'][0]
        self.assertEqual(party['representacao'], 'com_advogado')
        self.assertEqual([a['nome'] for a in party['advogados']], ['Representante do cliente'])

    def test_absence_for_a_second_party_in_the_same_cell_is_not_attributed_to_the_first(self):
        detail = {'tabelas':[{'titulo':'Partes e Representantes','linhas':[
            ['Cliente de teste ('+CPF+')\nOutra parte (222.222.222-22)\nSem advogado']
        ]}]}
        self.assertFalse(mandados_triagem.explicit_absence(detail, '11111111111'))
