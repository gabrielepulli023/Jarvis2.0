import tempfile,time,unittest
from pathlib import Path
from jarvis_voice import TTSCache

class TTSCacheTests(unittest.TestCase):
    def test_store_restore_and_content_verification(self):
        root=Path(tempfile.mkdtemp(prefix="jarvis_tts_"));source=root/"source.mp3";source.write_bytes(b"x"*256);cache=TTSCache(root/"cache",max_entries=3)
        self.assertTrue(cache.store("voice|hello",source));target=root/"target.mp3";self.assertTrue(cache.restore("voice|hello",target));self.assertEqual(target.read_bytes(),source.read_bytes())
    def test_rejects_truncated_audio(self):
        root=Path(tempfile.mkdtemp(prefix="jarvis_tts_small_"));source=root/"small.mp3";source.write_bytes(b"x");cache=TTSCache(root/"cache",min_size=128)
        self.assertFalse(cache.store("small",source));self.assertFalse(cache.restore("small",root/"out.mp3"))
    def test_lru_prunes_old_entries(self):
        root=Path(tempfile.mkdtemp(prefix="jarvis_tts_lru_"));cache=TTSCache(root/"cache",max_entries=2,min_size=1)
        for index in range(3):
            source=root/f"{index}.mp3";source.write_bytes(bytes([index])*10);cache.store(str(index),source);time.sleep(.01)
        self.assertEqual(cache.stats()["entries"],2);self.assertFalse(cache.restore("0",root/"old.mp3"));self.assertTrue(cache.restore("2",root/"new.mp3"))

if __name__=="__main__":unittest.main()
