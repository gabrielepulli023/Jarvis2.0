import unittest
from unittest.mock import patch


class CycleStabilityTests(unittest.TestCase):
    def test_500_conversational_cycles_recover_from_one_processing_error(self):
        import main

        worker = main.JarvisWorker()
        worker.conversazione_vocale_attiva = True
        calls = []
        recoveries = []

        def fake_listen(*args, **kwargs):
            return "come stai"

        def fake_process(text):
            calls.append(text)
            if len(calls) == 3:
                raise RuntimeError("errore simulato nel processing")
            if len(calls) >= 500:
                worker.running = False

        original_recover = worker._recover_cycle_exception
        with patch.object(main, "ascolta", side_effect=fake_listen), patch.object(worker, "processa_domanda", side_effect=fake_process), patch.object(worker, "_recover_cycle_exception", side_effect=lambda exc: (recoveries.append(str(exc)), original_recover(exc))[1]):
            worker.ciclo_conversazione_vocale()

        self.assertEqual(len(calls), 500)
        self.assertFalse(worker.running)
        self.assertIsNone(worker._active_cycle_id)
        self.assertFalse(worker.sta_parlando)
        states = [row["state"] for row in worker._cycle_trace]
        # La traccia è intenzionalmente bounded; il contatore delle chiamate
        # certifica i 500 cicli, mentre l'ultima finestra deve restare coerente.
        self.assertLessEqual(len(states), 300)
        self.assertIn("BACK_TO_STANDBY", states)
        self.assertEqual(len(recoveries), 1)
