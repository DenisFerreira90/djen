import copy,datetime as dt,sys,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.acervo import walk_acervo,node_key,merge_captures,TreeBrowser
from conectacoletor.pje import parse_snapshot
from conectacoletor import access

A='5000001-00.2026.8.17.0001'
B='5000002-00.2026.8.17.0001'
C='5000003-00.2026.8.17.0001'
PORTAL='PJE_PE_1G'


def corpus(numbers,end='01/01/2099'):
    return parse_snapshot({'texto':'','url':'https://pje.cloud.tjpe.jus.br/1g/Painel/painel_usuario/advogado.seam',
                          'tabelas':[{'linhas':[['Processo','Vencimento'],*[[n,end] for n in numbers]]}]},PORTAL,dt.date.max)


class Browser:
    def __init__(self,fail=None):self.expanded=False;self.selected=None;self.visited=[];self.fail=fail
    def open_acervo(self):pass
    def scan(self):
        nodes=[{'id':'root','label':'Caruaru - Varas','path':['Caruaru - Varas'],'count':2,'expandable':True,'expanded':self.expanded},
               {'id':'other','label':'Bezerros - Varas','path':['Bezerros - Varas'],'count':1}]
        if self.expanded:nodes += [{'id':'inbox','label':'Caixa de entrada','path':['Caruaru - Varas','Caixa de entrada'],'count':2},
                                  {'id':'empty','label':'Vazia','path':['Caruaru - Varas','Vazia'],'count':0}]
        return {'recognized':True,'nodes':nodes}
    def action(self,node,expand=False):
        if self.fail==node['id']:raise RuntimeError('Simulated unknown tree node')
        if expand:self.expanded=True
        else:self.selected=node['id'];self.visited.append(node_key(node))
    def collect(self,checkpoint,should_stop):
        result=corpus({'root':[A,B],'other':[C],'inbox':[A,B],'empty':[]}[self.selected])
        result['coleta'].update(paginacao_lista_confirmada=False,encerramento='paginacao_nao_confirmada')
        checkpoint(result)
        return result


