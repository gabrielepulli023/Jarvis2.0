import threading
import time
import unittest

from jarvis_memory import WorkingMemory


class AdvancedWorkingMemoryTests(unittest.TestCase):
    def test_legacy_api_and_defensive_copy_remain_unchanged(self):
        memory = WorkingMemory(max_entries=16)
        source = {"items": []}
        memory.set("one", source)
        source["items"].append(1)
        self.assertEqual(memory.get("one"), {"items": []})
        self.assertEqual(memory.snapshot()["one"], {"items": []})

    def test_delete_prefix_contains_and_inspect(self):
        memory = WorkingMemory(max_entries=16)
        memory.set("world.a", 1, source="test", confidence=.8)
        memory.set("world.b", 2)
        self.assertTrue(memory.contains("world.a"))
        self.assertEqual(memory.inspect("world.a")["source"], "test")
        self.assertEqual(memory.clear_prefix("world."), 2)
        self.assertFalse(memory.contains("world.a"))

    def test_expired_entries_are_purged_before_oldest_eviction(self):
        memory = WorkingMemory(max_entries=2)
        memory.set("expired", 1, ttl=.01)
        time.sleep(.03)
        memory.set("new", 2)
        memory.set("newer", 3)
        self.assertNotIn("expired", memory.snapshot())
        self.assertEqual(memory.stats()["entries"], 2)

    def test_eviction_is_bounded_and_thread_safe(self):
        memory = WorkingMemory(max_entries=16)
        threads = [threading.Thread(target=lambda offset=i: [memory.set(f"k{offset}-{n}", n) for n in range(20)]) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertLessEqual(memory.stats()["entries"], 16)

    def test_new_instance_is_volatile(self):
        self.assertEqual(WorkingMemory().snapshot(), {})


if __name__ == "__main__":
    unittest.main()
