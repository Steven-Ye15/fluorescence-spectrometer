# CircuitPython code for the Raspberry Pi Pico fluorescence spectrometer.
# Copy this file to CIRCUITPY as code.py.

import time

import board
import busio
import digitalio
import pwmio
from adafruit_as7341 import AS7341


WAVELENGTHS_NM = (415, 445, 480, 515, 555, 590, 630, 680)
PWM_MAX = 65535
DEFAULT_GAIN = 7
DEFAULT_INTEGRATION_MS = 100
INTEGRATION_STEP_SIZE = 9999


print("")
print("Pico AS7341 fluorescence spectrometer starting")

status_led = digitalio.DigitalInOut(board.GP25)
status_led.direction = digitalio.Direction.OUTPUT

i2c = busio.I2C(scl=board.GP5, sda=board.GP4)

sensor = None
try:
    sensor = AS7341(i2c)
    print("OK sensor connected")
except Exception as exc:
    print("ERR sensor not found: " + str(exc))
    print("Check AS7341 wiring: SCL=GP5, SDA=GP4, 3V3, GND")

led1 = pwmio.PWMOut(board.GP19, frequency=1000, duty_cycle=0)
led2 = pwmio.PWMOut(board.GP21, frequency=1000, duty_cycle=0)


def clamp_int(value, low, high):
    value = int(value)
    if value < low:
        return low
    if value > high:
        return high
    return value


def require_sensor():
    if sensor is None:
        raise RuntimeError("AS7341 sensor is not connected")


def set_led(led, brightness, report=True):
    brightness = clamp_int(brightness, 0, PWM_MAX)
    led.duty_cycle = brightness
    if report:
        if led is led1:
            print("OK led1 " + str(brightness))
        else:
            print("OK led2 " + str(brightness))
    return brightness


def set_gain(gain):
    require_sensor()
    gain = clamp_int(gain, 0, 10)
    sensor.gain = gain
    print("OK gain " + str(sensor.gain))


def set_integration(int_time_ms):
    require_sensor()
    int_time_ms = float(int_time_ms)
    if int_time_ms < 1:
        int_time_ms = 1

    sensor.astep = INTEGRATION_STEP_SIZE
    atime = int(int_time_ms * 1000 / (2.78 * (INTEGRATION_STEP_SIZE + 1)))
    sensor.atime = clamp_int(atime, 0, 255)

    actual_ms = (1 + sensor.atime) * (1 + sensor.astep) * 0.00278
    print("OK integration_ms " + str(round(actual_ms, 2)))


def read_channels(sample_count=1):
    require_sensor()
    sample_count = clamp_int(sample_count, 1, 50)
    totals = [0, 0, 0, 0, 0, 0, 0, 0]

    status_led.value = True
    for _ in range(sample_count):
        channels = sensor.all_channels
        for index in range(8):
            totals[index] += int(channels[index])
        if sample_count > 1:
            time.sleep(0.02)
    status_led.value = False

    values = []
    for total in totals:
        values.append(int(round(total / sample_count)))

    print("WAVELENGTHS," + ",".join(str(w) for w in WAVELENGTHS_NM))
    print("DATA," + ",".join(str(v) for v in values))


def measure(led1_brightness, led2_brightness=0, sample_count=1, settle_s=0.1):
    set_led(led1, led1_brightness, report=False)
    set_led(led2, led2_brightness, report=False)
    time.sleep(float(settle_s))
    read_channels(sample_count)
    set_led(led1, 0, report=False)
    set_led(led2, 0, report=False)
    print("OK measure complete")


def print_status():
    require_sensor()
    actual_ms = (1 + sensor.atime) * (1 + sensor.astep) * 0.00278
    print("STATUS gain " + str(sensor.gain))
    print("STATUS integration_ms " + str(round(actual_ms, 2)))
    print("STATUS led1 " + str(led1.duty_cycle))
    print("STATUS led2 " + str(led2.duty_cycle))


def print_help():
    print("HELP commands:")
    print("HELP led1 <0-65535>")
    print("HELP led2 <0-65535>")
    print("HELP leds <led1> <led2>")
    print("HELP gain <0-10>")
    print("HELP integration <ms>")
    print("HELP read [samples]")
    print("HELP measure <led1> [led2] [samples] [settle_s]")
    print("HELP dark [samples]")
    print("HELP status")
    print("HELP off")


def run_command(command):
    command = command.strip()
    if not command:
        print("ERR empty command")
        print("DONE")
        return

    parts = command.split()
    name = parts[0].lower()

    try:
        if name in ("help", "?"):
            print_help()
        elif name == "led1":
            set_led(led1, parts[1])
        elif name == "led2":
            set_led(led2, parts[1])
        elif name == "leds":
            set_led(led1, parts[1], report=False)
            set_led(led2, parts[2], report=False)
            print("OK led1 " + str(led1.duty_cycle))
            print("OK led2 " + str(led2.duty_cycle))
        elif name == "gain":
            set_gain(parts[1])
        elif name in ("integration", "int"):
            set_integration(parts[1])
        elif name in ("read", "channels"):
            samples = 1
            if len(parts) > 1:
                samples = parts[1]
            read_channels(samples)
        elif name == "measure":
            led1_value = parts[1]
            led2_value = 0
            samples = 1
            settle_s = 0.1
            if len(parts) > 2:
                led2_value = parts[2]
            if len(parts) > 3:
                samples = parts[3]
            if len(parts) > 4:
                settle_s = parts[4]
            measure(led1_value, led2_value, samples, settle_s)
        elif name == "dark":
            set_led(led1, 0, report=False)
            set_led(led2, 0, report=False)
            samples = 1
            if len(parts) > 1:
                samples = parts[1]
            read_channels(samples)
        elif name == "status":
            print_status()
        elif name == "off":
            set_led(led1, 0, report=False)
            set_led(led2, 0, report=False)
            print("OK leds off")
        else:
            print("ERR unknown command: " + name)
            print_help()
    except IndexError:
        print("ERR missing value for command: " + name)
    except Exception as exc:
        print("ERR " + name + ": " + str(exc))

    print("DONE")


set_led(led1, 0, report=False)
set_led(led2, 0, report=False)

if sensor is not None:
    set_gain(DEFAULT_GAIN)
    set_integration(DEFAULT_INTEGRATION_MS)

print("OK ready")
print_help()

while True:
    run_command(input(">"))
