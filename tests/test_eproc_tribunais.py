import sys, tempfile, unittest, json
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import eproc, eproc_tribunais as t, eproc_relatorios as reports, eproc_estruturado as structured, juridico
RS='5001234-12.2025.8.21.0001'
SC='5001234-12.2025.8.24.0001'
def link(n,host):return {'texto':n,'url':'https://'+host+'/eproc/controlador.php?acao=processo_selecionar&hash=temporary'}
class TribunaisTests(unittest.TestCase):
 def test_hosts_actions_ports_and_number_scope(self):
  snapshot={'links':[link(SC,t.config('TJSC')['host']),link(RS,t.config('TJRS')['host']),link(RS,t.config('TJSC')['host']),link(SC,'evil.test')]}
  self.assertEqual(list(eproc.process_links(snapshot,'TJSC')),[SC]);self.assertEqual(list(eproc.process_links(snapshot)),[RS])
  url=link(SC,t.config('TJSC')['host'])['url']
  for bad in (url.replace('https:','http:'),url.replace('.jus.br/','.jus.br:8443/'),url+'&acao=movimentar',url+'#x',url.replace('/eproc/controlador.php','/other.php')):
   self.assertFalse(t.valid_url(bad,'TJSC',('processo_selecionar',)))
 def test_sessions_and_initial_entry(self):
  self.assertEqual(t.config('TJRS')['sessao'],'sessao');self.assertEqual(t.config('TJSC')['sessao'],'sessao_tjsc')
  c=eproc.Collector();c.options={'tribunal':'TJSC'};page=MagicMock(url=t.entry('TJSC'));ctx=MagicMock(pages=[page])
  with patch.object(c,'log'),patch.object(c,'wait_user'),patch.dict(eproc.os.environ,{'EPROC_USUARIO':'RS-user','EPROC_SENHA':'RS-secret','EPROC_TJSC_USUARIO':'','EPROC_TJSC_SENHA':''}):c.open_login(ctx)
  self.assertEqual(page.goto.call_args.args[0],t.entry('TJSC'));page.locator.assert_not_called()
 def test_reject_unsupported_and_mismatched_case_before_creating_run(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=eproc.Collector(tmp)
   for options in ({'tribunal':'TJXX'},{'tribunal':'TJSC','modo':'individual','numero':RS}):
    with self.assertRaises(ValueError):c.start(options=options)
   self.assertEqual(list(Path(tmp).iterdir()),[])
 def test_listing_only_selected_host(self):
  c=eproc.Collector();c.options={'tribunal':'TJSC'}
  wrong=MagicMock(url='https://eproc1g.tjrs.jus.br/eproc/controlador.php?acao=citacao_intimacao_prazo_aberto_listar')
  right=MagicMock(url='https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao=citacao_intimacao_prazo_aberto_listar')
  with patch.object(c,'surfaces',return_value=[wrong,right]):self.assertIs(c.find_list(None),right)
 def test_read_complements_and_reports_bound_to_selected_court(self):
  url='https://eproc1g.tjsc.jus.br/eproc/controlador.php?acao=audiencia_listar&num_processo='+SC.replace('-','').replace('.','')
  snap={'links':[{'texto':'Audiências','url':url}]}
  self.assertEqual(eproc.supplement_links(snap,SC,['audiencias'],'TJSC'),{'audiencias':url});self.assertFalse(eproc.supplement_links(snap,SC,['audiencias']))
  action='relatorio_processos_prazo_a_encerrar';url=url.split('?')[0]+'?acao='+action
  self.assertTrue(reports.valid_url(url,action,'TJSC'));self.assertFalse(reports.valid_url(url,action))
 def test_import_tags_sc_when_only_listing_available(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=juridico.Store(Path(tmp)/'db');actor=store.create_user({'nome':'Admin','login':'admin','senha':'senha-segura-123'},setup=True)
   page={'texto':'','tabelas':[{'titulo':'Pendentes (2 registros)','linhas':[['Processo','Evento e Prazo','Final Prazo'],[SC,'Intimação','30/10/2026'],[SC,'Outra','31/10/2026']]}]}
   result=store.import_corpus({'execucao':{'id':'sc-test'},'paginas_da_lista':[page]},actor);self.assertEqual(result['total'],1)
   with store.connect() as db:self.assertEqual(json.loads(db.execute("SELECT data FROM records WHERE kind='processos'").fetchone()[0])['tribunal'],'TJSC')
   self.assertEqual(len(structured.listing([page])),2)
   self.assertEqual(structured.detail({'processo':SC,'detalhes':{'texto':'Nº do processo '+SC}})['campos']['tribunal'],'TJSC')
 def test_blocks_stop_selected_court_without_secret_url_in_log(self):
  c=eproc.Collector();c.options={'tribunal':'TJSC'};response=MagicMock(url=t.entry('TJSC')+'?hash=secret',status=429);response.request.resource_type='document'
  with patch.object(c,'log') as log:c.observe_response(response)
  self.assertEqual(c.block_status,429);self.assertNotIn('secret',str(log.call_args_list))
if __name__=='__main__':unittest.main()
