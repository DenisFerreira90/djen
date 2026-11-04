from pathlib import Path
import tempfile,unittest,json,datetime as dt
from unittest.mock import patch
import urllib.error
import jusdown
from jusdown_catalogo import CATALOG,COURTS
class JusdownTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'s.sqlite3';self.actor={'id':1,'role':'administrador'}
  self.version=1;self.failed=False
  self.m=jusdown.Monitor(self.path,self.check)
 def tearDown(self):self.temp.cleanup()
 def key(self,court='TJRS',degree='1'):return next(r['id'] for r in CATALOG if r['tribunal']==court and r['grau']==degree)
 def check(self,r):return dict(id=r['id'],estado='sem_resposta' if self.failed else 'respondeu',verificado_em=jusdown.now(),http=None if self.failed else 200,latencia_ms=12,conteudos=[{'url':'https://www.tjac.jus.br/noticia','titulo':'Nova versão '+str(self.version)}])
 def test_focused_catalog_and_sanitization(self):
  self.assertEqual(len(CATALOG),35);self.assertEqual(len(COURTS),24)
  for r in CATALOG:self.assertNotIn('?',r['url']);self.assertNotIn('#',r['url'])
  self.assertNotIn('TRT4',{r['tribunal'] for r in CATALOG})
  import eproc_tribunais
  self.assertEqual(eproc_tribunais.ATIVOS,{'TJRS'})
 def test_selected_scope_and_sources(self):
  calls=[];self.m.check=lambda r:(calls.append(r['tribunal']) or self.check(r))
  self.m.run('TJAC');self.assertEqual(set(calls),{'TJAC'})
  self.assertEqual(self.m.status()['resumo']['instancias'],35)
 def test_baseline_new_and_unchanged(self):
  self.m.run('TJAC');r=next(x for x in self.m.status()['itens'] if x['tribunal']=='TJAC');self.assertEqual(r['informacoes']['estado'],'primeira_leitura');self.assertFalse(r['informacoes']['novidades'])
  self.m.run('TJAC');r=next(x for x in self.m.status()['itens'] if x['tribunal']=='TJAC');self.assertEqual(r['informacoes']['estado'],'sem_novidades_detectadas')
  self.version=2;self.m.run('TJAC');r=next(x for x in self.m.status()['itens'] if x['tribunal']=='TJAC');self.assertEqual(r['informacoes']['estado'],'novidades');self.assertEqual(len(r['informacoes']['novidades']),1)
 def test_failed_reading_not_no_updates(self):
  self.m.run('TJAC');self.failed=True;self.m.run('TJAC')
  r=next(x for x in self.m.status()['itens'] if x['tribunal']=='TJAC');self.assertEqual(r['informacoes']['estado'],'leitura_nao_confirmada')
 def test_empty_reading_not_no_updates(self):
  self.m.check=lambda r:{**self.check(r),'conteudos':[]};self.m.run('TJAC')
  r=next(x for x in self.m.status()['itens'] if x['tribunal']=='TJAC');self.assertEqual(r['informacoes']['estado'],'leitura_sem_informes')
 def test_add_remove_persistent_without_reappearing(self):
  body={'tribunal':'TJTEST','nome':'Meu portal','sistema':'eproc','grau':'1','url':'https://www.tjac.jus.br/novo/','url_informacoes':'https://www.tjac.jus.br/eproc/'}
  key=self.m.add_portal(body,self.actor)['id'];self.assertTrue(any(r['id']==key for r in self.m.catalog()))
  self.m.remove_portal(key,self.actor);self.assertFalse(any(r['id']==key for r in jusdown.Monitor(self.path).catalog()))
  seed=self.key();self.m.remove_portal(seed,self.actor);self.assertFalse(any(r['id']==seed for r in jusdown.Monitor(self.path).catalog()))
  self.m.add_portal(body,self.actor);self.assertTrue(any(r['id']==key for r in self.m.catalog()))
 def test_custom_portal_admin_and_session_validation(self):
  body={'tribunal':'TJAC','nome':'X','sistema':'eproc','grau':'1','url':'https://www.tjac.jus.br/?hash=secret'}
  with self.assertRaises(ValueError):self.m.add_portal(body,self.actor)
  with self.assertRaises(ValueError):self.m.add_portal(body,{'id':2,'role':'leitor'})
  with self.assertRaises(ValueError):jusdown.public_url('https://example.org/')
 def test_inactive_hidden_staff_and_reports(self):
  self.m.save_note({'tribunal':'TJRS','texto':'Interno'},self.actor)
  with self.m.db() as c:c.execute('INSERT INTO daily_runs VALUES (?,?)',('x',json.dumps({'tribunal':'TJRS','manual':True,'portais':[{'id':self.key(),'tribunal':'TJRS'}]})))
  self.m.set_court('TJRS',False,self.actor)
  d=self.m.status({'id':2,'role':'leitor'});self.assertFalse(any(r['tribunal']=='TJRS' for r in d['itens']));self.assertFalse(d['lembretes']);self.assertFalse(d['rotinas']);self.assertEqual(d['resumo']['tribunais'],23)
  self.m.set_court('TJRS',True,self.actor);self.assertTrue(any(r['tribunal']=='TJRS' for r in self.m.status()['itens']))
 def test_inactive_not_requested(self):
  self.m.set_court('TJRS',False,self.actor)
  with self.assertRaises(ValueError):self.m.request('TJRS')
 def test_color_rules(self):
  fail={'estado':'sem_resposta','http':None};yellow=jusdown.color(fail);red=jusdown.color(fail,yellow)
  self.assertEqual(yellow['cor'],'amarelo');self.assertEqual(red['cor'],'vermelho');self.assertEqual(jusdown.color(fail,yellow,True)['cor'],'amarelo')
  self.assertEqual(jusdown.color({'estado':'acesso_restrito'})['cor'],'cinza')
  recovered=jusdown.color({'estado':'respondeu'},red);self.assertEqual(recovered['cor'],'amarelo');self.assertEqual(jusdown.color({'estado':'respondeu'},recovered)['cor'],'verde')
 def test_private_target_blocked(self):
  with patch('jusdown.socket.getaddrinfo',return_value=[(0,0,0,'',('127.0.0.1',443))]):
   with self.assertRaises(ValueError):jusdown.validate_url('https://www.tjac.jus.br/')
 def test_content_and_official_table(self):
  html='<a href="/noticia">Nova versão e atualização do eproc</a><a href="/?hash=secret">Nova versão deve ser ignorada</a><table><tr><td>23.10.2026</td><td>08:30</td><td>Custas temporariamente indisponíveis</td></tr></table>'
  rows=jusdown.public_content(html,'https://www.tjac.jus.br/');self.assertEqual(len(rows),2);self.assertIn('23.10.2026',rows[0]['titulo'])
 def test_08_1230_once_across_restarts(self):
  t=dt.datetime(2026,11,3,7,59,tzinfo=jusdown.TZ)
  with patch('jusdown.threading.Thread') as thread:
   self.m.tick(t);self.assertFalse(thread.called)
   self.m.tick(t.replace(hour=8,minute=0));self.assertEqual(thread.call_count,1)
   args=thread.call_args.kwargs['args']
  self.m.run(*args)
  with patch('jusdown.threading.Thread') as thread:
   self.m.tick(t.replace(hour=8,minute=1));self.assertFalse(thread.called)
   other=jusdown.Monitor(self.path,self.check);other.tick(t.replace(hour=12,minute=30));self.assertEqual(thread.call_count,1)
   args=thread.call_args.kwargs['args']
  other.run(*args);self.assertEqual(len(other.routine_status()),2)
 def test_missed_not_fabricated(self):
  with patch('jusdown.threading.Thread') as thread:self.m.tick(dt.datetime(2026,11,3,14,0,tzinfo=jusdown.TZ));self.assertFalse(thread.called)
  self.assertEqual([r['estado'] for r in self.m.routine_status()],['nao_executada','nao_executada'])
 def test_busy_does_not_overlap_or_consume_window(self):
  self.m.busy=True
  with patch('jusdown.threading.Thread') as thread:self.m.tick(dt.datetime(2026,11,3,8,0,tzinfo=jusdown.TZ));self.assertFalse(thread.called)
  self.assertFalse(self.m.routine_status())
 def test_pause_keeps_manual_available(self):
  self.m.configure(False)
  with patch('jusdown.threading.Thread') as thread:
   self.m.tick(dt.datetime(2026,11,3,8,0,tzinfo=jusdown.TZ));self.assertFalse(thread.called)
   self.assertTrue(self.m.request('TJAC'));self.assertTrue(thread.called)
 def test_reading_valid_until_next_round(self):
  checked=dt.datetime(2026,11,3,8,5,tzinfo=jusdown.TZ)
  self.assertFalse(jusdown.reading_stale(checked,checked.replace(hour=11)))
  self.assertTrue(jusdown.reading_stale(checked,checked.replace(hour=13)))
 def test_bad_db_does_not_abort_server_start(self):
  self.path.write_text('not sqlite')
  with patch('jusdown.threading.Thread') as thread:self.m.start();self.assertTrue(thread.called);self.assertIsNotNone(self.m.error)
