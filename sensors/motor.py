import time

from gpiozero import Servo

SERVO_PIN = 18
MIN_PULSE_WIDTH = 0.0005
MAX_PULSE_WIDTH = 0.0025

CLOSED_VALUE = -0.778
OPEN_VALUE = 0.0
CLOSED_DEGREES = 10
OPEN_DEGREES = 45

STEP = 0.05
STEP_SLEEP = 0.02
SETTLE_SLEEP = 0.5

current_position = 10

servo = None
try:
    servo = Servo(
        SERVO_PIN,
        min_pulse_width=MIN_PULSE_WIDTH,
        max_pulse_width=MAX_PULSE_WIDTH,
    )
    servo.value = OPEN_VALUE
except Exception as exc:
    print(f"Lucy Pi motor: failed to initialise servo on GPIO {SERVO_PIN} — {exc}")


def _value_to_degrees(value: float) -> float:
    return value * 45.0 + 45.0


def _degrees_to_value(degrees: float) -> float:
    clamped = max(CLOSED_DEGREES, min(OPEN_DEGREES, degrees))
    return (clamped - 45.0) / 45.0


def close_eyelids() -> None:
    global current_position
    if servo is None:
        print("Lucy Pi motor: open_eyelids skipped — servo not available.")
        return

    value = _degrees_to_value(current_position)
    while value < OPEN_VALUE:
        value = min(value + STEP, OPEN_VALUE)
        servo.value = value
        current_position = _value_to_degrees(value)
        if value < OPEN_VALUE:
            time.sleep(STEP_SLEEP)

    time.sleep(SETTLE_SLEEP)


def open_eyelids() -> None:
    global current_position
    if servo is None:
        print("Lucy Pi motor: close_eyelids skipped — servo not available.")
        return

    value = _degrees_to_value(current_position)
    while value > CLOSED_VALUE:
        value = max(value - STEP, CLOSED_VALUE)
        servo.value = value
        current_position = _value_to_degrees(value)
        if value > CLOSED_VALUE:
            time.sleep(STEP_SLEEP)

    time.sleep(SETTLE_SLEEP)


def get_position() -> float:
    global current_position
    if servo is None:
        return current_position

    try:
        value = servo.value
        if value is not None:
            current_position = _value_to_degrees(value)
    except Exception as exc:
        print(f"Lucy Pi motor: get_position failed — {exc}")

    return current_position


def set_position(degrees: float) -> None:
    global current_position
    if servo is None:
        print("Lucy Pi motor: set_position skipped — servo not available.")
        return

    clamped = max(CLOSED_DEGREES, min(OPEN_DEGREES, degrees))
    try:
        servo.value = _degrees_to_value(clamped)
        current_position = clamped
    except Exception as exc:
        print(f"Lucy Pi motor: set_position failed — {exc}")
