"""Standalone GUI for the Raspberry Pi Pico AS7341 spectrometer."""

from __future__ import annotations

import csv
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional, Union
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import serial
import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo


WAVELENGTHS_NM = [415, 445, 480, 515, 555, 590, 630, 680]
PWM_MAX = 65535
DEFAULT_BRIGHTNESS = 10000
DEFAULT_SAMPLES = 3
DEFAULT_SETTLE_S = 0.1
DEFAULT_GAIN = 7
DEFAULT_INTEGRATION_MS = 100
StatusValue = Union[float, int]


@dataclass
class Measurement:
    mode: str
    wavelengths: list[int]
    dark_counts: Optional[list[int]]
    sample_counts: list[int]
    corrected_counts: list[int]
    led1_brightness: int
    led2_brightness: int
    gain: int
    integration_ms: float
    samples: int
    timestamp: str


def clean_serial_line(raw_line: bytes) -> str:
    text = raw_line.decode("utf-8", errors="replace").strip()
    return text.lstrip(">").strip()


def find_pico_ports() -> list[ListPortInfo]:
    ports = list(serial.tools.list_ports.comports())

    def score(port: ListPortInfo) -> tuple[int, int, str]:
        device = port.device.upper()
        description = (port.description or "").upper()
        hwid = (port.hwid or "").upper()
        likely = (
            "239A" in hwid
            or "CIRCUITPY" in description
            or "PICO" in description
            or "USB SERIAL DEVICE" in description
            or "USBMODEM" in device
        )
        cu_preference = 0 if port.device.startswith("/dev/cu.") else 1
        likely_score = 0 if likely else 1
        return likely_score, cu_preference, port.device

    return sorted(ports, key=score)


class PicoClient:
    def __init__(self) -> None:
        self.serial_port: Optional[serial.Serial] = None
        self.lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self.serial_port is not None and self.serial_port.is_open

    @property
    def port_name(self) -> str:
        if self.serial_port is None:
            return ""
        return str(self.serial_port.port)

    def connect(self, port: str) -> list[str]:
        with self.lock:
            self.close()
            ser = serial.Serial(port, baudrate=115200, timeout=0.2, write_timeout=2)
            try:
                ser.dtr = True
                ser.rts = True
            except serial.SerialException:
                pass
            time.sleep(2)
            startup = ser.read_all().decode("utf-8", errors="replace").splitlines()
            ser.reset_input_buffer()
            self.serial_port = ser
        return [line.strip() for line in startup if line.strip()]

    def close(self) -> None:
        if self.serial_port is not None:
            try:
                if self.serial_port.is_open:
                    self.serial_port.close()
            finally:
                self.serial_port = None

    def command(self, command_text: str, timeout: float = 10) -> list[str]:
        with self.lock:
            if not self.is_connected or self.serial_port is None:
                raise RuntimeError("Pico is not connected")

            ser = self.serial_port
            ser.reset_input_buffer()
            ser.write((command_text.strip() + "\r\n").encode("utf-8"))

            deadline = time.time() + timeout
            lines: list[str] = []

            while time.time() < deadline:
                raw_line = ser.readline()
                if not raw_line:
                    continue

                line = clean_serial_line(raw_line)
                if not line:
                    continue
                if line == "DONE":
                    return lines
                lines.append(line)

            raise TimeoutError("Pico did not reply with DONE before the timeout")


def parse_data(lines: list[str]) -> list[int]:
    for line in lines:
        if line.startswith("DATA,"):
            return [int(value) for value in line.split(",")[1:]]
    raise ValueError("No DATA line was returned by the Pico")


def parse_status(lines: list[str]) -> dict[str, StatusValue]:
    status: dict[str, StatusValue] = {}
    for line in lines:
        parts = line.split()
        if len(parts) != 3 or parts[0] != "STATUS":
            continue
        key = parts[1]
        value = parts[2]
        if "." in value:
            status[key] = float(value)
        else:
            status[key] = int(value)
    return status


