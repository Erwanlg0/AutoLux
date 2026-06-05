import time
import ctypes
import os
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from miio import Yeelight, DeviceException

load_dotenv(Path(__file__).with_name(".env"))

YEELIGHT_IP = os.environ["YEELIGHT_IP"]
YEELIGHT_TOKEN = os.environ["YEELIGHT_TOKEN"]

LOG_FILE = Path(__file__).with_name("dimmer.log")
MUTEX_NAME = "Global\\LumiereDimmerSingleton"
MUTEX_HANDLE = None
CHECK_INTERVAL_SECONDS = 60
RESUME_THRESHOLD_SECONDS = 90
SYNC_BRIGHTNESS_TOLERANCE = 2
SYNC_CT_TOLERANCE = 100
MAX_SYNC_RETRIES = 2
TOGGLE_COMMAND_BRIGHTNESS = 100
TOGGLE_COMMAND_CT = 6500
TOGGLE_BRIGHTNESS_TOLERANCE = 1
TOGGLE_CT_TOLERANCE = 100


def write_log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"[{timestamp}] {message}\n")

def acquire_single_instance_lock():
    global MUTEX_HANDLE

    kernel32 = ctypes.windll.kernel32
    mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)

    if not mutex_handle:
        return False

    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(mutex_handle)
        return False

    MUTEX_HANDLE = mutex_handle
    return True

