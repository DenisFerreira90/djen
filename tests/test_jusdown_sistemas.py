import tempfile,json,unittest
from pathlib import Path
import jusdown
class JudicialSystems(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'status.sqlite3';self.calls=[]
  def check(row):
   self.calls.append(row['url'])
   return {'id':row['id'],'estado':'respondeu','verificado_em':jusdown.now(),'latencia_ms':1,'http':200,'conteudos':[]}
  self.m=jusdown.Monitor(self.path,check);self.actor={'id':1,'role':'administrador'}
 def tearDown(self):self.tmp.cleanup()
 def test_families_and_national_scope(self):
  rows=self.m.catalog();self.assertTrue({'eproc','e-SAJ','PJe','PDPJ'}<={r['familia'] for r in rows})
  pdpj=next(r for r in rows if r['familia']=='PDPJ');self.assertEqual(pdpj['grau'],'nacional');self.assertEqual(pdpj['tribunal'],'PDPJ')
  self.assertEqual(jusdown.system_family('E-SAJ'),'e-SAJ');self.assertEqual(jusdown.system_family('Portal eproc · informações'),'eproc')
 def test_al_second_degree_is_not_probed_or_reported_down(self):
  d=self.m.status();row=next(r for r in d['itens'] if r['tribunal']=='TJAL' and r['grau']=='2')
  self.assertIsNone(row['url']);self.assertEqual(row['estado'],'em_implantacao');self.assertEqual(row['cor'],'cinza')
  self.assertEqual(d['resumo']['em_implantacao'],1)
  self.m.run('TJAL');self.assertNotIn(None,self.calls);self.assertFalse(self.m.error)
  self.assertTrue(any('www2.tjal.jus.br/esaj' in u for u in self.calls))
 def test_al_migration_preserves_removal_and_custom_information_source(self):
  self.m.status()
  with self.m.db() as c:
   key,raw=next((k,v) for k,v in c.execute('SELECT id,data FROM portal_catalog') if json.loads(v).get('url')=='https://eproc1g.tjal.jus.br/')
   row=json.loads(raw);row['url_informacoes']='https://www.tjal.jus.br/'
   c.execute('UPDATE portal_catalog SET data=?,removed=1 WHERE id=?',(json.dumps(row),key));c.execute("DELETE FROM catalog_revisions WHERE id='v46-al'")
  self.assertFalse(any(r['id']==key for r in self.m.catalog()))
  with self.m.db() as c:
   row=json.loads(c.execute('SELECT data FROM portal_catalog WHERE id=?',(key,)).fetchone()[0]);self.assertEqual(row['url_informacoes'],'https://www.tjal.jus.br/eproc')
   row.update(url_informacoes='https://www.tjal.jus.br/fonte-escolhida',alterado_por=1)
   c.execute('UPDATE portal_catalog SET data=?,removed=0 WHERE id=?',(json.dumps(row),key));c.execute("DELETE FROM catalog_revisions WHERE id='v46-al'")
  self.assertEqual(next(r for r in self.m.catalog() if r['id']==key)['url_informacoes'],'https://www.tjal.jus.br/fonte-escolhida')
 def test_admin_can_register_planning_without_fake_endpoint(self):
  body={'tribunal':'TJTEST','nome':'Em implantação','sistema':'eproc','grau':'2','url_informacoes':'https://www.tjal.jus.br/eproc','situacao_implantacao':'em_implantacao'}
  key=self.m.add_portal(body,self.actor)['id'];r=next(r for r in self.m.status()['itens'] if r['id']==key)
  self.assertEqual(r['estado'],'em_implantacao');self.assertIsNone(r['url'])
  with self.assertRaises(ValueError):self.m.add_portal({**body,'sistema':'PDPJ','familia':'PDPJ'},self.actor)
 def test_scheduled_report_includes_planning_with_no_fake_check(self):
  slot='2026-11-04T08:00-03:00'
  with self.m.db() as c:c.execute('INSERT INTO daily_runs VALUES (?,?)',(slot,json.dumps({'slot':slot,'tribunal':'TJAL','estado':'executando'})))
  self.m.run('TJAL',slot)
  report=self.m.routine_status(self.actor,slot,True)[0]
  plan=next(r for r in report['portais'] if r['grau']=='2')
  self.assertEqual(plan['estado'],'em_implantacao');self.assertNotIn('http',plan);self.assertNotIn('verificado_em',plan)
