import json
import unittest

from transcriber import StreamingTranscriber


class _Recognizer:
    def __init__(self,partials,final=""):self.partials=iter(partials);self.final=final;self.current=""
    def AcceptWaveform(self,audio):self.current=next(self.partials);return False
    def PartialResult(self):return json.dumps({"partial":self.current})
    def Result(self):return json.dumps({"text":self.current})
    def FinalResult(self):return json.dumps({"text":self.final})


class StreamingSTTTests(unittest.TestCase):
    def test_partial_hypotheses_are_incremental_and_finalized(self):
        partials=[];stream=StreamingTranscriber(_Recognizer(["apri","apri chrome"],"apri chrome"),partials.append)
        stream.feed(b"a");stream.feed(b"b")
        self.assertEqual(partials,["apri","apri chrome"]);self.assertEqual(stream.finish(),"apri chrome")

    def test_final_fragments_do_not_split_common_italian_words(self):
        stream = StreamingTranscriber(_Recognizer([], ""))
        stream._final = ["pronunc", "iare adesso", "e poi", "and", "are"]
        self.assertEqual(stream.finish(), "pronunciare adesso e poi andare")

    def test_interrupt_phrase_fires_immediately(self):
        interrupts=[];stream=StreamingTranscriber(_Recognizer(["jarvis fermati"]),on_interrupt=interrupts.append)
        stream.feed(b"a");self.assertTrue(stream.interrupted);self.assertEqual(interrupts,["jarvis fermati"])

    def test_malformed_or_failed_recognizer_degrades_without_crash(self):
        class Broken:
            def AcceptWaveform(self,audio):return False
            def PartialResult(self):return "not-json"
            def FinalResult(self):raise RuntimeError("device gone")
        errors=[];stream=StreamingTranscriber(Broken(),on_error=errors.append)
        self.assertEqual(stream.feed(b"x"),"");self.assertEqual(stream.finish(),"");self.assertEqual(len(errors),2);self.assertLessEqual(len(stream.errors),20)


if __name__ == "__main__": unittest.main()