class CircadianProfile:
    def __init__(self, start_hour, duration_minutes, reset_hour=8):
        self.start_hour = start_hour
        self.duration = duration_minutes
        self.reset_hour = reset_hour

    def calculate(self, current_time):
        start_time = current_time.replace(hour=self.start_hour, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(minutes=self.duration)
        reset_time = current_time.replace(hour=self.reset_hour, minute=0, second=0, microsecond=0)

        in_overnight_low_window = (
            self.start_hour > self.reset_hour
            and current_time < start_time
            and current_time < reset_time
        )

        if in_overnight_low_window:
            progress = 1.0
            phase = "after"
        elif current_time < start_time:
            progress = 0.0
            phase = "before"
        elif current_time >= end_time:
            progress = 1.0
            phase = "after"
        else:
            elapsed = (current_time - start_time).total_seconds() / 60
            progress = min(1.0, max(0.0, elapsed / self.duration))
            phase = "during"

        brightness = int(100 - (progress * (100 - 12)))
        temp = int(5000 - (progress * 3300))

        return max(10, brightness), max(1700, temp), phase

class LightController:
    def __init__(self, ip, token):
        self.bulb = Yeelight(ip, token)

    def _read_state(self):
        props = self.bulb.get_properties(['power', 'bright', 'ct'])

        if isinstance(props, dict):
            power = props.get('power')
            bright_raw = props.get('bright')
            ct_raw = props.get('ct')
        else:
            power = props[0] if len(props) > 0 else None
            bright_raw = props[1] if len(props) > 1 else None
            ct_raw = props[2] if len(props) > 2 else None

        if bright_raw is None or ct_raw is None:
            raise ValueError(f"Invalid bulb state payload: {props}")

        return power, int(bright_raw), int(ct_raw)

    def _is_in_sync(self, current_brightness, current_temperature, target_brightness, target_temperature):
        return (
            abs(current_brightness - target_brightness) < SYNC_BRIGHTNESS_TOLERANCE
            and abs(current_temperature - target_temperature) < SYNC_CT_TOLERANCE
        )

    def _is_toggle_command(self, brightness, temperature):
        return (
            abs(brightness - TOGGLE_COMMAND_BRIGHTNESS) <= TOGGLE_BRIGHTNESS_TOLERANCE
            and abs(temperature - TOGGLE_COMMAND_CT) <= TOGGLE_CT_TOLERANCE
        )

    def detect_toggle_command(self):
        try:
            power, current_bright, current_ct = self._read_state()
            return power == 'on' and self._is_toggle_command(current_bright, current_ct)
        except DeviceException as ex:
            write_log(f"DeviceException in detect_toggle_command: {ex}")
            return False
        except ValueError as ex:
            write_log(f"ValueError in detect_toggle_command: {ex}")
            return False
        except Exception as ex:
            write_log(f"Unexpected exception in detect_toggle_command: {ex}")
            return False

    def apply(self, brightness, temperature):
        try:
            power, current_bright, current_ct = self._read_state()

            if power != 'on':
                return "off"

            if self._is_in_sync(current_bright, current_ct, brightness, temperature):
                return "in_sync"

            for attempt in range(1, MAX_SYNC_RETRIES + 1):
                self.bulb.set_brightness(brightness)
                self.bulb.set_color_temp(temperature)

                verify_power, verify_bright, verify_ct = self._read_state()
                if verify_power != 'on':
                    return "off"

                if self._is_in_sync(verify_bright, verify_ct, brightness, temperature):
                    if attempt > 1:
                        write_log(f"Lamp synchronized after retry attempt {attempt}.")
                    return "updated"

            write_log(
                "Lamp out of sync after retries "
                f"(target_brightness={brightness}, target_temp={temperature})."
            )
            return "out_of_sync"
        except DeviceException as ex:
            write_log(f"DeviceException: {ex}")
            return "device_error"
        except ValueError as ex:
            write_log(f"ValueError in apply: {ex}")
            return "value_error"
        except Exception as ex:
            write_log(f"Unexpected exception in apply: {ex}")
            return "error"

def run_service():
    profile = CircadianProfile(start_hour=19, duration_minutes=270, reset_hour=8)
    controller = None
    automation_enabled = True
    toggle_command_armed = True
    write_log("Service started")

    while True:
        try:
            if controller is None:
                try:
                    controller = LightController(YEELIGHT_IP, YEELIGHT_TOKEN)
                    write_log("Light controller initialized.")
                except DeviceException as ex:
                    write_log(f"DeviceException during controller initialization: {ex}")
                    time.sleep(CHECK_INTERVAL_SECONDS)
                    continue
                except Exception as ex:
                    write_log(f"Unexpected exception during controller initialization: {ex}")
                    time.sleep(CHECK_INTERVAL_SECONDS)
                    continue

            now = datetime.now()
            target = profile.calculate(now)
            brightness, temperature, phase = target

            toggle_command_active = controller.detect_toggle_command()
            if toggle_command_active and toggle_command_armed:
                automation_enabled = not automation_enabled
                mode = "enabled" if automation_enabled else "disabled"
                write_log(
                    "Toggle command detected "
                    f"({TOGGLE_COMMAND_BRIGHTNESS}%/{TOGGLE_COMMAND_CT}K). Automation {mode}."
                )
                toggle_command_armed = False
            elif not toggle_command_active:
                toggle_command_armed = True

            if automation_enabled:
                controller.apply(brightness, temperature)

            sleep_started_at = datetime.now()
            time.sleep(CHECK_INTERVAL_SECONDS)
            actual_gap = (datetime.now() - sleep_started_at).total_seconds()

            if actual_gap > (CHECK_INTERVAL_SECONDS + RESUME_THRESHOLD_SECONDS):
                if automation_enabled:
                    resumed_now = datetime.now()
                    resumed_brightness, resumed_temperature, resumed_phase = profile.calculate(resumed_now)
                    resume_status = controller.apply(resumed_brightness, resumed_temperature)
                    write_log(
                        "Resume detected after sleep/hibernate "
                        f"(gap={actual_gap:.1f}s, phase={resumed_phase}, status={resume_status})."
                    )
                else:
                    write_log(
                        "Resume detected after sleep/hibernate "
                        f"(gap={actual_gap:.1f}s). Automation disabled; no re-sync applied."
                    )
        except Exception as ex:
            write_log(f"Unexpected exception in loop: {ex}")
            time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    if acquire_single_instance_lock():
        run_service()
    else:
        write_log("Another dimmer instance is already running; duplicate launch skipped.")