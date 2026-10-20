import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import Mock, patch

with patch.dict(os.environ, {
    "YEELIGHT_IP": "192.0.2.1",
    "YEELIGHT_TOKEN": "0" * 32,
    "LATITUDE": "48.8566",
    "LONGITUDE": "2.3522",
    "TIMEZONE": "Europe/Paris",
}), patch("dotenv.load_dotenv"):
    import dimmer


class CircadianProfileTests(unittest.TestCase):
    def setUp(self):
        self.tz = ZoneInfo("Europe/Paris")
        self.profile = dimmer.CircadianProfile(48.8566, 2.3522, "Europe/Paris")

    def test_evening_start_follows_sunset_within_limits(self):
        for sunset_hour, sunset_minute, start_hour, start_minute in ((16, 0, 18, 30), (20, 30, 19, 30), (22, 0, 20, 30)):
            with self.subTest(sunset=(sunset_hour, sunset_minute)):
                start = datetime(2026, 10, 20, start_hour, start_minute, tzinfo=self.tz)
                with patch.object(dimmer, "sun", return_value={
                    "sunrise": start.replace(hour=8, minute=0),
                    "sunset": start.replace(hour=sunset_hour, minute=sunset_minute),
                }):
                    self.assertEqual(self.profile.calculate(start - timedelta(minutes=1)), (100, 5000, "day"))
                    self.assertEqual(self.profile.calculate(start), (100, 5000, "evening"))
                    midpoint = start + (start.replace(hour=23, minute=0) - start) / 2
                    self.assertEqual(self.profile.calculate(midpoint), (56, 3350, "evening"))

    def test_seasons_keep_light_until_bedtime(self):
        for month, day in ((1, 15), (6, 21), (10, 20), (10, 25)):
            with self.subTest(date=(month, day)):
                now = datetime(2026, month, day, 20, 0, tzinfo=self.tz)
                brightness, temperature, _ = self.profile.calculate(now)
                self.assertGreater(brightness, 12)
                self.assertGreater(temperature, 1700)
                before_bedtime = now.replace(hour=22, minute=30)
                self.assertGreater(self.profile.calculate(before_bedtime)[0], 12)
                self.assertEqual(self.profile.calculate(now.replace(hour=23, minute=0)), (12, 1700, "night"))
                self.assertEqual(self.profile.calculate((now + timedelta(days=1)).replace(hour=0)), (12, 1700, "night"))

    def test_morning_still_follows_sunrise(self):
        now = datetime(2026, 10, 20, tzinfo=self.tz)
        sunrise = dimmer.sun(self.profile.location.observer, date=now.date(), tzinfo=self.tz)["sunrise"]
        self.assertEqual(self.profile.calculate(sunrise - timedelta(minutes=1)), (12, 1700, "night"))
        self.assertEqual(self.profile.calculate(sunrise + timedelta(hours=1)), (56, 3350, "morning"))
        self.assertEqual(self.profile.calculate(sunrise + timedelta(hours=2)), (100, 5000, "day"))


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
