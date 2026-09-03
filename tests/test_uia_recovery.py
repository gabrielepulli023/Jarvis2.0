import time,unittest
from unittest.mock import patch
from jarvis_windows import WindowsUIAgent

class UIARecoveryTests(unittest.TestCase):
    def test_failed_action_retries_are_bounded(self):
        calls=[]
        with patch("jarvis_windows.uia.ui_invoke",side_effect=lambda target:(calls.append(target) or {"success":len(calls)>=2})):
            agent=WindowsUIAgent(lambda:{"success":True,"data":{}});result=agent.invoke("Save",retries=2);agent.close()
        self.assertTrue(result["success"]);self.assertEqual(len(calls),2)
    def test_action_timeout_returns_structured_failure(self):
        with patch("jarvis_windows.uia.ui_focus",side_effect=lambda target:time.sleep(.2)):
            agent=WindowsUIAgent(lambda:{"success":True,"data":{}});started=time.monotonic();result=agent.focus("x",timeout=.02,retries=0);agent.close()
        self.assertFalse(result["success"]);self.assertEqual(result["error"],"timeout");self.assertLess(time.monotonic()-started,.15)

if __name__=="__main__":unittest.main()
