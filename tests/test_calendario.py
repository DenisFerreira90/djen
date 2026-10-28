import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,calendario as cal,chat_interno as chat,fila_coleta as queue,gestao
class CalendarTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'db.sqlite')
  self.admin=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
  self.a=self.store.create_user({'nome':'Contratação','login':'contratos','senha':'senha-forte-123','role':'equipe'},self.admin)
  self.b=self.store.create_user({'nome':'Consignados','login':'consig','senha':'senha-forte-123','role':'equipe'},self.admin)
  self.cid=next(c['id'] for c in cal.calendars(self.store,self.a) if c['owner_id']==self.a['id'])
 def tearDown(self):self.tmp.cleanup()
 def event(self,**kw):return {'titulo':'Atendimento','inicio':'2026-10-28T09:00:00-03:00','fim':'2026-10-28T10:00:00-03:00','responsavel_id':self.a['id'],**kw}
 def test_delegate_sector_and_revoke(self):
  group=chat.create(self.store,self.admin,{'tipo':'grupo','titulo':'Consignados','membros':[self.b['id']]})['id']
  with self.assertRaises(legal.AppError):cal.save(self.store,self.b,self.cid,self.event())
  cal.grants(self.store,self.admin,self.cid,[{'tipo':'setor','principal_id':group,'papel':'agendar'}])
  e=cal.save(self.store,self.b,self.cid,self.event(cliente='Cliente de teste'))
  rows=cal.events(self.store,self.a,self.cid,'2026-10-28T00:00:00-03:00','2026-10-29T00:00:00-03:00')['itens']
  self.assertEqual(rows[0]['criado_por'],self.b['id']);self.assertEqual(rows[0]['responsavel_id'],self.a['id'])
  cal.grants(self.store,self.admin,self.cid,[])
  with self.assertRaises(legal.AppError):cal.events(self.store,self.b,self.cid,'2026-10-28T00:00:00-03:00','2026-10-29T00:00:00-03:00')
 def test_conflicts_version_and_cancel(self):
  e=cal.save(self.store,self.a,self.cid,self.event())
  with self.assertRaises(legal.AppError) as error:cal.save(self.store,self.a,self.cid,self.event())
  self.assertEqual(error.exception.code,409)
  changed=cal.save(self.store,self.a,self.cid,self.event(status='cancelado',versao=e['versao']),e['id'])
  with self.assertRaises(legal.AppError) as error:cal.save(self.store,self.a,self.cid,self.event(versao=e['versao']),e['id'])
  self.assertEqual(error.exception.code,409)
  self.assertNotEqual(cal.save(self.store,self.a,self.cid,self.event())['id'],e['id'])
 def test_viewer_cannot_schedule_and_dates_need_zone(self):
  cal.grants(self.store,self.admin,self.cid,[{'tipo':'usuario','principal_id':self.b['id'],'papel':'ver'}])
  with self.assertRaises(legal.AppError):cal.save(self.store,self.b,self.cid,self.event())
  with self.assertRaises(legal.AppError):cal.timestamp('2026-10-28T09:00')
  with self.assertRaises(legal.AppError):cal.save(self.store,self.a,self.cid,self.event(fim='2026-10-28T08:00:00-03:00'))
 def test_queue_resumes_without_persisting_links(self):
  n='5004310-40.2026.8.21.0018';found={n:'https://example.test/?hash=secret'}
  self.assertEqual(queue.prepare(self.store,found,{n:'fp'},'incremental',set()),[n])
  queue.claim(self.store,n)
  self.assertEqual(queue.prepare(self.store,found,{n:'fp'},'incremental',set()),[n])
  queue.finish(self.store,n,{'gravado_no_sistema':True,'detalhes':{}})
  gestao.sync_save(self.store,n,'fp',{'gravado_no_sistema':True,'detalhes':{}},'run')
  self.assertEqual(queue.prepare(self.store,found,{n:'fp'},'incremental',set()),[])
  self.assertEqual(queue.prepare(self.store,found,{n:'fp'},'incremental',set(),True),[n])
  self.assertNotIn(b'hash=secret',self.store.path.read_bytes())
