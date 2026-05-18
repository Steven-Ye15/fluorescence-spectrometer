# Fluorescence Spectrometer

CircuitPython and Jupyter/DataSpell control code for a Raspberry Pi Pico fluorescence spectrometer using an AS7341 spectral light sensor.

## Project Layout

```text
pico/code.py                  CircuitPython program to copy onto CIRCUITPY
notebooks/spectrometer_control.ipynb
                              Laptop-side notebook for serial control and plotting
examples/spectrometer_reading_example.csv
                              Example output format
docs/setup.md                 Full setup instructions
docs/troubleshooting.md       Common fixes
requirements.txt              Python packages for the laptop notebook
```

Do not put a file called `code.py` in the repository root. Jupyter imports Python's built-in `code` module when starting a kernel, and a root-level `code.py` can make the kernel crash.

## Hardware Connections

| Part | Pico pin |
| --- | --- |
| AS7341 SCL | GP5 |
| AS7341 SDA | GP4 |
| AS7341 VIN | 3V3 |
| AS7341 GND | GND |
| LED 1 PWM | GP19 |
| LED 2 PWM | GP21 |

## Quick Start

1. Install CircuitPython on the Pico.
2. Copy `pico/code.py` to the Pico drive as `code.py`.
   - Windows example: `Copy-Item .\pico\code.py F:\code.py`
   - macOS example: `cp pico/code.py /Volumes/CIRCUITPY/code.py`
3. Make sure the Pico has the AS7341 CircuitPython libraries in `CIRCUITPY/lib`.
4. Install the notebook requirements:

```bash
pip install -r requirements.txt
```

5. Open `notebooks/spectrometer_control.ipynb` in DataSpell, JupyterLab, or VS Code.
6. In the sample measurement cell, set `MODE` to `"fluorescence"` or `"transmittance"`.
7. Run the notebook cells from top to bottom.

The notebook detects Windows `COM*` ports and macOS `/dev/cu.usbmodem*` ports automatically.

Measurement modes:

| Mode | LED used |
| --- | --- |
| Fluorescence | LED1 / GP19 |
| Transmittance | LED2 / GP21 |

## Pico Serial Commands

The notebook sends these commands to the Pico:

```text
status
off
gain 7
integration 100
dark 3
measure 10000 0 3 0.1
read 1
```

The Pico replies with parseable CSV-style lines:

```text
WAVELENGTHS,415,445,480,515,555,590,630,680
DATA,31,73,89,159,270,425,420,266
DONE
```

## Notes

Only one program can use the Pico serial port at once. Close Mu, Thonny, Arduino Serial Monitor, or old notebook sessions before running the notebook.