def parse_optional_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(float(value))


def parse_optional_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def read_measurement_csv(path: Path) -> Measurement:
    with path.open(newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    if not rows:
        raise ValueError("CSV file does not contain any measurement rows")

    fieldnames = set(rows[0].keys())
    if "wavelength_nm" not in fieldnames:
        raise ValueError("CSV file must contain a wavelength_nm column")

    sample_column = "sample_counts"
    if sample_column not in fieldnames and "light_counts" in fieldnames:
        sample_column = "light_counts"

    if sample_column not in fieldnames and "corrected_counts" not in fieldnames:
        raise ValueError("CSV file must contain sample_counts, light_counts, or corrected_counts")

    wavelengths: list[int] = []
    sample_counts: list[int] = []
    corrected_counts: list[int] = []
    dark_counts_values: list[Optional[int]] = []

    for row in rows:
        wavelengths.append(int(float(row["wavelength_nm"])))

        sample_value = parse_optional_int(row.get(sample_column))
        corrected_value = parse_optional_int(row.get("corrected_counts"))
        dark_value = parse_optional_int(row.get("dark_counts"))

        if sample_value is None and corrected_value is None:
            raise ValueError("A row is missing both sample and corrected count values")
        if sample_value is None:
            sample_value = corrected_value
        if corrected_value is None:
            corrected_value = sample_value

        sample_counts.append(int(sample_value))
        corrected_counts.append(int(corrected_value))
        dark_counts_values.append(dark_value)

    has_dark_counts = any(value is not None for value in dark_counts_values)
    dark_counts = None
    if has_dark_counts:
        dark_counts = [0 if value is None else int(value) for value in dark_counts_values]

    first_row = rows[0]
    mode = first_row.get("mode") or "loaded"
    timestamp = first_row.get("timestamp") or path.stem

    led1 = parse_optional_int(first_row.get("led1_brightness"))
    led2 = parse_optional_int(first_row.get("led2_brightness"))
    gain = parse_optional_int(first_row.get("gain"))
    integration_ms = parse_optional_float(first_row.get("integration_ms"))
    samples = parse_optional_int(first_row.get("samples"))

    return Measurement(
        mode=mode,
        wavelengths=wavelengths,
        dark_counts=dark_counts,
        sample_counts=sample_counts,
        corrected_counts=corrected_counts,
        led1_brightness=0 if led1 is None else led1,
        led2_brightness=0 if led2 is None else led2,
        gain=DEFAULT_GAIN if gain is None else gain,
        integration_ms=DEFAULT_INTEGRATION_MS if integration_ms is None else integration_ms,
        samples=1 if samples is None else samples,
        timestamp=timestamp,
    )


class SpectrometerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Pico Fluorescence Spectrometer")
        self.geometry("1160x760")
        self.minsize(980, 640)

        self.client = PicoClient()
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_dark_counts: Optional[list[int]] = None
        self.last_measurement: Optional[Measurement] = None

        self.mode_var = tk.StringVar(value="fluorescence")
        self.port_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Disconnected")
        self.gain_var = tk.IntVar(value=DEFAULT_GAIN)
        self.integration_var = tk.DoubleVar(value=DEFAULT_INTEGRATION_MS)
        self.samples_var = tk.IntVar(value=DEFAULT_SAMPLES)
        self.settle_var = tk.DoubleVar(value=DEFAULT_SETTLE_S)
        self.brightness_var = tk.IntVar(value=DEFAULT_BRIGHTNESS)
        self.connected = False
        self.busy = False

        self._build_ui()
        self.refresh_ports()
        self.after(100, self._process_ui_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        controls = ttk.Frame(self, padding=12)
        controls.grid(row=0, column=0, sticky="ns")
        controls.columnconfigure(0, weight=1)

        plot_area = ttk.Frame(self, padding=(0, 12, 12, 12))
        plot_area.grid(row=0, column=1, sticky="nsew")
        plot_area.columnconfigure(0, weight=1)
        plot_area.rowconfigure(0, weight=1)
        plot_area.rowconfigure(1, weight=0)

        self._build_connection_controls(controls)
        self._build_measurement_controls(controls)
        self._build_plot(plot_area)
        self._build_log(plot_area)

    def _build_connection_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Pico Connection", padding=10)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame.columnconfigure(0, weight=1)

        status_row = ttk.Frame(frame)
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.status_canvas = tk.Canvas(status_row, width=16, height=16, highlightthickness=0)
        self.status_canvas.grid(row=0, column=0, padx=(0, 8))
        self.status_dot = self.status_canvas.create_oval(2, 2, 14, 14, fill="#c23b3b", outline="")
        self.status_label = ttk.Label(status_row, textvariable=self.status_var)
        self.status_label.grid(row=0, column=1, sticky="w")

        ttk.Label(frame, text="Serial port").grid(row=1, column=0, sticky="w")
        self.port_combo = ttk.Combobox(frame, textvariable=self.port_var, width=28, state="readonly")
        self.port_combo.grid(row=2, column=0, sticky="ew", pady=(2, 8))

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, sticky="ew")
        button_row.columnconfigure((0, 1), weight=1)

        self.refresh_button = ttk.Button(button_row, text="Refresh", command=self.refresh_ports)
        self.refresh_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.connect_button = ttk.Button(button_row, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

    def _build_measurement_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Measurement", padding=10)
        frame.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="Mode").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            frame,
            text="Fluorescence (LED1)",
            variable=self.mode_var,
            value="fluorescence",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Radiobutton(
            frame,
            text="Transmittance (LED2)",
            variable=self.mode_var,
            value="transmittance",
        ).grid(row=2, column=0, sticky="w", pady=(2, 8))

        self._add_slider(frame, "Active LED brightness", self.brightness_var, 0, PWM_MAX, 3)
        self._add_spinbox(frame, "Gain", self.gain_var, 0, 10, 6)
        self._add_spinbox(frame, "Integration ms", self.integration_var, 1, 1000, 8)
        self._add_spinbox(frame, "Samples", self.samples_var, 1, 50, 10)
        self._add_spinbox(frame, "Settle seconds", self.settle_var, 0.0, 5.0, 12, increment=0.05)

        action_frame = ttk.Frame(frame)
        action_frame.grid(row=14, column=0, sticky="ew", pady=(12, 0))
        action_frame.columnconfigure((0, 1), weight=1)

        self.apply_button = ttk.Button(action_frame, text="Apply Settings", command=self.apply_settings)
        self.apply_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        self.dark_button = ttk.Button(action_frame, text="Take Dark", command=self.take_dark)
        self.dark_button.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        self.measure_button = ttk.Button(action_frame, text="Measure Sample", command=self.measure_sample)
        self.measure_button.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))

        self.read_button = ttk.Button(action_frame, text="Read Sensor", command=self.read_sensor)
        self.read_button.grid(row=2, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        self.off_button = ttk.Button(action_frame, text="LEDs Off", command=self.leds_off)
        self.off_button.grid(row=2, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))

        self.save_button = ttk.Button(action_frame, text="Save CSV", command=self.save_csv)
        self.save_button.grid(row=3, column=0, sticky="ew", padx=(0, 4))
        self.load_button = ttk.Button(action_frame, text="Load CSV", command=self.load_csv)
        self.load_button.grid(row=3, column=1, sticky="ew", padx=(4, 0))
        self.clear_button = ttk.Button(action_frame, text="Clear Plot", command=self.clear_plot)
        self.clear_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.action_buttons = [
            self.apply_button,
            self.dark_button,
            self.measure_button,
            self.read_button,
            self.off_button,
            self.save_button,
            self.load_button,
            self.clear_button,
        ]

    def _add_slider(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.IntVar,
        low: int,
        high: int,
        row: int,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(8, 0))
        slider = ttk.Scale(
            parent,
            from_=low,
            to=high,
            orient="horizontal",
            command=lambda value: variable.set(int(float(value))),
        )
        slider.set(variable.get())
        slider.grid(row=row + 1, column=0, sticky="ew", pady=(2, 0))
        spin = ttk.Spinbox(parent, from_=low, to=high, textvariable=variable, width=10)
        spin.grid(row=row + 2, column=0, sticky="ew", pady=(2, 0))

    def _add_spinbox(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.Variable,
        low: float,
        high: float,
        row: int,
        increment: float = 1,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(8, 0))
        spin = ttk.Spinbox(
            parent,
            from_=low,
            to=high,
            increment=increment,
            textvariable=variable,
            width=10,
        )
        spin.grid(row=row + 1, column=0, sticky="ew", pady=(2, 0))

    def _build_plot(self, parent: ttk.Frame) -> None:
        figure = Figure(figsize=(7.4, 5.0), dpi=100)
        self.axis = figure.add_subplot(111)
        self.axis.set_xlabel("Wavelength (nm)")
        self.axis.set_ylabel("Sensor counts")
        self.axis.set_title("Spectrometer reading")
        self.axis.grid(True, alpha=0.3)

        self.canvas = FigureCanvasTkAgg(figure, master=parent)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        toolbar_frame = ttk.Frame(parent)
        toolbar_frame.grid(row=1, column=0, sticky="ew")
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.grid(row=0, column=0, sticky="w")

    def _build_log(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Command Log", padding=6)
        frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(frame, height=9, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def refresh_ports(self) -> None:
        ports = find_pico_ports()
        values = [port.device for port in ports]
        self.port_combo["values"] = values
        if values and self.port_var.get() not in values:
            self.port_var.set(values[0])
        self.log("Available ports: " + (", ".join(values) if values else "none"))

    def toggle_connection(self) -> None:
        if self.client.is_connected:
            self.client.close()
            self.set_connected(False, "Disconnected")
            self.log("Disconnected")
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("No port selected", "Select the Pico serial port first.")
            return

        self.run_worker("Connecting", lambda: self.client.connect(port), self.on_connected)

    def on_connected(self, startup_lines: list[str]) -> None:
        self.set_connected(True, "Connected: " + self.client.port_name)
        self.log("Connected to " + self.client.port_name)
        for line in startup_lines:
            self.log("< " + line)
        self.apply_settings()

    def set_connected(self, connected: bool, text: str) -> None:
        self.connected = connected
        self.status_var.set(text)
        self.status_canvas.itemconfigure(self.status_dot, fill="#2e9d57" if connected else "#c23b3b")
        self.connect_button.configure(text="Disconnect" if connected else "Connect")

    def run_worker(self, label: str, worker, on_success=None) -> None:
        if self.busy:
            self.log("Busy: wait for the current command to finish")
            return

        self.busy = True
        self.set_actions_enabled(False)
        self.log(label + "...")

        def target() -> None:
            try:
                result = worker()
                self.ui_queue.put(("success", (label, result, on_success)))
            except Exception as exc:
                self.ui_queue.put(("error", (label, exc)))

        threading.Thread(target=target, daemon=True).start()

    def _process_ui_queue(self) -> None:
        while True:
            try:
                event, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self.log(str(payload))
                continue

            self.busy = False
            self.set_actions_enabled(True)

            if event == "success":
                label, result, on_success = payload
                self.log(label + " complete")
                if on_success is not None:
                    on_success(result)
            elif event == "error":
                label, exc = payload
                self.log(label + " failed: " + str(exc))
                if not self.client.is_connected:
                    self.set_connected(False, "Disconnected")
                messagebox.showerror(label + " failed", str(exc))

        self.after(100, self._process_ui_queue)

    def set_actions_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.refresh_button.configure(state=state)
        self.connect_button.configure(state=state)
        for button in self.action_buttons:
            button.configure(state=state)

    def active_led_values(self) -> tuple[int, int]:
        brightness = int(self.brightness_var.get())
        brightness = max(0, min(PWM_MAX, brightness))
        if self.mode_var.get() == "fluorescence":
            return brightness, 0
        return 0, brightness

    def apply_settings(self) -> None:
        def worker() -> dict[str, StatusValue]:
            self.send_logged_command(f"gain {int(self.gain_var.get())}", timeout=5)
            self.send_logged_command(f"integration {float(self.integration_var.get())}", timeout=5)
            return self.status_command()

        self.run_worker("Applying settings", worker, self.on_status)

    def take_dark(self) -> None:
        samples = int(self.samples_var.get())

        def worker() -> list[int]:
            lines = self.send_logged_command(f"dark {samples}", timeout=12)
            return parse_data(lines)

        self.run_worker("Taking dark reading", worker, self.on_dark_reading)

    def read_sensor(self) -> None:
        samples = int(self.samples_var.get())
        led1, led2 = self.active_led_values()

        def worker() -> tuple[list[int], int, int]:
            self.send_logged_command(f"leds {led1} {led2}", timeout=5)
            lines = self.send_logged_command(f"read {samples}", timeout=12)
            return parse_data(lines), led1, led2

        self.run_worker("Reading sensor", worker, self.on_sensor_reading)

    def measure_sample(self) -> None:
        samples = int(self.samples_var.get())
        settle_s = float(self.settle_var.get())
        led1, led2 = self.active_led_values()

        def worker() -> tuple[list[int], int, int, dict[str, StatusValue]]:
            status = self.status_command()
            lines = self.send_logged_command(f"measure {led1} {led2} {samples} {settle_s}", timeout=18)
            return parse_data(lines), led1, led2, status

        self.run_worker("Measuring sample", worker, self.on_sample_measurement)

    def leds_off(self) -> None:
        self.run_worker("Switching LEDs off", lambda: self.send_logged_command("off", timeout=5))

    def status_command(self) -> dict[str, StatusValue]:
        lines = self.send_logged_command("status", timeout=5)
        return parse_status(lines)

    def send_logged_command(self, command_text: str, timeout: float) -> list[str]:
        self.ui_queue.put(("log", "> " + command_text))
        lines = self.client.command(command_text, timeout=timeout)
        for line in lines:
            self.ui_queue.put(("log", "< " + line))
        errors = [line for line in lines if line.startswith("ERR")]
        if errors:
            raise RuntimeError(errors[0])
        return lines

    def on_status(self, status: dict[str, StatusValue]) -> None:
        if not status:
            return
        self.log(
            "Pico status: "
            + ", ".join(f"{key}={value}" for key, value in sorted(status.items()))
        )

    def on_dark_reading(self, dark_counts: list[int]) -> None:
        self.last_dark_counts = dark_counts
        self.plot_counts(dark_counts, "Dark reading", "Dark counts")
        self.log("Dark reading stored")

    def on_sensor_reading(self, payload: tuple[list[int], int, int]) -> None:
        counts, led1, led2 = payload
        title = self.current_mode_label() + " live sensor reading"
        self.plot_counts(counts, title, "Counts", led1=led1, led2=led2)

    def on_sample_measurement(
        self,
        payload: tuple[list[int], int, int, dict[str, StatusValue]],
    ) -> None:
        sample_counts, led1, led2, status = payload
        dark_counts = self.last_dark_counts
        if dark_counts is None:
            corrected_counts = sample_counts[:]
            self.log("No dark reading stored; plotting raw sample counts")
        else:
            corrected_counts = [
                sample - dark for sample, dark in zip(sample_counts, dark_counts)
            ]

        mode = self.mode_var.get()
        title = self.current_mode_label() + " sample measurement"
        self.plot_counts(corrected_counts, title, "Dark-corrected counts", led1=led1, led2=led2)

        self.last_measurement = Measurement(
            mode=mode,
            wavelengths=WAVELENGTHS_NM[:],
            dark_counts=dark_counts[:] if dark_counts is not None else None,
            sample_counts=sample_counts,
            corrected_counts=corrected_counts,
            led1_brightness=led1,
            led2_brightness=led2,
            gain=int(status.get("gain", self.gain_var.get())),
            integration_ms=float(status.get("integration_ms", self.integration_var.get())),
            samples=int(self.samples_var.get()),
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.log("Sample measurement stored")

    def plot_counts(
        self,
        counts: list[int],
        title: str,
        ylabel: str,
        wavelengths: Optional[list[int]] = None,
        led1: Optional[int] = None,
        led2: Optional[int] = None,
    ) -> None:
        if wavelengths is None:
            wavelengths = WAVELENGTHS_NM

        self.axis.clear()
        self.axis.plot(wavelengths, counts, marker="o", linewidth=2)
        self.axis.set_xlabel("Wavelength (nm)")
        self.axis.set_ylabel(ylabel)
        self.axis.set_title(title)
        self.axis.grid(True, alpha=0.3)

        if led1 is not None and led2 is not None:
            self.axis.text(
                0.01,
                0.98,
                f"LED1={led1}  LED2={led2}",
                transform=self.axis.transAxes,
                va="top",
            )

        self.canvas.draw_idle()

    def clear_plot(self) -> None:
        self.axis.clear()
        self.axis.set_xlabel("Wavelength (nm)")
        self.axis.set_ylabel("Sensor counts")
        self.axis.set_title("Spectrometer reading")
        self.axis.grid(True, alpha=0.3)
        self.canvas.draw_idle()
        self.log("Plot cleared")

    def save_csv(self) -> None:
        if self.last_measurement is None:
            messagebox.showinfo("No measurement", "Take a sample measurement before saving.")
            return

        default_name = f"{self.last_measurement.mode}_measurement.csv"
        path = filedialog.asksaveasfilename(
            title="Save measurement CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return

        self.write_measurement_csv(Path(path), self.last_measurement)
        self.log("Saved " + path)

    def load_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Load measurement CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            measurement = read_measurement_csv(Path(path))
        except Exception as exc:
            messagebox.showerror("Load CSV failed", str(exc))
            self.log("Load CSV failed: " + str(exc))
            return

        self.last_measurement = measurement
        self.last_dark_counts = (
            measurement.dark_counts[:] if measurement.dark_counts is not None else None
        )

        mode_label = measurement.mode.replace("_", " ").title()
        title = f"Loaded {mode_label} measurement"
        self.plot_counts(
            measurement.corrected_counts,
            title,
            "Dark-corrected counts",
            wavelengths=measurement.wavelengths,
            led1=measurement.led1_brightness,
            led2=measurement.led2_brightness,
        )
        self.log("Loaded " + path)

    def write_measurement_csv(self, path: Path, measurement: Measurement) -> None:
        with path.open("w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(
                [
                    "timestamp",
                    "mode",
                    "wavelength_nm",
                    "dark_counts",
                    "sample_counts",
                    "corrected_counts",
                    "led1_brightness",
                    "led2_brightness",
                    "gain",
                    "integration_ms",
                    "samples",
                ]
            )
            for index, wavelength in enumerate(measurement.wavelengths):
                dark_value = ""
                if measurement.dark_counts is not None:
                    dark_value = measurement.dark_counts[index]
                writer.writerow(
                    [
                        measurement.timestamp,
                        measurement.mode,
                        wavelength,
                        dark_value,
                        measurement.sample_counts[index],
                        measurement.corrected_counts[index],
                        measurement.led1_brightness,
                        measurement.led2_brightness,
                        measurement.gain,
                        measurement.integration_ms,
                        measurement.samples,
                    ]
                )

    def current_mode_label(self) -> str:
        if self.mode_var.get() == "fluorescence":
            return "Fluorescence"
        return "Transmittance"

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def on_close(self) -> None:
        try:
            if self.client.is_connected:
                try:
                    self.client.command("off", timeout=2)
                except Exception:
                    pass
            self.client.close()
        finally:
            self.destroy()


def main() -> None:
    app = SpectrometerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
