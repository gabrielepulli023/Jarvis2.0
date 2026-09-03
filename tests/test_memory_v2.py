import sqlite3,tempfile,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from jarvis_memory import ContextBuilder,MemoryKind,MemoryStore,WorkingMemory

class WorkingMemoryTests(unittest.TestCase):
    def test_snapshot_keeps_explicit_none_values(self):
        memory=WorkingMemory();memory.set("empty",None)
        self.assertIn("empty",memory.snapshot());self.assertIsNone(memory.snapshot()["empty"])

    def test_snapshot_drops_expired_values(self):
        memory=WorkingMemory();memory.set("temporary", "value", ttl=.01);time.sleep(.06)
        self.assertNotIn("temporary", memory.snapshot())

    def test_ttl_and_defensive_copy(self):
        memory=WorkingMemory();source={"x":[]};memory.set("context",source,ttl=.02);source["x"].append(1)
        self.assertEqual(memory.get("context"),{"x":[]});time.sleep(.06);self.assertIsNone(memory.get("context"))

class DurableMemoryTests(unittest.TestCase):
    def setUp(self):
        path=Path(tempfile.gettempdir())/"jarvis_memory_v2_test.db";path.unlink(missing_ok=True);self.store=MemoryStore(path)
    def test_deduplicates_and_ranks_relevant_memory(self):
        first=self.store.remember("Python 3.12 is the live runtime",importance=.9)
        duplicate=self.store.remember("  python 3.12 IS the live runtime  ",importance=.5)
        self.store.remember("User likes blue",importance=.8)
        self.assertEqual(first["id"],duplicate["id"]);self.assertTrue(duplicate["deduplicated"])
        self.assertIn("Python",self.store.search("python runtime")[0]["content"])
    def test_memory_kinds_and_usage_scoring(self):
        self.store.remember("Fixed bridge reconnect",kind=MemoryKind.EPISODIC,source="mission")
        row=self.store.search("bridge",kind=MemoryKind.EPISODIC)[0]
        self.assertEqual(row["kind"],"episodic");self.assertGreaterEqual(row["score"],0)
    def test_session_preference_and_task_levels_are_distinct(self):
        for kind in (MemoryKind.SESSION,MemoryKind.PREFERENCE,MemoryKind.TASK):self.store.remember(f"item {kind.value}",kind=kind)
        self.assertEqual(self.store.search("preference",kind="preference")[0]["kind"],"preference")
    def test_sensitive_content_is_never_persisted(self):
        with self.assertRaises(ValueError):self.store.remember("api_key=sk-example-secret")
        self.assertFalse(self.store.search("example secret"))
    def test_local_vector_retrieval_handles_minor_typo(self):
        self.store.remember("configurazione del microfono principale",kind="preference")
        rows=self.store.search("configurazone microfono",kind="preference");self.assertTrue(rows);self.assertIn("microfono",rows[0]["content"])
    def test_knowledge_graph_links_memories(self):
        source=self.store.remember("ChromeBridge",kind="semantic")["id"];target=self.store.remember("websocket disconnect",kind="semantic")["id"]
        self.store.connect(source,"can_fail_with",target,.9);neighbors=self.store.neighbors(source)
        self.assertEqual(neighbors[0]["relation"],"can_fail_with");self.assertEqual(neighbors[0]["content"],"websocket disconnect")
    def test_expiration_and_forget(self):
        expired=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();identity=self.store.remember("temporary",expires_at=expired)["id"]
        self.assertFalse(self.store.search("temporary"));self.assertTrue(self.store.forget(identity));self.assertGreaterEqual(self.store.consolidate()["expired"],0)
    def test_legacy_schema_migration_is_idempotent(self):
        path=Path(tempfile.gettempdir())/"jarvis_memory_legacy_test.db";path.unlink(missing_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY,category TEXT,content TEXT,source TEXT,confidence REAL,importance REAL,expires_at TEXT,active INTEGER)")
            db.execute("INSERT INTO memories VALUES(1,'preference','Preferisco il blu','user',1,.9,NULL,1)")
        store=MemoryStore(path);first=store.migrate_legacy();second=store.migrate_legacy()
        self.assertEqual(first["imported"],1);self.assertEqual(second["imported"],0);self.assertEqual(store.search("blu")[0]["metadata"]["legacy_category"],"preference")
    def test_context_builder_prioritizes_and_obeys_budget(self):
        self.store.remember("Chrome bridge websocket reconnect procedure",kind="procedural",importance=1)
        self.store.remember("Unrelated preference",importance=1)
        builder=ContextBuilder(self.store,max_chars=256,max_items=2);items=builder.build("chrome websocket")
        self.assertEqual(items[0].kind,"procedural");self.assertLessEqual(sum(len(x.content) for x in items),256)
        self.assertIn("Chrome bridge",builder.render("chrome websocket"))

if __name__=="__main__":unittest.main()