class AcervoTests(unittest.TestCase):
    def test_authenticated_pje_route_recognizes_supplied_expedientes_td(self):
        frame=MagicMock(url='https://pje.cloud.tjpe.jus.br/1g/Painel/painel_usuario/advogado.seam')
        def locator(selector):
            result=MagicMock();result.count.return_value=int('td[id="tabExpedientes_lbl"]' in selector)
            result.nth.return_value.is_visible.return_value=True
            return result
        frame.locator.side_effect=locator
        self.assertTrue(access._pje_panel(frame))
        frame.url='https://pje.cloud.tjpe.jus.br/1g/login.seam'
        self.assertFalse(access._pje_panel(frame))
    def tab_page(self,active=False,label='Acervo'):
        page=MagicMock();tabs=MagicMock();control=MagicMock()
        page.locator.return_value=tabs;tabs.count.return_value=1;tabs.nth.return_value=control
        control.is_visible.return_value=True;control.inner_text.return_value=label
        control.get_attribute.side_effect=lambda key:('rich-tab-header rich-tab-active painel abaAcervo' if active else 'rich-tab-header rich-tab-inactive painel abaAcervo') if key=='class' else None
        return page,control

    def test_richfaces_td_tab_is_clicked_using_supplied_id(self):
        page,control=self.tab_page()
        with patch.object(TreeBrowser,'assert_page'):TreeBrowser(page,PORTAL).open_acervo()
        page.locator.assert_called_once_with('td[id="tabAcervo_lbl"], td[id$=":tabAcervo_lbl"]')
        control.click.assert_called_once_with(timeout=5000)
        self.assertEqual(page.wait_for_function.call_count,2)

    def test_active_richfaces_tab_is_not_clicked_again(self):
        page,control=self.tab_page(active=True)
        with patch.object(TreeBrowser,'assert_page'):TreeBrowser(page,PORTAL).open_acervo()
        control.click.assert_not_called()

    def test_wrong_label_at_supplied_tab_id_is_rejected(self):
        page,control=self.tab_page(label='Novo processo')
        with patch.object(TreeBrowser,'assert_page'):
            with self.assertRaises(RuntimeError):TreeBrowser(page,PORTAL).open_acervo()
        control.click.assert_not_called()

    def test_every_district_and_box_visited_future_cases_kept_and_deduplicated(self):
        browser=Browser();saved=[]
        result=walk_acervo(browser,PORTAL,checkpoint=lambda p:saved.append(copy.deepcopy(p)))
        self.assertEqual(len(browser.visited),4)
        self.assertEqual({r['processo'] for r in result['processos']},{A,B,C})
        self.assertEqual(result['coleta']['adiados'],0)
        self.assertTrue(result['acervo']['navegacao_total_confirmada'])
        record=next(r for r in result['processos'] if r['processo']==A)
        self.assertEqual(record['localizacoes_acervo'],['Caruaru - Varas','Caruaru - Varas / Caixa de entrada'])
        self.assertTrue(all(not r['detalhes'] for r in result['processos']))
        self.assertTrue(saved)

    def test_unknown_tree_is_pending_not_successful_empty_acervo(self):
        browser=Browser();browser.scan=lambda:{'recognized':False,'reason':'arvore_ausente_ou_ambigua'}
        result=walk_acervo(browser,PORTAL)
        self.assertFalse(result['acervo']['navegacao_total_confirmada'])
        self.assertEqual(result['acervo']['encerramento'],'arvore_ausente_ou_ambigua')
        self.assertEqual(result['coleta']['estado'],'parcial')

    def test_failed_node_does_not_erase_other_districts(self):
        result=walk_acervo(Browser(fail='other'),PORTAL)
        self.assertEqual({r['processo'] for r in result['processos']},{A,B})
        self.assertEqual(result['acervo']['nos']['Bezerros - Varas']['estado'],'leitura_nao_confirmada')
        self.assertFalse(result['acervo']['navegacao_total_confirmada'])

    def test_pause_preserves_accumulated_pages_and_reports_incomplete(self):
        browser=Browser()
        result=walk_acervo(browser,PORTAL,should_stop=lambda:len(browser.visited)>=1)
        self.assertEqual(len(result['processos']),2)
        self.assertEqual(result['acervo']['encerramento'],'pausa_ou_limite_tempo')
        self.assertFalse(result['acervo']['navegacao_total_confirmada'])

    def test_counter_mismatch_and_unknown_pagination_are_pending(self):
        browser=Browser();original=browser.collect
        def collect(checkpoint,should_stop):
            payload=original(checkpoint,should_stop)
            if browser.selected=='other':payload['processos']=[]
            return payload
        browser.collect=collect
        result=walk_acervo(browser,PORTAL)
        self.assertEqual(result['acervo']['nos']['Bezerros - Varas']['estado'],'contagem_divergente')
        self.assertFalse(result['acervo']['navegacao_total_confirmada'])

    def test_checkpoint_failure_aborts_before_next_box(self):
        browser=Browser()
        def fail(_):raise OSError('Disk full')
        with self.assertRaises(OSError):walk_acervo(browser,PORTAL,checkpoint=fail)
        self.assertEqual(browser.visited,[])

    def test_node_limit_does_not_mark_acervo_complete(self):
        result=walk_acervo(Browser(),PORTAL,max_nodes=1)
        self.assertEqual(result['acervo']['encerramento'],'limite_nos')
        self.assertFalse(result['acervo']['navegacao_total_confirmada'])

    def test_ambiguous_same_named_siblings_are_not_silently_skipped(self):
        browser=Browser()
        browser.scan=lambda:{'recognized':True,'nodes':[{'id':'a','label':'Comarca A'},{'id':'b','label':'Comarca A'}]}
        result=walk_acervo(browser,PORTAL)
        self.assertFalse(result['acervo']['navegacao_total_confirmada'])
        self.assertEqual(result['acervo']['encerramento'],'caminhos_duplicados_na_arvore')

    def test_source_corpora_are_not_mutated_by_merge(self):
        original=corpus([A]);before=copy.deepcopy(original)
        result=merge_captures({'Caruaru':original},PORTAL,{'nos':{}},'test')
        self.assertEqual(original,before)
        self.assertEqual(result['paginas_da_lista'][0]['localizacao_acervo'],'Caruaru')

    def test_threshold_counts_the_whole_portal_not_each_district(self):
        nums=[f'{n:07d}-00.2026.8.17.0001' for n in range(6000000,6000501)]
        captures={'Comarca A':corpus(nums[:300],end=''),'Comarca B':corpus(nums[300:500],end='')}
        captures['Comarca C']=corpus([nums[500]])
        result=merge_captures(captures,PORTAL,{'nos':{}},'test',dt.date(2026,11,26))
        self.assertEqual(result['coleta']['descobertos'],501)
        self.assertEqual(result['coleta']['lidos'],500)
        self.assertEqual(result['coleta']['adiados'],1)
        del captures['Comarca B']
        small=merge_captures(captures,PORTAL,{'nos':{}},'test',dt.date(2026,11,26))
        self.assertEqual(small['coleta']['adiados'],0)
        self.assertEqual(small['coleta']['lidos'],301)
