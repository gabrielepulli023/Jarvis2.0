import json,tempfile,unittest
from pathlib import Path
from jarvis_memory import MemoryStore
from jarvis_missions import MissionStore,Task,TaskGraph
from jarvis_search import UniversalSearch

class UniversalSearchTests(unittest.TestCase):
    def test_searches_memory_missions_skills_logs_and_code(self):
        root=Path(tempfile.mkdtemp(prefix="jarvis_search_"));data=root/"data";data.mkdir();(data/"logs").mkdir()
        memory=MemoryStore(data/"memory.db");memory.remember("wake word configuration")
        missions=MissionStore(data/"missions.db");missions.create("fix wake word",TaskGraph([Task("a","inspect")]))
        (data/"jarvis_skills.json").write_text(json.dumps({"wake":{"name":"Wake helper","commands":["wake word"]}}),encoding="utf-8")
        (data/"logs"/"jarvis.jsonl").write_text('{"event":"wake word detected"}\n',encoding="utf-8")
        (root/"voice.py").write_text("WAKE_WORD = 'jarvis'\n",encoding="utf-8")
        results=UniversalSearch(root,memory,missions,data).search("wake word",limit=20);sources={x["source"] for x in results}
        self.assertTrue({"memory","mission","skill","log","file"}.issubset(sources))
    def test_empty_query_does_not_scan(self):
        root=Path(tempfile.mkdtemp(prefix="jarvis_search_empty_"));data=root/"data";data.mkdir()
        service=UniversalSearch(root,MemoryStore(data/"memory.db"),MissionStore(data/"missions.db"),data)
        self.assertEqual(service.search(""),[])

if __name__=="__main__":unittest.main()
