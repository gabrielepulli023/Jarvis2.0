import threading,time,unittest
from jarvis_voice import SpeechPriority,VoiceSessionEngine,VoiceState

class VoiceSessionTests(unittest.TestCase):
    def test_priority_queue_and_fifo_within_priority(self):
        spoken=[];engine=VoiceSessionEngine(lambda text,interruptible:spoken.append(text),lambda text:None,auto_start=False)
        engine.submit("low",SpeechPriority.LOW);engine.submit("normal one");engine.submit("critical",SpeechPriority.CRITICAL);engine.submit("normal two")
        engine.start();deadline=time.monotonic()+1
        while len(spoken)<4 and time.monotonic()<deadline:time.sleep(.01)
        engine.shutdown();self.assertEqual(spoken,["critical","normal one","normal two","low"])
    def test_barge_in_interrupts_current_speech_and_records_text(self):
        release=threading.Event();started=threading.Event();stopped=[]
        def speaker(text,interruptible):started.set();release.wait(1)
        def stop(text):stopped.append(text);release.set()
        engine=VoiceSessionEngine(speaker,stop);engine.submit("long response");self.assertTrue(started.wait(.5));self.assertTrue(engine.interrupt("nuovo comando"))
        deadline=time.monotonic()+1
        while not engine.snapshot()["history"] and time.monotonic()<deadline:time.sleep(.01)
        snapshot=engine.snapshot();engine.shutdown();self.assertEqual(stopped[0],"nuovo comando");self.assertTrue(snapshot["history"][0]["interrupted"]);self.assertEqual(snapshot["history"][0]["barge_text"],"nuovo comando")
    def test_non_interruptible_message_rejects_barge_in(self):
        release=threading.Event();started=threading.Event();engine=VoiceSessionEngine(lambda text,interruptible:(started.set(),release.wait(.3)),lambda text:release.set())
        engine.submit("critical",interruptible=False);self.assertTrue(started.wait(.5));self.assertFalse(engine.interrupt("stop"));release.set();engine.shutdown()
    def test_shutdown_cancels_pending_and_stops_worker(self):
        engine=VoiceSessionEngine(lambda text,interruptible:None,lambda text:None,auto_start=False);engine.submit("one");engine.submit("two");self.assertEqual(engine.cancel_pending(),2);engine.start();engine.shutdown();self.assertEqual(engine.state,VoiceState.STOPPED)
    def test_synchronous_wait_returns_speaker_result(self):
        engine=VoiceSessionEngine(lambda text,interruptible:"heard:"+text,lambda text:None)
        self.assertEqual(engine.speak_wait("hello",timeout=1),"heard:hello");engine.shutdown()

    def test_italian_interruptible_alias_remains_compatible(self):
        flags=[]
        engine=VoiceSessionEngine(lambda text,interruptible:flags.append(interruptible) or text,lambda text:None)
        self.assertEqual(engine.speak_wait("ciao",interrompibile=False,timeout=1),"ciao")
        engine.shutdown();self.assertEqual(flags,[False])
    def test_records_tts_latency_metric(self):
        metrics=[];engine=VoiceSessionEngine(lambda text,interruptible:None,lambda text:None,record_metric=lambda *row:metrics.append(row))
        engine.speak_wait("metric",timeout=1);engine.shutdown();self.assertEqual(metrics[0][0],"tts");self.assertTrue(metrics[0][1]);self.assertGreaterEqual(metrics[0][2],0)

if __name__=="__main__":unittest.main()
