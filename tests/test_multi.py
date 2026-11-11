import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conectacoletor.storage import AgentDB,Vault
from conectacoletor.runtime import Runtime
from conectacoletor.multi import collect_batch,snapshot_checkpoint,PJE_BATCH
from conectacoletor.cli import parser


class MultiTests(unittest.TestCase):
    def test_vault_keys_cover_each_portal_without_allowing_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault=Vault(tmp,lambda value,decrypt=False:value)
            for portal in PJE_BATCH:
                vault.write('sessao_'+portal,{'state':{'cookies':[]}})
                self.assertTrue(vault.path('sessao_'+portal).exists())
            with self.assertRaises(ValueError):vault.path('sessao_../TJSC')

    def test_recovery_does_not_interrupt_other_active_portal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=AgentDB(Path(tmp)/'db')
            a=db.new_job('TJSC',{});b=db.new_job('PJE_RJ_1G',{})
            db.update(a,'executando','a');db.update(b,'executando','b')
            self.assertEqual(db.recover('TJSC'),[{'run_id':'a','court':'TJSC'}])
            self.assertEqual(db.job(b)['state'],'executando')

    def test_pje_checkpoint_is_durable_and_never_enters_eproc_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp,Vault(Path(tmp)/'vault',lambda value,decrypt=False:value))
            corpus={'execucao':{},'processos':[{'processo':'5000001-00.2026.8.19.0001'}]}
            file=snapshot_checkpoint(runtime,'test-pje','PJE_RJ_1G',corpus)
            self.assertTrue(file.exists());self.assertEqual(runtime.db.pending(),[])
            stored=json.loads(file.read_text())
            self.assertEqual(stored['execucao']['sistema'],'pje')
            self.assertFalse(stored['coleta']['detalhes_completos'])
            self.assertEqual(runtime.db.status()['capturas_pje_locais'][0]['portal'],'PJE_RJ_1G')

    def test_batch_limits_parallelism_and_deduplicates_portals(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp,Vault(Path(tmp)/'vault',lambda value,decrypt=False:value))
            processes=[];active=0;peak=0
            class Process:
                def __init__(self,args,**kwargs):
                    nonlocal active,peak
                    self.args=args;self.polls=0;self.done=False
                    active+=1;peak=max(active,peak);processes.append(self)
                def poll(self):
                    nonlocal active
                    self.polls+=1
                    if self.polls<2:return None
                    if not self.done:active-=1;self.done=True
                    return 0
            with patch('conectacoletor.multi.time.sleep'):
                result=collect_batch(runtime,[*PJE_BATCH,PJE_BATCH[0]],parallel=2,popen=Process)
            self.assertEqual(peak,2);self.assertEqual(len(result),5);self.assertEqual(len(processes),5)
            for proc in processes:self.assertIn('--pasta',proc.args)

    def test_batch_rejects_unknown_portals_and_excess_parallelism(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp,Vault(Path(tmp)/'vault',lambda value,decrypt=False:value))
            with self.assertRaises(ValueError):collect_batch(runtime,['anything'])
            with self.assertRaises(ValueError):collect_batch(runtime,PJE_BATCH,parallel=4)

    def test_default_batches_are_the_five_pje_portals(self):
        for command in ('acessar-lote','coletar-lote'):
            args=parser().parse_args([command])
            self.assertEqual(tuple(args.tribunais),PJE_BATCH)
