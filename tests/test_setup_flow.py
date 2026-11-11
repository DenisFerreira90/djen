import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.cli import validate_acervo_route,start_after_access,parser
from conectacoletor.storage import AgentDB,Vault
from conectacoletor.multi import batch_command


class SetupFlowTests(unittest.TestCase):
    def test_manual_login_dispatches_automatic_full_acervo(self):
        runtime=MagicMock()
        with patch('conectacoletor.cli.collect_pje',return_value='parcial_acervo') as worker:
            self.assertEqual(start_after_access(runtime,'PJE_PE_1G'),'parcial_acervo')
        args=worker.call_args.args
        self.assertTrue(args[2]['todas_comarcas']);self.assertEqual(args[2]['dias'],20)
        self.assertFalse(args[3])

    def test_eproc_dispatch_keeps_existing_engine(self):
        runtime=MagicMock()
        with patch('conectacoletor.cli.collect',return_value='parcial') as worker:
            start_after_access(runtime,'TJSC')
        self.assertFalse(worker.call_args.args[2]['todas_comarcas'])

    def test_issues_survive_restart_and_only_verified_entries_are_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db';db=AgentDB(path)
            db.issue('PJE_PE_1G','login_pendente','Abra o acesso')
            db.acervo_issues('PJE_PE_1G',{'nos':{'Caruaru':{'estado':'contagem_divergente'}},'encerramento':'nos_renderizados_percorridos','navegacao_total_confirmada':False})
            other=AgentDB(path);self.assertEqual(len(other.issues()),3)
            other.resolve_issue('PJE_PE_1G','login_pendente')
            other.acervo_issues('PJE_PE_1G',{'nos':{'Caruaru':{'estado':'lista_conferida'}},'encerramento':'nos_renderizados_percorridos','navegacao_total_confirmada':True})
            self.assertEqual(other.issues(),[])

    def test_route_is_same_portal_stable_and_persisted_protected(self):
        url='https://pje.cloud.tjpe.jus.br/1g/Painel/painel_usuario/advogado.seam'
        self.assertEqual(validate_acervo_route(url,'PJE_PE_1G'),url)
        for bad in (url+'?cid=123',url+'?state=private',url+'#token','javascript:alert(1)',url.replace('/1g/','/2g/'),url.replace('pje.cloud.tjpe.jus.br','example.com')):
            with self.subTest(url=bad):
                with self.assertRaises(ValueError):validate_acervo_route(bad,'PJE_PE_1G')
        with tempfile.TemporaryDirectory() as tmp:
            vault=Vault(tmp,lambda raw,decrypt=False:raw)
            vault.write('rota_PJE_PE_1G',{'acervo':url})
            self.assertEqual(vault.read('rota_PJE_PE_1G')['acervo'],url)

    def test_pure_login_option_and_family_specific_batch_arguments(self):
        self.assertTrue(parser().parse_args(['acessar','PJE_PE_1G','--somente-login']).somente_login)
        self.assertIn('--todas-comarcas',batch_command(Path('/test'),'PJE_PE_1G',20,all_districts=True))
        self.assertNotIn('--todas-comarcas',batch_command(Path('/test'),'TJSC',20,all_districts=True))
