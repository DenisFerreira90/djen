import unittest,sys,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mandados,juridico
class MandadosTest(unittest.TestCase):
 def test_classification(self):
  self.assertEqual(mandados.classify('Expedição de mandado de busca e apreensão'),'possivel_expedicao')
  self.assertEqual(mandados.classify('Mandado não cumprido'),'revisar_negativa_ou_alteracao')
  self.assertEqual(mandados.classify('Mandado revogado'),'revisar_negativa_ou_alteracao')
  self.assertIsNone(mandados.classify('Juntada de mandato e procuração'))
  self.assertIsNone(mandados.classify('Intimação eletrônica expedida'))
 def test_persistence_and_dedup(self):
  with tempfile.TemporaryDirectory() as d:
   store=juridico.Store(Path(d)/'test.db')
   actor=store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
   c=store.save('processos',{'dados':{'numero':'5004310-40.2026.8.21.0018','titulo':'Teste'}},actor)
   with store.connect() as db:
    db.execute('CREATE TABLE source_events(id INTEGER PRIMARY KEY,case_id INTEGER,numero TEXT,data TEXT,payload TEXT)')
    db.execute('INSERT INTO source_events VALUES(1,?,?,?,?)',(c['id'],'5','2026-10-27',json.dumps({'descricao':'Mandado expedido'})))
   self.assertEqual(mandados.scan(store)['novos'],1)
   self.assertEqual(mandados.scan(store)['novos'],0)
   self.assertEqual(mandados.status(store)['pendentes'],1)
   with self.assertRaises(juridico.AppError):mandados.review(store,{**actor,'role':'leitor'},1)
   mandados.review(store,actor,1)
   self.assertEqual(mandados.status(store)['pendentes'],0)
 def test_scope_isolated_and_replays_old_events(self):
  with tempfile.TemporaryDirectory() as d:
   store=juridico.Store(Path(d)/'test.db');actor=store.create_user({'nome':'Admin','login':'admin','senha':'senha-forte-123'},setup=True)
   ns=['5004310-40.2026.8.21.0018','5323687-43.2024.8.21.0001']
   cs=[store.save('processos',{'dados':{'numero':n,'titulo':'Teste'}},actor) for n in ns]
   with store.connect() as db:
    db.execute('CREATE TABLE source_events(id INTEGER PRIMARY KEY,case_id INTEGER,numero TEXT,data TEXT,payload TEXT)')
    for i,c in enumerate(cs,1):db.execute('INSERT INTO source_events VALUES(?,?,?,?,?)',(i,c['id'],'1','2026-10-27',json.dumps({'descricao':'Mandado expedido'})))
   mandados.set_scope(store,actor,[ns[0]])
   self.assertEqual([x['numero'] for x in mandados.status(store)['itens']],[ns[0]])
   mandados.set_scope(store,actor,[ns[1]])
   self.assertEqual([x['numero'] for x in mandados.status(store)['itens']],[ns[1]])
   self.assertEqual(mandados.scan(store)['novos'],0)
   mandados.set_scope(store,actor,[],False)
   self.assertEqual(mandados.status(store)['pendentes'],2)
   with self.assertRaises(juridico.AppError):mandados.set_scope(store,actor,[])
 def test_watchlist_rejects_rounded_excel_number(self):
  import csv,io
  data='Processo,Cliente\n5004310-40.2026.8.21.0018,A\n5.004310402026821e+19,B\n5004310-40.2026.8.21.0018,C\n'.encode()
  r=mandados.extract_watchlist(data,'busca.csv')
  self.assertEqual(len(r['numeros']),1)
  self.assertEqual(len(r['invalidos']),1)

 def test_normalizes_only_punctuation_when_check_digits_match(self):
  pairs={'5001982-77.2025.821.0017':'5001982-77.2025.8.21.0017','5002985-67.2025.821.0017':'5002985-67.2025.8.21.0017','5003475-89.2025.821.0017':'5003475-89.2025.8.21.0017','5150236.40.2025.8.21.0001':'5150236-40.2025.8.21.0001'}
  for original,expected in pairs.items():self.assertEqual(mandados.number(original),expected)
  self.assertIsNone(mandados.number('5001982-78.2025.821.0017'))
  self.assertIsNone(mandados.number('5.00252583202082E+19'))
  self.assertIsNone(mandados.number('[número Excel sem precisão] 5.00252583202082E+19'))
 def test_import_preserves_original_and_explains_rejections(self):
  data='Processo\n5001982-77.2025.821.0017\n5150236.40.2025.8.21.0001\n5.00252583202082E+19\n5001982-78.2025.8.21.0017\n'.encode()
  result=mandados.extract_watchlist(data,'lista.csv');self.assertEqual(len(result['numeros']),2);self.assertEqual(len(result['normalizados']),2);self.assertEqual(len(result['invalidos']),2)
  self.assertEqual(result['normalizados'][0]['original'],'5001982-77.2025.821.0017');self.assertIn('não são confiáveis',result['invalidos'][0]['motivo']);self.assertIn('verificador',result['invalidos'][1]['motivo'])

 def test_watchlist_carries_explicit_client_columns_without_using_responsible_as_contact(self):
  csv='Processo,CLIENTE,TELEFONE,RESPONSÁVEL\n5001982-77.2025.821.0017,Cliente fictício,(51) 99999-0000,Supervisor\n'.encode()
  result=mandados.extract_watchlist(csv,'lista.csv');ctx=result['contexto'][0];self.assertEqual(ctx['nome_cliente'],'Cliente fictício');self.assertIn('99999-0000',ctx['contato']);self.assertNotIn('Supervisor',ctx['contato'])
