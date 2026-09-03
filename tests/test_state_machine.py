import unittest

from jarvis_core.events import EventBus
from jarvis_core.state_machine import JarvisState, JarvisStateMachine, StateTransitionError


class StateMachineTests(unittest.TestCase):
    def test_critical_path_transitions_are_explicit(self):
        machine = JarvisStateMachine(EventBus())
        for state in (JarvisState.IDLE, JarvisState.LISTENING, JarvisState.TRANSCRIBING,
                      JarvisState.UNDERSTANDING, JarvisState.PLANNING, JarvisState.EXECUTING,
                      JarvisState.VERIFYING, JarvisState.SPEAKING, JarvisState.IDLE):
            machine.transition(state)
        self.assertEqual(machine.state, JarvisState.IDLE)

    def test_invalid_transition_is_rejected(self):
        with self.assertRaises(StateTransitionError): JarvisStateMachine(EventBus()).transition(JarvisState.EXECUTING)

    def test_emergency_forces_idle_with_priority(self):
        events = []; bus = EventBus(); bus.subscribe("assistant.state_changed", events.append)
        machine = JarvisStateMachine(bus); machine.transition(JarvisState.IDLE); machine.transition(JarvisState.SPEAKING)
        machine.emergency_idle(); self.assertEqual(machine.state, JarvisState.IDLE); self.assertEqual(events[-1].priority, 1000)
    def test_external_state_sync_uses_legal_shortest_path(self):
        machine=JarvisStateMachine(EventBus());machine.advance(JarvisState.SPEAKING)
        self.assertEqual(machine.state,JarvisState.SPEAKING)


if __name__ == "__main__": unittest.main()
