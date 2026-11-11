import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import juridico as legal,estoque

class InventoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=legal.Store(Path(self.tmp.name)/'app.db')
  self.admin=self.store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-teste'},setup=True)
  self.user=self.store.create_user({'nome':'Equipe','login':'equipe','senha':'senha-forte-teste','role':'equipe'},self.admin)
 def tearDown(self):self.tmp.cleanup()
 def grant(self,ti='',other='',user=None):return estoque.permissions(self.store,self.admin,{'user_id':(user or self.user)['id'],'permissoes':{'ti':ti,'escritorio_limpeza':other}})
 def local(self,stock='ti'):return estoque.locations(self.store,self.admin,stock)[0]['id']
 def body(self,**kw):return {'nome':'Material de teste','categoria':'Equipamentos','unidade':'un.','codigo':'','local_id':self.local(),'quantidade':'10','minimo':'1','observacoes':'',**kw}
 def test_seed_locations_once_and_regular_users_start_without_access(self):
  self.assertEqual(estoque.access(self.store,self.user)['estoques'],[])
  for stock in estoque.STOCKS:
   self.assertEqual(set(l['nome'] for l in estoque.locations(self.store,self.admin,stock)),set(estoque.LOCATIONS))
  locs=estoque.locations(self.store,self.admin,'ti');loc=locs[0]
  estoque.locations(self.store,self.admin,'ti',{'versao':loc['versao'],'excluir':True},loc['id'])
  self.assertEqual(len(estoque.locations(self.store,self.admin,'ti')),5)
 def test_permissions_are_independent_and_cannot_be_self_granted(self):
  self.grant('crud','ver');a=estoque.access(self.store,self.user)
  self.assertEqual({s['codigo']:s['permissao'] for s in a['estoques']},{'ti':'crud','escritorio_limpeza':'ver'})
  with self.assertRaises(legal.AppError):estoque.permissions(self.store,self.user)
  with self.assertRaises(legal.AppError):estoque.permissions(self.store,self.user,{'user_id':self.user['id'],'permissoes':{'ti':'crud','escritorio_limpeza':'crud'}})
  with self.assertRaises(legal.AppError):estoque.save(self.store,self.user,'escritorio_limpeza',self.body(local_id=self.local('escritorio_limpeza')))
 def test_viewer_reads_but_all_mutations_and_foreign_stock_are_denied(self):
  item=estoque.save(self.store,self.admin,'ti',self.body());self.grant('ver')
  self.assertEqual(estoque.items(self.store,self.user,'ti')['total'],1)
  self.assertEqual(estoque.history(self.store,self.user,item['id'])['total'],1)
  operations=[lambda:estoque.save(self.store,self.user,'ti',self.body()),lambda:estoque.movement(self.store,self.user,item['id'],{'tipo':'entrada','quantidade':'1','motivo':'Teste','versao':item['versao']}),lambda:estoque.delete(self.store,self.user,item['id'],{'motivo':'Teste','versao':item['versao']}),lambda:estoque.locations(self.store,self.user,'ti',{'nome':'Novo'}),lambda:estoque.items(self.store,self.user,'escritorio_limpeza')]
  for operation in operations:
   with self.assertRaises(legal.AppError) as error:operation()
   self.assertEqual(error.exception.code,403)
 def test_reader_role_cannot_receive_crud_and_revocation_applies_immediately(self):
  reader=self.store.create_user({'nome':'Leitor','login':'leitor','senha':'senha-forte-teste','role':'leitor'},self.admin)
  with self.assertRaises(legal.AppError):self.grant('crud',user=reader)
  self.grant('ver',user=reader);self.assertEqual(estoque.access(self.store,reader)['estoques'][0]['permissao'],'ver')
  self.grant('crud');item=estoque.save(self.store,self.user,'ti',self.body());self.grant()
  with self.assertRaises(legal.AppError):estoque.history(self.store,self.user,item['id'])
 def test_exact_decimal_quantities_and_input_validation(self):
  self.grant('crud');item=estoque.save(self.store,self.user,'ti',self.body(quantidade='10,100'))
  self.assertEqual(item['quantidade'],'10.1')
  item=estoque.movement(self.store,self.user,item['id'],{'tipo':'entrada','quantidade':'0.2','motivo':'Recebimento','versao':item['versao']})
  self.assertEqual(item['quantidade'],'10.3');self.assertEqual(estoque.decimal(100000),'100')
  for value in ('-1','NaN','inf','0.0001','1000000001',True,None):
   with self.assertRaises(legal.AppError):estoque.quantity(value)
 def test_overdraw_and_stale_update_roll_back_without_losing_stock(self):
  self.grant('crud');item=estoque.save(self.store,self.user,'ti',self.body(quantidade='1'))
  body={'tipo':'saida','quantidade':'2','motivo':'Saída','versao':item['versao']}
  with self.assertRaises(legal.AppError):estoque.movement(self.store,self.user,item['id'],body)
  self.assertEqual(estoque.history(self.store,self.user,item['id'])['total'],1)
  changed=estoque.movement(self.store,self.user,item['id'],{**body,'tipo':'entrada','quantidade':'1'})
  with self.assertRaises(legal.AppError) as error:estoque.save(self.store,self.user,'ti',self.body(nome='Desatualizado',versao=item['versao']),item['id'])
  self.assertEqual(error.exception.code,409)
  self.assertEqual(estoque.history(self.store,self.user,item['id'])['item']['quantidade'],'2')
  self.assertEqual(changed['versao'],2)
 def test_stock_and_location_cannot_be_crossed(self):
  self.grant('crud','crud')
  with self.assertRaises(legal.AppError):estoque.save(self.store,self.user,'ti',self.body(local_id=self.local('escritorio_limpeza')))
  self.assertEqual(estoque.items(self.store,self.user,'ti')['total'],0)
 def test_delete_keeps_audit_and_requires_zero_balance(self):
  self.grant('crud');item=estoque.save(self.store,self.user,'ti',self.body())
  with self.assertRaises(legal.AppError):estoque.delete(self.store,self.user,item['id'],{'versao':item['versao'],'motivo':'Baixa'})
  item=estoque.movement(self.store,self.user,item['id'],{'versao':item['versao'],'tipo':'saida','quantidade':'10','motivo':'Consumo'})
  estoque.delete(self.store,self.user,item['id'],{'versao':item['versao'],'motivo':'Cadastro encerrado'})
  self.assertEqual(estoque.items(self.store,self.user,'ti')['total'],0)
  with self.store.connect() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM inventory_moves WHERE item_id=?',(item['id'],)).fetchone()[0],3)
   self.assertEqual(db.execute("SELECT COUNT(*) FROM audit WHERE acao='excluir_material'").fetchone()[0],1)
 def test_location_rename_preserves_historical_name_and_in_use_cannot_be_deleted(self):
  self.grant('crud');item=estoque.save(self.store,self.user,'ti',self.body());loc=next(l for l in estoque.locations(self.store,self.user,'ti') if l['id']==item['local_id'])
  with self.assertRaises(legal.AppError):estoque.locations(self.store,self.user,'ti',{'excluir':True,'versao':loc['versao']},loc['id'])
  estoque.locations(self.store,self.user,'ti',{'nome':'Local renomeado','versao':loc['versao']},loc['id'])
  data=estoque.history(self.store,self.user,item['id'])
  self.assertEqual(data['item']['local'],'Local renomeado');self.assertEqual(data['itens'][0]['local_depois_nome'],loc['nome'])
 def test_search_minimum_and_stock_counts_do_not_mix_units_or_stocks(self):
  self.grant('crud','crud');estoque.save(self.store,self.user,'ti',self.body(nome='Cabo HDMI',quantidade='2',minimo='2'))
  estoque.save(self.store,self.user,'escritorio_limpeza',self.body(nome='Detergente',local_id=self.local('escritorio_limpeza'),unidade='litro',quantidade='50'))
  self.assertEqual(estoque.items(self.store,self.user,'ti',query='HDMI',low=True)['total'],1)
  self.assertEqual(estoque.items(self.store,self.user,'ti')['resumo']['materiais'],1)
  with self.assertRaises(legal.AppError):estoque.items(self.store,self.user,'ti',lid=self.local('escritorio_limpeza'))
