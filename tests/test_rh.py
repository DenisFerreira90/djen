import sys,tempfile,unittest,json,sqlite3,io,zipfile,threading
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen,Request
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rh,juridico as legal,gestao,servidor
class RHTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'main.sqlite3')
  self.owner=self.store.create_user({'nome':'Dono','login':'dono','senha':'senha-forte-123'},setup=True)
  self.admin=self.store.create_user({'nome':'Outro admin','login':'admin','senha':'senha-forte-123','role':'administrador'},self.owner)
  self.user=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-123','role':'equipe'},self.owner)
  self.reader=self.store.create_user({'nome':'Leitor','login':'leitor','senha':'senha-forte-123','role':'leitor'},self.owner)
 def tearDown(self):self.tmp.cleanup()
 def grant(self,user,**areas):return rh.permissions(self.store,self.owner,{'usuario_id':user['id'],'areas':areas})
 def sample(self):return {'dados':{'titulo':'Entrevista confidencial','pessoa':'Pessoa fictícia','status':'agendado','inicio':'2026-10-29T10:00:00-03:00','fim':'2026-10-29T11:00:00-03:00'}}
 def denied(self,fn):
  with self.assertRaises(legal.AppError) as ctx:fn()
  self.assertEqual(ctx.exception.code,403)
 def test_default_deny_for_global_admin_and_employee(self):
  self.assertTrue(rh.access(self.store,self.owner)['proprietario'])
  for actor in (self.admin,self.user,self.reader):
   self.assertFalse(any(rh.access(self.store,actor)['areas'].values()))
   self.denied(lambda:rh.items(self.store,actor,'desligamentos'))
   self.denied(lambda:rh.backup(self.store,actor))
   self.denied(lambda:rh.history(self.store,actor))
   self.denied(lambda:rh.permissions(self.store,actor))
 def test_grant_is_per_area_and_revocation_immediate(self):
  self.grant(self.user,entrevistas='ver')
  item=rh.save(self.store,self.owner,'entrevistas',self.sample())
  self.assertEqual(rh.items(self.store,self.user,'entrevistas')['total'],1)
  self.denied(lambda:rh.save(self.store,self.user,'entrevistas',self.sample()))
  self.denied(lambda:rh.items(self.store,self.user,'desligamentos'))
  self.denied(lambda:rh.save(self.store,self.user,'desligamentos',self.sample(),item['id']))
  self.grant(self.user)
  self.denied(lambda:rh.items(self.store,self.user,'entrevistas'))
 def test_editor_cannot_self_grant_or_see_unrelated_area(self):
  self.grant(self.user,demandas='editar')
  item=rh.save(self.store,self.user,'demandas',self.sample());self.assertEqual(item['versao'],1)
  self.denied(lambda:rh.permissions(self.store,self.user,{'usuario_id':self.user['id'],'areas':{'desligamentos':'editar'}}))
  self.denied(lambda:rh.history(self.store,self.user))
 def test_reader_cannot_receive_edit_permission(self):
  with self.assertRaises(legal.AppError):self.grant(self.reader,demandas='editar')
  self.grant(self.reader,demandas='ver');self.denied(lambda:rh.save(self.store,self.reader,'demandas',self.sample()))
 def test_version_conflict_and_cross_area_id(self):
  item=rh.save(self.store,self.owner,'entrevistas',self.sample())
  with self.assertRaises(legal.AppError) as e:rh.save(self.store,self.owner,'entrevistas',{**self.sample(),'versao':0},item['id'])
  self.assertEqual(e.exception.code,409)
  updated=rh.save(self.store,self.owner,'entrevistas',{**self.sample(),'versao':1},item['id']);self.assertEqual(updated['versao'],2)
  with self.assertRaises(legal.AppError) as e:rh.save(self.store,self.owner,'demandas',{**self.sample(),'versao':2},item['id'])
  self.assertEqual(e.exception.code,404)
 def test_invalid_dates_unknown_fields_and_no_scheduled_date(self):
  for change in ({'inicio':'2026-10-29T10:00:00'},{'fim':'2026-10-28T10:00:00-03:00'},{'extra':'unknown'},{'status':'inventado'}):
   b=self.sample();b['dados'].update(change)
   with self.assertRaises(legal.AppError):rh.save(self.store,self.owner,'agenda',b)
  with self.assertRaises(legal.AppError):rh.save(self.store,self.owner,'agenda',{'dados':{'titulo':'Sem data'}})
 def test_schedule_interval_pagination_and_search(self):
  for i in range(53):
   b=self.sample();b['dados']['titulo']='Registro '+str(i);rh.save(self.store,self.owner,'agenda',b)
  self.assertEqual(len(rh.items(self.store,self.owner,'agenda')['itens']),50)
  self.assertEqual(len(rh.items(self.store,self.owner,'agenda',page=2)['itens']),3)
  self.assertEqual(rh.items(self.store,self.owner,'agenda',start='2026-10-30',end='2026-10-31')['total'],0)
  self.assertEqual(rh.items(self.store,self.owner,'agenda',search='Registro 52')['total'],1)
 def test_backup_separate_from_main_and_immutable_audit(self):
  rh.save(self.store,self.owner,'desligamentos',self.sample())
  main=gestao.backup(self.store,self.admin)
  with zipfile.ZipFile(io.BytesIO(main)) as z:
   p=Path(self.tmp.name)/'backup.sqlite';p.write_bytes(z.read('juridico.sqlite3'))
  with sqlite3.connect(p) as db:self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='rh_items'").fetchone())
  raw=rh.backup(self.store,self.owner)
  with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertIn('rh.sqlite3',z.namelist())
  self.assertTrue(rh.history(self.store,self.owner))
  with rh.connect(self.store) as db:
   with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM rh_audit')
 def test_notes_from_general_require_membership_and_rh_permission(self):
  import chat_interno as chat
  chat.rooms(self.store,self.owner)
  with self.store.connect() as db:
   room=db.execute("SELECT id FROM chat_rooms WHERE tipo='geral'").fetchone()
  if not room:
   chat.rooms(self.store,self.owner)
   with self.store.connect() as db:room=db.execute("SELECT id FROM chat_rooms WHERE tipo='geral'").fetchone()
  with self.store.connect() as db:
   mid=db.execute('INSERT INTO chat_messages(room_id,sender_id,texto,criado,nonce) VALUES(?,?,?,?,?)',(room[0],self.owner['id'],'Aviso fictício',legal.now(),'rh-test')).lastrowid
  self.denied(lambda:rh.save_general(self.store,self.user,{'mensagem_id':mid}))
  self.grant(self.user,notas='editar')
  with self.store.connect() as db:db.execute('INSERT OR IGNORE INTO chat_members(room_id,user_id) VALUES(?,?)',(room[0],self.user['id']))
  note=rh.save_general(self.store,self.user,{'mensagem_id':mid});self.assertIn('Aviso fictício',note['dados']['observacoes'])
 def test_restoring_unrelated_accounts_cannot_inherit_rh_permissions(self):
  rh.save(self.store,self.owner,'notas',self.sample())
  with self.store.connect() as db:db.execute("UPDATE rh_identity SET token='outra-base' WHERE id=1")
  self.denied(lambda:rh.items(self.store,self.owner,'notas'))
 def test_http_direct_access_csrf_and_static_file(self):
  with patch.object(legal,'store',self.store):
   server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
   try:
    result,token=self.store.login('equipe','senha-forte-123');headers={'Cookie':'juridico_session='+token}
    for route in ('rh/desligamentos','rh/backup','rh/auditoria','rh/permissoes'):
     with self.assertRaises(HTTPError) as e:urlopen(Request(base+'/api/juridico/'+route,headers=headers))
     self.assertEqual(e.exception.code,403)
    self.assertEqual(urlopen(base+'/js/rh.js').status,200)
    with self.assertRaises(HTTPError) as e:urlopen(Request(base+'/api/juridico/rh/notas',data=json.dumps(self.sample()).encode(),headers={**headers,'Content-Type':'application/json'}))
    self.assertEqual(e.exception.code,403)
   finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
