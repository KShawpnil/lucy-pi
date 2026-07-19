"""Eyelid servo motor control for Lucy Pi (GPIO 25, Raspberry Pi 5)."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import time

from gpiozero import Device, Servo
from gpiozero.pins.rpi import RPiGPIOFactory

CLOSED_DEGREES = 10
OPEN_DEGREES = 45
MIN_DEGREES = 10
MAX_DEGREES = 45

SERVO_PIN = 25
MIN_PULSE_WIDTH = 0.001
MAX_PULSE_WIDTH = 0.002

OPEN_STEP_SLEEP = 0.02
CLOSE_STEP_SLEEP = 0.03
SETTLE_SLEEP = 0.5

current_position: float = CLOSED_DEGREES


def _create_servo() -> Servo:
    return Servo(
        SERVO_PIN,
        min_pulse_width=MIN_PULSE_WIDTH,
        max_pulse_width=MAX_PULSE_WIDTH,
    )


servo: Servo | None = None
try:
    servo = _create_servo()
except Exception as exc:
    error_text = str(exc).lower()
    if "pigpio" in error_text or "failed to connect" in error_text:
        try:
            Device.pin_factory = RPiGPIOFactory()
            servo = _create_servo()
            print("Lucy Pi motor: pigpio unavailable, using default pin factory.")
        except Exception as fallback_exc:
            servo = None
            print(
                f"Lucy Pi motor: failed to initialise servo on GPIO {SERVO_PIN} "
                f"— {fallback_exc}"
            )
    else:
        servo = None
        print(f"Lucy Pi motor: failed to initialise servo on GPIO {SERVO_PIN} — {exc}")


def degrees_to_servo_value(degrees: float) -> float:
    """Map 0–90° to gpiozero servo range -1..1 (10° → -0.78, 45° → 0.0)."""
    return (degrees / 90.0) * 2.0 - 1.0


def servo_value_to_degrees(value: float) -> float:
    """Map gpiozero servo value -1..1 back to degrees."""
    return ((value + 1.0) / 2.0) * 90.0


def _clamp_degrees(degrees: float) -> float:
    return max(MIN_DEGREES, min(MAX_DEGREES, degrees))


def _apply_degrees(degrees: float) -> None:
    global current_position
    if servo is None:
        raise RuntimeError(
            f"servo on GPIO {SERVO_PIN} is not available (not connected or no access)"
        )
    clamped = _clamp_degrees(degrees)
    servo.value = degrees_to_servo_value(clamped)
    current_position = clamped


def open_eyelids() -> None:
    """Smoothly open eyelids from 10° (closed) to 45° (open)."""
    global current_position
    print("Eyelids opening")
    try:
        start = int(round(current_position))
        if start > OPEN_DEGREES:
            start = OPEN_DEGREES
        if start < CLOSED_DEGREES:
            start = CLOSED_DEGREES

        for degree in range(start, OPEN_DEGREES + 1):
            _apply_degrees(float(degree))
            if degree < OPEN_DEGREES:
                time.sleep(OPEN_STEP_SLEEP)
    except Exception as exc:
        print(f"Lucy Pi motor: open_eyelids failed — {exc}")
        return

    time.sleep(SETTLE_SLEEP)
    print("Eyelids fully open")


def close_eyelids() -> None:
    """Smoothly close eyelids from 45° (open) to 10° (closed)."""
    global current_position
    print("Eyelids closing")
    try:
        start = int(round(current_position))
        if start > OPEN_DEGREES:
            start = OPEN_DEGREES
        if start < CLOSED_DEGREES:
            start = CLOSED_DEGREES

        for degree in range(start, CLOSED_DEGREES - 1, -1):
            _apply_degrees(float(degree))
            if degree > CLOSED_DEGREES:
                time.sleep(CLOSE_STEP_SLEEP)
    except Exception as exc:
        print(f"Lucy Pi motor: close_eyelids failed — {exc}")
        return

    time.sleep(SETTLE_SLEEP)
    print("Eyelids fully closed")


def set_position(degrees: float) -> None:
    """Move the servo directly to `degrees` (clamped between 10 and 45)."""
    try:
        _apply_degrees(degrees)
    except Exception as exc:
        print(f"Lucy Pi motor: set_position failed — {exc}")


def get_position() -> float:
    """Return the current eyelid angle in degrees."""
    global current_position
    if servo is None:
        return current_position
    try:
        value = servo.value
        if value is None:
            return current_position
        current_position = _clamp_degrees(servo_value_to_degrees(value))
        return current_position
    except Exception as exc:
        print(f"Lucy Pi motor: get_position failed — {exc}")
        return current_position
