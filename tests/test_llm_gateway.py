import os
import unittest
from pathlib import Path
from unittest.mock import patch

import llm_gateway


class LLMGatewayCredentialTests(unittest.TestCase):
    def tearDown(self):
        llm_gateway.openai_client.cache_clear()
        llm_gateway.kimi_client.cache_clear()

    def test_missing_openai_key_is_deferred_until_remote_use(self):
        llm_gateway.openai_client.cache_clear()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(llm_gateway, "_load_project_environment"),
        ):
            client = llm_gateway.openai_client(profile="transcription")
            self.assertIsInstance(client, llm_gateway._DeferredOpenAIClient)
            with self.assertRaises(llm_gateway.MissingProviderCredentials):
                _ = client.responses

    def test_missing_kimi_key_is_deferred_until_remote_use(self):
        llm_gateway.kimi_client.cache_clear()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(llm_gateway, "_load_project_environment"),
        ):
            client = llm_gateway.kimi_client()
            self.assertIsInstance(client, llm_gateway._DeferredKimiClient)
            with self.assertRaises(llm_gateway.MissingProviderCredentials):
                _ = client.chat

    def test_frozen_exe_can_find_project_env_next_to_desktop_folder(self):
        with patch.object(llm_gateway.sys, "frozen", True, create=True), patch.object(
            llm_gateway.sys, "executable", r"C:\Users\gabri\Desktop\JARVIS2.0.exe"
        ):
            candidates = llm_gateway._environment_candidates()
            self.assertIn(Path(r"C:\Users\gabri\Desktop\Jarvis2.0\.env"), candidates)


if __name__ == "__main__":
    unittest.main()
