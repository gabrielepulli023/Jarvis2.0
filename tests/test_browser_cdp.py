import json,unittest
from unittest.mock import patch
from jarvis_browser import ChromeDevToolsClient

class Response:
    def __init__(self,value):self.value=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.value

class BrowserCDPTests(unittest.TestCase):
    def test_lists_tabs_from_fixed_loopback_endpoint(self):
        with patch("jarvis_browser.cdp.urlopen",return_value=Response([{"id":"a","title":"Page","url":"https://example.com","type":"page"}])) as call:
            result=ChromeDevToolsClient().action("list_tabs");self.assertTrue(result["success"]);self.assertEqual(result["data"]["tabs"][0]["title"],"Page");self.assertTrue(call.call_args.args[0].full_url.startswith("http://127.0.0.1:9222/"))
    def test_rejects_unsafe_url_tab_id_and_arbitrary_dom_action(self):
        client=ChromeDevToolsClient();self.assertFalse(client.action("open_tab",target="file:///secret")["success"]);self.assertFalse(client.action("close_tab",target="a/../b")["success"]);self.assertFalse(client.action("evaluate",value="alert(1)")["success"])

    def test_accepts_empty_success_body_for_tab_lifecycle(self):
        client=ChromeDevToolsClient()
        with patch.object(client,"_request",return_value={}):
            self.assertTrue(client.action("close_tab",target="tab-123")["success"])

if __name__=="__main__":unittest.main()
