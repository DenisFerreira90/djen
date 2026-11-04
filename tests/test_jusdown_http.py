import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import juridico
import servidor
import jusdown

class JusdownHTTP(unittest.TestCase):
    def test_auth_csrf_admin_and_selected_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            monitor=jusdown.Monitor(Path(tmp)/'status.sqlite3')
            store=juridico.Store(Path(tmp)/'legal.sqlite3')
            admin=store.create_user({'nome':'Admin Teste','login':'admin','senha':'senha-forte-teste'},setup=True)
            store.create_user({'nome':'Leitor Teste','login':'leitor','senha':'senha-forte-teste','role':'leitor'},admin)
            with patch.object(juridico,'store',store),patch.object(jusdown,'monitor',monitor):
                server=servidor.ThreadingHTTPServer(('127.0.0.1',0),servidor.Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base='http://127.0.0.1:'+str(server.server_port)
                def req(route,body=None,auth=None):
                    request=Request(base+'/api/juridico/'+route,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(auth or {})})
                    with urlopen(request) as r:return json.load(r),r.headers
                def login(name):
                    payload,headers=req('entrar',{'login':name,'senha':'senha-forte-teste'})
                    return {'Cookie':headers['Set-Cookie'].split(';')[0],'Origin':base,'X-CSRF-Token':payload['csrf']}
                try:
                    with self.assertRaises(HTTPError) as error:req('jusdown')
                    self.assertEqual(error.exception.code,401)
                    reader=login('leitor');admin_auth=login('admin')
                    self.assertEqual(req('jusdown',auth=reader)[0]['resultado']['resumo']['tribunais'],24)
                    for action,body in [('verificar',{'tribunal':'TJRS'}),('configurar',{'ativo':False}),('lembrete',{}),('adicionar-portal',{}),('remover-portal',{}),('tribunal',{'tribunal':'TJRS','ativo':False})]:
                        with self.assertRaises(HTTPError) as error:req('jusdown/'+action,body,reader)
                        self.assertEqual(error.exception.code,403)
                    with self.assertRaises(HTTPError) as error:req('jusdown/configurar',{'ativo':False},{'Cookie':admin_auth['Cookie']})
                    self.assertEqual(error.exception.code,403)
                    with patch.object(monitor,'request',return_value=True) as run:
                        self.assertTrue(req('jusdown/verificar',{'tribunal':'TJRS'},admin_auth)[0]['resultado']['iniciado'])
                        run.assert_called_once_with('TJRS')
                    with self.assertRaises(HTTPError) as denied:req('jusdown/relatorio',auth=reader)
                    self.assertEqual(denied.exception.code,400)
                    with monitor.db() as c:c.execute('INSERT INTO daily_runs VALUES (?,?)',('test-slot',json.dumps({'slot':'test-slot','tribunal':'TJRS','manual':True,'portais':[{'id':monitor.catalog()[0]['id'],'tribunal':'STJ'}]})))
                    self.assertEqual(len(req('jusdown/relatorio?slot=test-slot',auth=admin_auth)[0]['resultado']),1)
                    self.assertFalse(req('jusdown/tribunal',{'tribunal':'TJRS','ativo':False},admin_auth)[0]['resultado']['ativo'])
                    hidden=req('jusdown',auth=reader)[0]['resultado']
                    self.assertFalse(any(t['id']=='TJRS' for t in hidden['tribunais']))
                    self.assertFalse(any(r['tribunal']=='TJRS' for r in hidden['itens']))
                    self.assertEqual(hidden['resumo']['tribunais'],23)
                    self.assertEqual(req('jusdown/relatorio?slot=test-slot',auth=reader)[0]['resultado'],[])
                    self.assertFalse(req('jusdown/configurar',{'ativo':False},admin_auth)[0]['resultado']['ativo'])
                finally:server.shutdown();server.server_close();thread.join()
