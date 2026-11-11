import sys,tempfile,unittest,types
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import eproc
class BlockedWindow(unittest.TestCase):
 def test_full_run_keeps_window_for_inspection_then_closes_without_retry(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=eproc.Collector(tmp)
   with patch.object(eproc.threading,'Thread'):c.start(options={'tribunal':'TJRS'})
   context=MagicMock();page=MagicMock();page.is_closed.return_value=False;context.pages=[page]
   pw=MagicMock();pw.chromium.launch_persistent_context.return_value=context
   sync=MagicMock();sync.return_value.__enter__.return_value=pw
   module=types.ModuleType('playwright.sync_api');module.sync_playwright=sync
   def denied(*args,**kwargs):c.block_status=403
   page.goto.side_effect=denied
   def inspect_pause(timeout):
    self.assertFalse(context.close.called)
    self.assertEqual(c.current['estado'],'aguardando')
    self.assertEqual(c.current['bloqueio_http'],403)
    c.check() # Still blocked, even during the inspection pause.
   def release(timeout):
    try:inspect_pause(timeout)
    except RuntimeError as error:self.assertEqual(str(error),'HTTP_403')
    return True
   with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':module}),patch.object(c.resume,'wait',side_effect=release),patch.object(c,'await_listing') as listing:
    c.run()
   self.assertEqual(c.current['estado'],'bloqueado_http');page.goto.assert_called_once();listing.assert_not_called();context.close.assert_called_once()
 def test_hidden_mode_never_waits_for_inspection(self):
  c=eproc.Collector();c.options={'invisivel':True};c.block_status=403
  with patch.object(c.resume,'wait') as wait:c.inspect_blocked(MagicMock())
  wait.assert_not_called()
 def test_cancel_exits_visible_inspection(self):
  c=eproc.Collector();c.options={};c.block_status=403;c.log=MagicMock();c.update=MagicMock();c.cancelled.set()
  with patch.object(c.resume,'wait',return_value=False):c.inspect_blocked(MagicMock())
  self.assertEqual(c.block_status,403)
if __name__=='__main__':unittest.main()
