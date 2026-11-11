import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,painel_operacional as panel
from origem_registros import provenance,stable_link


class OriginTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db')
  self.admin=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
 def tearDown(self):self.tmp.cleanup()
 def case(self,**extra):
  return self.store.save('processos',{'dados':{'numero':'5000001-00.2026.8.17.0001','titulo':'Teste','tribunal':'TJPE','sistema_origem':'pje','grau':'2','comarca':'Recife','orgao':'Vara informada',**extra}},self.admin)
 def test_grade_and_system_are_not_inferred_from_cnj(self):
  o=provenance({'numero':'5000001-00.2026.8.17.0000'})
  self.assertEqual(o['tribunal'],'TJPE');self.assertEqual(o['grau'],'Não informado');self.assertEqual(o['sistema'],'Não informado');self.assertFalse(o['url'])
 def test_correct_portal_grade_and_registered_direct_link(self):
  data=self.case()['dados'];o=provenance(data,case_id=1)
  self.assertEqual(o['url'],'https://pje.cloud.tjpe.jus.br/2g/');self.assertEqual(o['tipo_link'],'portal');self.assertFalse(o['origem_pendente'])
  data['link_origem']='https://pje.cloud.tjpe.jus.br/2g/Processo/ConsultaProcesso/Detalhe/listAutosDigitais.seam?idProcesso=123'
  self.assertEqual(provenance(data)['tipo_link'],'origem')
 def test_temporary_unsafe_and_wrong_grade_urls_do_not_redirect(self):
  for value in ('javascript:alert(1)','https://example.com/case','https://pje.cloud.tjpe.jus.br/2g/login.seam','https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=processo_consultar&hash=PRIVATE'):
   self.assertIsNone(stable_link(value))
  data=self.case()['dados'];data['link_origem']='https://pje.cloud.tjpe.jus.br/1g/Processo/ConsultaProcesso/Detalhe/listAutosDigitais.seam?idProcesso=123'
  o=provenance(data);self.assertFalse(o['url']);self.assertIn('origem divergente',o['campos_pendentes'])
 def test_djen_publication_does_not_inherit_case_pje_link(self):
  o=provenance({'origem':'djen'},self.case()['dados'],1)
  self.assertEqual(o['sistema'],'DJEN');self.assertEqual(o['url'],'https://comunica.pje.jus.br/');self.assertEqual(o['grau'],'Publicação nacional')
 def test_205_deadlines_are_all_available_by_page_and_totals_are_complete(self):
  case=self.case();today=legal.now()[:10]
  for n in range(205):self.store.save('prazos',{'processo_id':case['id'],'dados':{'titulo':'Prazo '+str(n),'vencimento':today}},self.admin)
  pages=[panel.report(self.store,self.admin,'fatais_hoje',n) for n in (1,2,3)]
  self.assertEqual([len(p['listas']['fatais_hoje']) for p in pages],[100,100,5])
  ids=[r['id'] for p in pages for r in p['listas']['fatais_hoje']];self.assertEqual(len(set(ids)),205)
  self.assertTrue(all(p['contagens']['fatais_hoje']==205 for p in pages));self.assertEqual(pages[0]['origens_pendentes']['fatais_hoje'],0)
 def test_mandate_deadline_remains_in_general_today_but_indication_alone_is_not_fatal(self):
  import mandados
  case=self.case(classe='Busca e apreensão');today=legal.now()[:10]
  self.store.save('prazos',{'processo_id':case['id'],'dados':{'titulo':'Prazo','vencimento':today}},self.admin)
  with self.store.connect() as db:
   mandados.schema(db);db.execute('INSERT INTO mandate_alerts(case_id,numero,evento,trecho,categoria,criado) VALUES(?,?,?,?,?,?)',(case['id'],case['dados']['numero'],'1','Indício','revisar_mencao',legal.now()))
  d=panel.report(self.store,self.admin)
  self.assertEqual(d['contagens']['fatais_hoje'],1);self.assertEqual(d['contagens']['mandados_fatais_hoje'],1)
  self.assertEqual(d['contagens']['mandados_pendentes'],1)
  with self.store.connect() as db:db.execute("DELETE FROM records WHERE kind='prazos'")
  d=panel.report(self.store,self.admin);self.assertEqual(d['contagens']['mandados_fatais_hoje'],0);self.assertEqual(d['contagens']['mandados_pendentes'],1)
 def test_new_import_adds_confirmed_connector_grade_without_overwriting_manual_metadata(self):
  number='5000001-00.2026.8.24.0001'
  payload={'execucao':{'id':'test-origin','tribunal':'TJSC','sistema':'eproc'},'processos':[{'processo':number,'detalhes':None}], 'paginas_da_lista':[]}
  self.store.import_corpus(payload,self.admin)
  case=self.store.list('processos',number)['itens'][0]
  self.assertEqual(case['dados']['grau'],'1');self.assertEqual(case['dados']['portal_origem'],'EPROC_TJSC_1G')
  self.store.save('processos',{'dados':{'grau':'2'},'versao':case['versao']},self.admin,case['id'])
  payload['execucao']['id']='test-origin-next';self.store.import_corpus(payload,self.admin)
  self.assertEqual(self.store.detail(case['id'])['dados']['grau'],'2')
 def test_bad_page_and_private_financial_group_are_rejected(self):
  team=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},self.admin)
  with self.assertRaises(legal.AppError):panel.report(self.store,team,'financeiro_vencido',1)
  with self.assertRaises(legal.AppError):panel.report(self.store,self.admin,'fatais_hoje',0)
