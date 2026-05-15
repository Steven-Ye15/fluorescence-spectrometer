# Troubleshooting

## Jupyter Kernel Dies Immediately

Check that there is no `code.py` file in the repository root. The Pico file belongs at:

```text
pico/code.py
```

Only the `CIRCUITPY` drive should contain a top-level `code.py`.

## Permission Denied Or Resource Busy On Serial Port

Only one app can open the Pico serial port at a time. Close other notebook kernels, Mu, Thonny, Arduino Serial Monitor, or any terminal serial monitor.

In a notebook, run:

```python
ser.close()
```

Then reconnect.

## Pico Does Not Appear In The Notebook

Check that the Pico is connected by USB and visible as `CIRCUITPY`.

On Windows, the serial port is usually `COM*`.

On macOS, use the `/dev/cu.usbmodem*` device rather than `/dev/tty.usbmodem*`.

## ModuleNotFoundError: No Module Named serial

Install pyserial in the same environment used by the notebook:

```bash
pip install pyserial
```

## ModuleNotFoundError: No Module Named board

This usually means the Pico CircuitPython file is being run on the laptop by accident. `pico/code.py` is for the Raspberry Pi Pico only.

The laptop should run the notebook, not the Pico firmware.
