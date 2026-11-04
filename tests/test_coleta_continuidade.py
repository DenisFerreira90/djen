import tempfile,threading,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import eproc,eproc_tribunais as courts
class ContinuityTests(unittest.TestCase):
 def test_collector_status_reads_do_not_stop_or_restart_worker(self):
  with tempfile.TemporaryDirectory() as folder:
   done=threading.Event()
   collector=eproc.Collector(folder);collector.run=lambda:done.wait(5)
   try:
    start=collector.start(options={'tribunal':'TJRS'})['atual']['id']
    for _ in range(5):
     self.assertEqual(collector.status()['atual']['id'],start);self.assertTrue(collector.thread.is_alive());self.assertFalse(collector.cancelled.is_set())
    with self.assertRaises(ValueError):collector.start(options={'tribunal':'TJRS'})
   finally:done.set();collector.thread.join(2)
 def test_sc_is_supported_and_separate_from_other_court(self):
  self.assertEqual(courts.from_number('5001234-12.2025.8.24.0001'),'TJSC')
  self.assertEqual(courts.config('TJSC')['host'],'eproc1g.tjsc.jus.br')
  self.assertNotEqual(courts.config('TJRS')['sessao'],courts.config('TJSC')['sessao'])
  self.assertEqual(courts.from_number('5001234-12.2025.8.16.0001'),'')
if __name__=='__main__':unittest.main()
