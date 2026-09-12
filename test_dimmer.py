import os
import unittest
from unittest.mock import Mock, patch

with patch.dict(os.environ, {
    "YEELIGHT_IP": "192.0.2.1",
    "YEELIGHT_TOKEN": "0" * 32,
    "LATITUDE": "48.8566",
    "LONGITUDE": "2.3522",
    "TIMEZONE": "Europe/Paris",
}), patch("dotenv.load_dotenv"):
    import dimmer


class ToggleCommandTests(unittest.TestCase):
    def setUp(self):
        with patch.object(dimmer, "Yeelight"):
            self.controller = dimmer.LightController("192.0.2.1", "0" * 32)
        self.log_patch = patch.object(dimmer, "write_log")
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def test_read_errors_return_unknown(self):
        for error in (dimmer.DeviceException("offline"), ValueError("invalid"), RuntimeError("unexpected")):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.controller, "_read_state", side_effect=error):
                    self.assertIsNone(self.controller.detect_toggle_command())

    def test_valid_states_detect_command(self):
        for state, expected in ((('on', 100, 6500), True), (('on', 50, 4000), False), (('off', 100, 6500), False)):
            with self.subTest(state=state):
                with patch.object(self.controller, "_read_state", return_value=state):
                    self.assertIs(self.controller.detect_toggle_command(), expected)

    def run_states(self, states):
        profile = Mock()
        profile.calculate.return_value = (50, 4000, "evening")
        with patch.object(dimmer, "CircadianProfile", return_value=profile), \
                patch.object(dimmer, "LightController", return_value=self.controller), \
                patch.object(self.controller, "_read_state", side_effect=states), \
                patch.object(self.controller, "apply") as apply, \
                patch.object(dimmer.time, "sleep", side_effect=[None] * (len(states) - 1) + [KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                dimmer.run_service()
            return apply.call_args_list

    def test_network_failure_does_not_reenable_automation(self):
        calls = self.run_states([
            ('on', 100, 6500),
            dimmer.DeviceException("offline"),
            ('on', 100, 6500),
        ])
        self.assertEqual(calls, [])

    def test_leaving_command_then_returning_reenables_automation(self):
        calls = self.run_states([
            ('on', 100, 6500),
            ('on', 50, 4000),
            ('on', 100, 6500),
        ])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, (50, 4000))


if __name__ == "__main__":
    unittest.main()
