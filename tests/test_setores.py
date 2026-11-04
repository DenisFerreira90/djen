from pathlib import Path
import tempfile,unittest
import juridico as legal
import setores,calendario,chat_interno
class SectorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'legal.sqlite3')
  self.admin=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-teste'},setup=True)
  self.sec=self.store.create_user({'nome':'Secretaria','login':'sec','senha':'senha-forte-teste','role':'equipe'},self.admin)
  self.rel=self.store.create_user({'nome':'Relacionamento','login':'rel','senha':'senha-forte-teste','role':'equipe'},self.admin)
  self.other=self.store.create_user({'nome':'Outro','login':'outro','senha':'senha-forte-teste','role':'equipe'},self.admin)
 def tearDown(self):self.tmp.cleanup()
 def room(self,code):return next(s for s in setores.directory(self.store,self.admin)['setores'] if s['codigo']==code)['room_id']
 def agenda(self):return next(c for c in calendario.calendars(self.store,self.admin) if c.get('setor')=='relacionamento')['id']
 def test_seed_once_15_private_groups_and_calendar(self):
  setores.bootstrap(self.store);setores.bootstrap(self.store)
  data=setores.directory(self.store,self.admin);self.assertEqual(len(data['setores']),15)
  self.assertEqual(len({s['room_id'] for s in data['setores']}),15)
  self.assertTrue(all(s['membros']==[self.admin['id']] for s in data['setores']))
  self.assertEqual(len([c for c in calendario.calendars(self.store,self.admin) if c.get('setor')=='relacionamento']),1)
  self.assertFalse(any(r['tipo']=='grupo' for r in chat_interno.rooms(self.store,self.other)))
 def test_reuse_group_preserve_read_history_and_members(self):
  group=chat_interno.create(self.store,self.admin,{'tipo':'grupo','titulo':'Financeiro','membros':[self.other['id']]})
  setores.bootstrap(self.store)
  self.assertEqual(self.room('financeiro'),group['id'])
  self.assertIn(self.other['id'],next(s for s in setores.directory(self.store,self.admin)['setores'] if s['codigo']=='financeiro')['membros'])
 def test_only_explicit_secretariat_can_create_related_agenda(self):
  setores.bootstrap(self.store)
  with self.assertRaises(legal.AppError) as e:calendario.create(self.store,self.sec,'Agenda nova','relacionamento')
  self.assertEqual(e.exception.code,403)
  setores.grant(self.store,self.admin,{'user_id':self.sec['id'],'secretaria':True})
  created=calendario.create(self.store,self.sec,'Agenda nova','relacionamento')
  self.assertTrue(created['id']);self.assertTrue(setores.access(self.store,self.sec)['pode_criar_agenda_relacionamento'])
  with self.assertRaises(legal.AppError):calendario.create(self.store,self.sec,'RH','rh')
  setores.grant(self.store,self.admin,{'user_id':self.sec['id'],'secretaria':False})
  with self.assertRaises(legal.AppError):calendario.create(self.store,self.sec,'Nova','relacionamento')
 def test_reader_capability_does_not_escape_read_only(self):
  reader=self.store.create_user({'nome':'Leitor','login':'leitor','senha':'senha-forte-teste','role':'leitor'},self.admin)
  setores.bootstrap(self.store);setores.grant(self.store,self.admin,{'user_id':reader['id'],'secretaria':True})
  self.assertFalse(setores.access(self.store,reader)['pode_criar_agenda_relacionamento'])
  with self.assertRaises(legal.AppError):calendario.create(self.store,reader,'Agenda','relacionamento')
 def test_calendar_access_and_responsible_scope(self):
  setores.bootstrap(self.store);cid=self.agenda()
  setores.members(self.store,self.admin,'relacionamento',[self.rel['id']])
  setores.grant(self.store,self.admin,{'user_id':self.sec['id'],'secretaria':True})
  self.assertEqual(next(c['permissao'] for c in calendario.calendars(self.store,self.rel) if c['id']==cid),'ver')
  self.assertEqual(next(c['permissao'] for c in calendario.calendars(self.store,self.sec) if c['id']==cid),'agendar')
  self.assertNotIn(cid,{c['id'] for c in calendario.calendars(self.store,self.other)})
  self.assertIn(self.rel['id'],{p['id'] for p in calendario.assignees(self.store,self.sec,cid)})
  self.assertNotIn(self.other['id'],{p['id'] for p in calendario.assignees(self.store,self.sec,cid)})
  body={'titulo':'Atendimento','inicio':'2026-11-05T09:00:00-03:00','fim':'2026-11-05T09:30:00-03:00','responsavel_id':self.rel['id'],'cliente':'Cliente de teste','contato':'Contato de teste'}
  event=calendario.save(self.store,self.sec,cid,body);self.assertTrue(event['id'])
  with self.assertRaises(legal.AppError) as e:calendario.save(self.store,self.sec,cid,body)
  self.assertEqual(e.exception.code,409)
  with self.assertRaises(legal.AppError):calendario.save(self.store,self.rel,cid,{**body,'inicio':'2026-11-05T10:00:00-03:00','fim':'2026-11-05T10:30:00-03:00'})
 def test_membership_changes_calendar_access_and_owner_only(self):
  setores.bootstrap(self.store);cid=self.agenda()
  with self.assertRaises(legal.AppError):setores.members(self.store,self.other,'relacionamento',[self.other['id']])
  with self.assertRaises(legal.AppError):setores.grant(self.store,self.sec,{'user_id':self.sec['id'],'secretaria':True})
  setores.members(self.store,self.admin,'relacionamento',[self.rel['id']]);self.assertIn(cid,{c['id'] for c in calendario.calendars(self.store,self.rel)})
  setores.members(self.store,self.admin,'relacionamento',[]);self.assertNotIn(cid,{c['id'] for c in calendario.calendars(self.store,self.rel)})
 def test_seed_does_not_reset_delegations(self):
  setores.bootstrap(self.store);cid=self.agenda();calendario.grants(self.store,self.admin,cid,[])
  setores.bootstrap(self.store);self.assertEqual(calendario.grants(self.store,self.admin,cid)['permissoes'],[])
 def test_chat_only_bootstrap_does_not_create_calendars(self):
  setores.bootstrap(self.store,with_calendar=False)
  with self.store.connect() as db:self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='calendars'").fetchone())
