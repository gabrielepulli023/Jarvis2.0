import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_broker.protocol import BrokerResponse
from jarvis_system import StartupManager
from jarvis_vault import CredentialVault

class VaultTests(unittest.TestCase):
    def test_round_trip_inventory_and_delete_without_value_exposure(self):
        vault=CredentialVault(Path(tempfile.mkdtemp())/"vault.db")
        with patch("jarvis_vault.vault.protect",side_effect=lambda value:b"ENC"+value),patch("jarvis_vault.vault.unprotect",side_effect=lambda value:value[3:]):
            entry=vault.put("service.api","secret");self.assertEqual(entry.name,"service.api");self.assertEqual(vault.get("service.api"),b"secret")
            self.assertFalse(hasattr(vault.list()[0],"value"));self.assertTrue(vault.delete("service.api"));self.assertFalse(vault.list())
    def test_invalid_names_and_missing_values_fail_closed(self):
        vault=CredentialVault(Path(tempfile.mkdtemp())/"vault.db")
        with self.assertRaises(ValueError):vault.put("bad/name","x")
        with self.assertRaises(KeyError):vault.get("missing")

class Client:
    def __init__(self):self.calls=[]
    def execute(self,action,parameters,confirmed=False):self.calls.append((action,parameters,confirmed));return BrokerResponse("id",True,"ok",{})
class Broker:
    def __init__(self,available=True):self.client=Client();self.available=available
    def ensure_available(self):return self.available
class StartupTests(unittest.TestCase):
    def test_enable_uses_fixed_entrypoint_and_confirmed_broker(self):
        broker=Broker();root=Path.cwd();manager=StartupManager(broker,root);self.assertTrue(manager.enable()["success"])
        action,parameters,confirmed=broker.client.calls[0];self.assertEqual(action,"startup.enable");self.assertTrue(confirmed);self.assertEqual(Path(parameters["arguments"][0]).name,"main.py")
    def test_cancelled_elevation_fails_without_request(self):
        broker=Broker(False);self.assertFalse(StartupManager(broker,Path.cwd()).disable()["success"]);self.assertFalse(broker.client.calls)

if __name__=="__main__":unittest.main()
