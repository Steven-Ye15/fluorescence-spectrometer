# Spectrometer GUI

Standalone desktop GUI for the Pico spectrometer. It does not use the notebook.

## Run

Install the project requirements first:

```bash
pip install -r requirements.txt
```

Windows:

```powershell
python .\gui\spectrometer_gui.py
```

macOS:

```bash
python3 gui/spectrometer_gui.py
```

If you use Conda on macOS, run it from the activated Conda environment. Conda's Python normally includes Tkinter, which the GUI uses for the desktop window.

## macOS Serial Ports

The Pico usually appears as a port like:

```text
/dev/cu.usbmodem1101
```

Use the `/dev/cu.*` port, not the `/dev/tty.*` port, if both appear.

Only one program can use the Pico serial port at a time. Close DataSpell notebooks, Mu, Thonny, or serial monitors before connecting from the GUI.

## Loading Saved Measurements

Use **Load CSV** to reopen a saved measurement and redraw the graph. The loader supports CSV files saved by this GUI and the earlier notebook-style files with `light_counts` / `corrected_counts` columns.
