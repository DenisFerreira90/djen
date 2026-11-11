"""Integração opcional contra o servidor real do ConectaAdv v59."""
import os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.sync import Client,SyncError
from conectacoletor.runtime import juridico
SOURCE=os.environ.get('CONECTAADV_SOURCE')

@unittest.skipUnless(SOURCE,'Defina CONECTAADV_SOURCE para testar o servidor ConectaAdv real.')
class RealConectaIntegration(unittest.TestCase):
 def test_import_repeated_payload_and_owner_permission(self):
  sys.path.append(SOURCE)
  import servidor
  with tempfile.TemporaryDirectory() as tmp:
   store=juridico.Store(Path(tmp)/'remote.sqlite3');owner=store.create_user({'nome':'Owner','login':'owner','senha':'senha-teste-forte-123'},setup=True)
   store.create_user({'nome':'Admin','login':'admin','senha':'senha-teste-forte-123','role':'administrador'},owner)
   with patch.object(juridico,'store',store):
    server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    url='http://127.0.0.1:'+str(server.server_port)
    try:
     client=Client({'url':url,'usuario':'owner','senha':'senha-teste-forte-123'})
     number='5001234-12.2026.8.24.0001'
     payload={'execucao':{'id':'cc-integration-1','tribunal':'TJSC'},'processos':[{'processo':number,'detalhes':None}],'paginas_da_lista':[]}
     first=client.send(payload);second=client.send(payload)
     with store.connect() as db:
      self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE kind='processos'").fetchone()[0],1)
      self.assertEqual(db.execute('SELECT COUNT(*) FROM imports WHERE id LIKE ?',('cc-integration-1:%',)).fetchone()[0],1)
     self.assertEqual(first['criados'],1);self.assertTrue(second['repetido'])
     denied=Client({'url':url,'usuario':'admin','senha':'senha-teste-forte-123'})
     with self.assertRaises(SyncError):denied.send(payload)
    finally:server.shutdown();server.server_close();worker.join()
if __name__=='__main__':unittest.main()
