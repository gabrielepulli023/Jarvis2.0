import sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_voice.health import probe_audio_input,probe_audio_output,probe_wake_model

class VoiceHealthTests(unittest.TestCase):
    def test_validates_required_wake_model_artifacts(self):
        root=Path(tempfile.mkdtemp());(root/"am").mkdir();(root/"graph").mkdir();(root/"am"/"final.mdl").write_bytes(b"model")
        self.assertTrue(probe_wake_model(root));(root/"am"/"final.mdl").unlink();self.assertFalse(probe_wake_model(root))
    def test_probes_input_and_output_devices(self):
        module=types.ModuleType("sounddevice");module.query_devices=lambda:[{"max_input_channels":1,"max_output_channels":0},{"max_input_channels":0,"max_output_channels":2}]
        with patch.dict(sys.modules,{"sounddevice":module}):self.assertTrue(probe_audio_input());self.assertTrue(probe_audio_output())
    def test_reports_missing_devices(self):
        module=types.ModuleType("sounddevice");module.query_devices=lambda:[]
        with patch.dict(sys.modules,{"sounddevice":module}):self.assertFalse(probe_audio_input());self.assertFalse(probe_audio_output())

if __name__=="__main__":unittest.main()
