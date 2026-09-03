import os
import unittest
from unittest.mock import patch

import provider_router
import json
from io import BytesIO


class ProviderRouterTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "ai_provider": "auto", "ai_model": "gpt-5.6-luna",
            "claude_model": "claude-haiku-4-5-20251001", "kimi_model": "kimi-k3",
        }

    def test_auto_routing_assigns_specialized_work(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "c", "MOONSHOT_API_KEY": "k"}, clear=True), patch.object(provider_router, "get_setting", side_effect=lambda key, default=None: self.settings.get(key, default)):
            self.assertEqual(provider_router.decide_route("Correggi il bug nel codice Python").provider, "claude")
            self.assertEqual(provider_router.decide_route("Analizza e riassumi questo documento lungo").provider, "kimi")
            self.assertEqual(provider_router.decide_route("Quali sono le ultime notizie oggi?").provider, "openai")

    def test_unconfigured_provider_is_never_selected(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "o"}, clear=True), patch.object(provider_router, "get_setting", side_effect=lambda key, default=None: self.settings.get(key, default)):
            decision = provider_router.decide_route("Scrivi codice Rust")
        self.assertEqual(decision.provider, "openai")

    def test_user_choice_precedes_automatic_assignment(self):
        self.settings["ai_provider"] = "kimi"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "o", "MOONSHOT_API_KEY": "k"}, clear=True), patch.object(provider_router, "get_setting", side_effect=lambda key, default=None: self.settings.get(key, default)):
            self.assertEqual(provider_router.decide_route("Quali sono le ultime notizie?").provider, "kimi")

    def test_operational_tasks_stay_on_openai(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "c", "MOONSHOT_API_KEY": "k"}, clear=True), patch.object(provider_router, "get_setting", side_effect=lambda key, default=None: self.settings.get(key, default)):
            self.assertEqual(provider_router.decide_route("Apri Chrome", requires_tools=True).provider, "openai")

    def test_capability_matrix_routes_vision_planning_and_summaries(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "c", "MOONSHOT_API_KEY": "k"}, clear=True), patch.object(provider_router, "get_setting", side_effect=lambda key, default=None: self.settings.get(key, default)):
            self.assertEqual(provider_router.decide_route("Guarda questo screenshot").provider, "openai")
            self.assertEqual(provider_router.decide_route("Pianifica un workflow multi-step").provider, "claude")
            self.assertEqual(provider_router.decide_route("Riassumi questo documento lungo").provider, "kimi")

    def test_work_items_are_distributed_independently(self):
        items = [{"description": "debug codice Python"}, {"description": "riassumi molti file"}, {"description": "apri Chrome", "requires_tools": True}]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "c", "MOONSHOT_API_KEY": "k"}, clear=True), patch.object(provider_router, "get_setting", side_effect=lambda key, default=None: self.settings.get(key, default)):
            routed = provider_router.route_work_items(items)
        self.assertEqual([decision.provider for _, decision in routed], ["claude", "kimi", "openai"])
    def test_claude_sse_is_streamed_as_deltas(self):
        decision=provider_router.RouteDecision("claude","model","coding","test")
        lines=[b'data: {"type":"content_block_delta","delta":{"text":"Ciao "}}\n',b'data: {"type":"content_block_delta","delta":{"text":"mondo"}}\n',b'data: [DONE]\n']
        response=type("Response",(),{"__enter__":lambda self:self,"__exit__":lambda *args:None,"__iter__":lambda self:iter(lines)})()
        with patch.dict(os.environ,{"ANTHROPIC_API_KEY":"c"},clear=True),patch.object(provider_router,"urlopen",return_value=response):
            self.assertEqual(list(provider_router.stream_non_openai(decision,"system",[])),["Ciao ","mondo"])

    def test_anthropic_model_override_is_configurable_without_exposing_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_MODEL": "claude-haiku-4-5-20251001", "ANTHROPIC_API_KEY": "c"}, clear=True):
            self.assertEqual(provider_router._models()["claude"], "claude-haiku-4-5-20251001")
