# Setup

## 1. Pico Setup

Install CircuitPython for Raspberry Pi Pico, then confirm the board appears as a USB drive named `CIRCUITPY`.

Copy the Pico firmware:

Windows:

```powershell
Copy-Item .\pico\code.py F:\code.py
```

macOS:

```bash
cp pico/code.py /Volumes/CIRCUITPY/code.py
```

The Pico must have these CircuitPython library files/folders in `CIRCUITPY/lib`:

```text
adafruit_as7341.mpy
adafruit_bus_device/
adafruit_register/
```

Use the CircuitPython library bundle version that matches the CircuitPython version on the Pico.

## 2. Laptop Python Setup

Create or activate a Python environment, then install:

```bash
pip install -r requirements.txt
```

Conda users can also install the same packages into their chosen environment:

```bash
conda activate base
pip install -r requirements.txt
```

## 3. Run The Notebook

Open:

```text
notebooks/spectrometer_control.ipynb
```

Run cells from top to bottom. The notebook should print the detected serial ports and select the Pico automatically.

In the sample measurement cell, choose the mode:

```python
MODE = "fluorescence"   # uses LED1 / GP19
MODE = "transmittance"  # uses LED2 / GP21
```

Typical port names:

```text
Windows: COM5
macOS: /dev/cu.usbmodem1101
```

Generated measurements are saved to:

```text
data/spectrometer_reading.csv
```
