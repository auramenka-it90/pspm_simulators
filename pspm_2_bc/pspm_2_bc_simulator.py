import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import font as tkfont
import serial
import serial.tools.list_ports
import threading
import time
from datetime import datetime
import json
import os
import sys
import struct
import math
import random
import ctypes

# Определение реальной папки программы (работает и в .py, и в .exe)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ================================================================================
# HELP TEXTS
# ================================================================================
HELP_EN = """PSPM SIMULATOR - DETAILED HELP & SPECIFICATION
================================================================================

1. UART SETTINGS (Left Panel)
   COM Port     - Select serial port (COM1, COM2, COM3...)
   Baudrate     - Data rate, default 921600
   Parity       - Even (per PSPM interface spec)
   Data bits    - 8
   Stop bits    - 1
   Period (ms)  - Interval for Stream mode (10..1000 ms)

2. CONNECTION
   Connect/Disconnect - Opens/closes the COM port
   Indicator          - Red = Disconnected, Green = Connected

3. PACKET STRUCTURE PSPM -> BC (32 bytes)
   Byte 0       - 0xAA (Start byte, adjustable)
   Bytes 1..28  - D[0]..D[27] (Data field 28 bytes)
   Bytes 29-30  - CRC16-CCITT (Little endian)
   Byte 31      - XOR_ALL

4. PACKET STRUCTURE BC -> PSPM (32 bytes)
   Byte 0       - 0x55 (Start byte, adjustable)
   Bytes 1..28  - D[0]..D[27] (Data field 28 bytes)
   Bytes 29-30  - CRC16-CCITT (Little endian)
   Byte 31      - XOR_ALL

5. DATA FIELD D[0..27] - PSPM -> BC (TRANSMIT)
   All values are signed int16 (little endian), except pressure (uint16).
   Bytes 0..1   - ERR_EL     Elevation error   +/-400 arcmin  (1 LSB = 400/32768)
   Bytes 2..3   - ERR_EL_10  Elev. error x10   +/-40 arcmin   (1 LSB = 40/32768)
   Bytes 4..5   - ERR_AZ     Azimuth error     +/-400 arcmin  (1 LSB = 400/32768)
   Bytes 6..7   - ERR_AZ_10  Azim. error x10   +/-40 arcmin   (1 LSB = 40/32768)
   Bytes 8..9   - W_EL       Elev. ang. rate   +/-5 deg/s     (1 LSB = 5/32768)
   Bytes 10..11 - W_AZ       Azim. ang. rate   +/-5 deg/s     (1 LSB = 5/32768)
   Bytes 12..13 - GUN_POS    Gun position      +/-15 deg      (1 LSB = 30/65536)
   Bytes 14..15 - ROLL       Roll angle        +/-180 deg     (1 LSB = 360/65536)
   Bytes 16..17 - PITCH      Pitch angle       +/-180 deg     (1 LSB = 360/65536)
   Bytes 18..19 - V_TANK     Tank speed        +/-20 m/s      (1 LSB = 40/65536)
   Bytes 20..21 - V_WIND     Crosswind speed   +/-25 m/s      (1 LSB = 50/65536)
   Bytes 22..23 - COS_FI     Turret cosine     -1.0 .. +1.0   (1 LSB = 1/32767)
   Bytes 24..25 - P_A        Pressure (uint16) 0..1500 mmHg   (1 LSB = 1500/65536)
   Byte 26      - STATUS: [0] GLOBAL_ERROR [1] ADC_ERROR [2] FPGA_ERROR
                  [3] BMP280_ERROR (pressure sensor fault, P_A sent as 0)
   Byte 27      - RESERVED (Always 0)

6. DATA FIELD D[0..27] - BC -> PSPM (RECEIVE)
   Bytes 1..2   - ASEL_A     Elevation AC DAC code      int16
   Bytes 3..4   - ASEL_D     Elevation DC DAC code      int16
   Bytes 5..6   - ASAZ_A     Azimuth AC DAC code        int16
   Bytes 7..8   - ASAZ_D     Azimuth DC DAC code        int16
   Bytes 9..10  - SCALE_ASEL Elevation scale            int16
   Bytes 11..12 - SCALE_GPS  Gun position scale         int16
   Bytes 13..14 - ADJ_0_ALPHA Elevation zero adjust     int16
   Bytes 15..16 - SCALE_ASAZ Azimuth scale              int16
   Bytes 17..18 - SCALE_HPS  Hatch position scale       int16
   Bytes 19..20 - ADJ_0_BETA Azimuth zero adjust        int16
   Bytes 21..28 - RESERVED (Always 0)

7. CONTROL BUTTONS
   Send Packet    - Send single packet
   Start Stream   - Send continuously (Interval = Period)
   Reset to Zero  - Zero all sensors (pressure resets to 750 mmHg)
   TX Start / RX Start - Override start bytes
   Send on Change - Instantly transmit the packet upon any parameter adjustment.
   Reset Counters - Reset diagnostic counters
   Clear Log      - Clear text output

8. SIGNAL GENERATOR
   Applies a waveform (Sine, Square, Triangle, Noise) to any single sensor
   field while streaming. The value is clamped to the sensor range.

9. LOGGING & SETTINGS
    Log View         - Show log in window
    Save Log to File - Write log to file
    Freeze View      - Suspend GUI log redraw (file logging continues)
    Font             - Configure font (saved in JSON)
    Check RX CRC16   - If disabled, only XOR is checked on reception

10. CRC16-CCITT
    Polynomial: 0x1021, init: 0xFFFF

11. XOR_ALL
    xor_all = (Start) xor D[0] xor ... xor D[27] xor CRC_L xor CRC_H
================================================================================
"""

HELP_RU = """ИМИТАТОР МПОС (PSPM) - ПОДРОБНАЯ СПРАВКА И СПЕЦИФИКАЦИЯ
================================================================================

1. UART НАСТРОЙКИ (левая панель)
   COM Port     - выбор последовательного порта (COM1, COM2, COM3...)
   Baudrate     - скорость обмена, по умолчанию 921600
   Parity       - Even (по спецификации интерфейса PSPM)
   Data bits    - 8
   Stop bits    - 1
   Period (ms)  - интервал отправки в режиме Stream (10..1000 мс)

2. ПОДКЛЮЧЕНИЕ
   Кнопка Connect/Disconnect - открывает/закрывает COM-порт
   Индикатор Connected       - красный = отключён, зелёный = подключён

3. СТРУКТУРА ПАКЕТА PSPM -> BC (32 байта)
   Байт 0       - 0xAA (стартовый байт, можно менять)
   Байты 1..28  - D[0]..D[27] (поле данных 28 байт)
   Байты 29-30  - CRC16-CCITT (little endian)
   Байт 31      - XOR_ALL

4. СТРУКТУРА ПАКЕТА BC -> PSPM (32 байта)
   Байт 0       - 0x55 (стартовый байт, можно менять)
   Байты 1..28  - D[0]..D[27] (поле данных 28 байт)
   Байты 29-30  - CRC16-CCITT (little endian)
   Байт 31      - XOR_ALL

5. ПОЛЕ D[0..27] - PSPM -> BC (ПЕРЕДАЧА)
   Все величины - знаковый int16 (little endian), кроме давления (uint16).
   Байты 0..1   - ERR_EL     ошибка вертикали    +/-400 угл.мин
   Байты 2..3   - ERR_EL_10  ошибка верт. x10    +/-40 угл.мин
   Байты 4..5   - ERR_AZ     ошибка азимута      +/-400 угл.мин
   Байты 6..7   - ERR_AZ_10  ошибка азим. x10    +/-40 угл.мин
   Байты 8..9   - W_EL       уг. скорость верт.  +/-5 град/с
   Байты 10..11 - W_AZ       уг. скорость азим.  +/-5 град/с
   Байты 12..13 - GUN_POS    положение пушки     +/-15 град
   Байты 14..15 - ROLL       крен                +/-180 град
   Байты 16..17 - PITCH      тангаж              +/-180 град
   Байты 18..19 - V_TANK     скорость танка      +/-20 м/с
   Байты 20..21 - V_WIND     поперечный ветер    +/-25 м/с
   Байты 22..23 - COS_FI     косинус угла башни  -1.0 .. +1.0
   Байты 24..25 - P_A        давление (uint16)   0..1500 мм рт.ст
   Байт 26      - СТАТУС: [0] GLOBAL_ERROR [1] ADC_ERROR [2] FPGA_ERROR
                  [3] BMP280_ERROR (неисправность датчика давления, P_A = 0)
   Байт 27      - РЕЗЕРВ (всегда 0)

6. ПОЛЕ D[0..27] - BC -> PSPM (ПРИЁМ)
   Байты 1..2   - ASEL_A      код ЦАП вертикали (перем.)
   Байты 3..4   - ASEL_D      код ЦАП вертикали (пост.)
   Байты 5..6   - ASAZ_A      код ЦАП азимута (перем.)
   Байты 7..8   - ASAZ_D      код ЦАП азимута (пост.)
   Байты 9..10  - SCALE_ASEL  масштаб ДУВН
   Байты 11..12 - SCALE_GPS   масштаб ДПТ
   Байты 13..14 - ADJ_0_ALPHA регулировка 0 вертикали
   Байты 15..16 - SCALE_ASAZ  масштаб ДУГН
   Байты 17..18 - SCALE_HPS   масштаб ДПЛ
   Байты 19..20 - ADJ_0_BETA  регулировка 0 азимута
   Байты 21..28 - РЕЗЕРВ (всегда 0)

7. КНОПКИ УПРАВЛЕНИЯ
   Send Packet    - одиночная отправка
   Start Stream   - циклическая отправка (с интервалом Period)
   Reset to Zero  - сброс всех датчиков в 0 (давление - в 750)
   TX Start / RX Start - возможность переопределить стартовые байты
   Send on Change - отправка пакета по изменению любого параметра.
   Reset Counters - сброс счётчиков
   Clear Log      - очистка лога

8. ГЕНЕРАТОР СИГНАЛОВ
   Накладывает форму (синус, меандр, треугольник, шум) на любое одно поле
   датчика во время потока. Значение ограничивается диапазоном поля.

9. ЛОГИРОВАНИЕ И НАСТРОЙКИ
    Log View         - отображение лога в окне
    Save Log to File - запись лога в файл
    Freeze View      - заморозка отрисовки лога в окне (запись в файл продолжается)
    Font             - настройка шрифта (сохраняется в JSON)
    Check RX CRC16   - если снята, при приёме проверяется только XOR

10. CRC16-CCITT
    Полином: 0x1021, init: 0xFFFF

11. XOR_ALL
    xor_all = (Старт) xor D[0] xor ... xor D[27] xor CRC_L xor CRC_H
================================================================================
"""

SENSOR_FIELDS = ["err_el", "err_el_10", "err_az", "err_az_10", "w_el", "w_az",
                 "gun_pos", "roll", "pitch", "v_tank", "v_wind", "cos_fi", "p_a"]

SENSOR_LIMITS = {
    "err_el":    (-400.0, 400.0), "err_el_10": (-40.0, 40.0),
    "err_az":    (-400.0, 400.0), "err_az_10": (-40.0, 40.0),
    "w_el":      (-5.0, 5.0),     "w_az":      (-5.0, 5.0),
    "gun_pos":   (-15.0, 15.0),   "roll":      (-180.0, 180.0),
    "pitch":     (-180.0, 180.0), "v_tank":    (-20.0, 20.0),
    "v_wind":    (-25.0, 25.0),   "cos_fi":    (-1.0, 1.0),
    "p_a":       (0.0, 1500.0),
}

SENSOR_SCALE = {
    "err_el": 32768.0 / 400.0,  "err_el_10": 32768.0 / 40.0,
    "err_az": 32768.0 / 400.0,  "err_az_10": 32768.0 / 40.0,
    "w_el": 32768.0 / 5.0,      "w_az": 32768.0 / 5.0,
    "gun_pos": 65536.0 / 30.0,  "roll": 65536.0 / 360.0,
    "pitch": 65536.0 / 360.0,   "v_tank": 65536.0 / 40.0,
    "v_wind": 65536.0 / 50.0,   "cos_fi": 32767.0 / 1.0,
    "p_a": 65536.0 / 1500.0,
}

SENSOR_LABELS = {
    "err_el": "ERR_EL (arcmin):",     "err_el_10": "ERR_EL_10 (arcmin):",
    "err_az": "ERR_AZ (arcmin):",     "err_az_10": "ERR_AZ_10 (arcmin):",
    "w_el": "W_EL (deg/s):",          "w_az": "W_AZ (deg/s):",
    "gun_pos": "GUN_POS (deg):",      "roll": "ROLL (deg):",
    "pitch": "PITCH (deg):",          "v_tank": "V_TANK (m/s):",
    "v_wind": "V_WIND (m/s):",        "cos_fi": "COS_FI:",
    "p_a": "P_A (mmHg):",
}

RX_LABELS = [
    ("asel_a", "ASEL_A [1..2]:"),       ("asel_d", "ASEL_D [3..4]:"),
    ("asaz_a", "ASAZ_A [5..6]:"),       ("asaz_d", "ASAZ_D [7..8]:"),
    ("scale_asel", "SCALE_ASEL [9..10]:"), ("scale_gps", "SCALE_GPS [11..12]:"),
    ("adj_0_alpha", "ADJ_0_ALPHA [13..14]:"), ("scale_asaz", "SCALE_ASAZ [15..16]:"),
    ("scale_hps", "SCALE_HPS [17..18]:"),   ("adj_0_beta", "ADJ_0_BETA [19..20]:"),
]

RX_BYTE_OFFSET = {
    "asel_a": 0, "asel_d": 2, "asaz_a": 4, "asaz_d": 6, "scale_asel": 8,
    "scale_gps": 10, "adj_0_alpha": 12, "scale_asaz": 14, "scale_hps": 16, "adj_0_beta": 18,
}


class PSPM2BCSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Primary Signal Processing Module (PSPM) Simulator v2.2")
        self.root.minsize(1100, 700)

        self.settings_file = os.path.join(APP_DIR, "pspm_2_bc_simulator_settings.json")
        self.log_file = os.path.join(APP_DIR, "pspm_log.txt")

        # UART Variables
        self.serial_conn = None
        self.is_connected = False
        self.rx_thread = None
        self.stream_active = False
        self.stream_job = None

        # Counters
        self.tx_counter = 0
        self.rx_counter = 0
        self.crc_errors = 0
        self.xor_errors = 0

        # UART Parameters
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="921600")
        self.parity_var = tk.StringVar(value="Even")
        self.databits_var = tk.StringVar(value="8")
        self.stopbits_var = tk.StringVar(value="1")
        self.period_var = tk.StringVar(value="100")

        # Start Bytes
        self.start_byte_tx_var = tk.StringVar(value="0xAA")
        self.start_byte_rx_var = tk.StringVar(value="0x55")
        # Plain mirror for the RX thread (Tk vars are not thread safe)
        self._m_rx_start = 0x55
        self.start_byte_rx_var.trace_add('write', lambda *a: setattr(
            self, '_m_rx_start', self.parse_hex(self.start_byte_rx_var.get(), 0x55)))

        # Sensor Variables (TX)
        self.err_el = tk.DoubleVar(value=0.0);   self.err_el_10 = tk.DoubleVar(value=0.0)
        self.err_az = tk.DoubleVar(value=0.0);   self.err_az_10 = tk.DoubleVar(value=0.0)
        self.w_el = tk.DoubleVar(value=0.0);     self.w_az = tk.DoubleVar(value=0.0)
        self.gun_pos = tk.DoubleVar(value=0.0);  self.roll = tk.DoubleVar(value=0.0)
        self.pitch = tk.DoubleVar(value=0.0);    self.v_tank = tk.DoubleVar(value=0.0)
        self.v_wind = tk.DoubleVar(value=0.0);   self.cos_fi = tk.DoubleVar(value=0.0)
        self.p_a = tk.DoubleVar(value=750.0)

        self.global_error = tk.BooleanVar(value=False)
        self.adc_error = tk.BooleanVar(value=False)
        self.fpga_error = tk.BooleanVar(value=False)
        self.bmp280_error = tk.BooleanVar(value=False)

        # View Options
        self.global_hex_mode = tk.BooleanVar(value=False)
        self.rx_hex_mode = tk.BooleanVar(value=False)
        self.log_enabled = tk.BooleanVar(value=True)
        self.log_view_enabled = tk.BooleanVar(value=True)
        self.freeze_view = tk.BooleanVar(value=False)
        self.send_on_change = tk.BooleanVar(value=False)
        self.check_crc_rx_var = tk.BooleanVar(value=True)

        # Font settings
        self.log_font_family = tk.StringVar(value="Consolas")
        self.log_font_size = tk.IntVar(value=10)

        # RX Variables (BC -> PSPM, raw int16 DAC codes)
        self.raw_rx_data = {k: 0 for k in RX_BYTE_OFFSET}
        self.rx_vars = {k: tk.StringVar() for k in RX_BYTE_OFFSET}

        # Generator Variables
        self.gen_enabled = tk.BooleanVar(value=False)
        self.gen_wave_type = tk.StringVar(value="Sine")
        self.gen_target = tk.StringVar(value="err_el")
        self.gen_amplitude = tk.DoubleVar(value=10.0)
        self.gen_frequency = tk.DoubleVar(value=1.0)
        self.gen_offset = tk.DoubleVar(value=0.0)
        self.gen_start_time = time.perf_counter()
        self.last_gui_update = 0.0
        # Phase accumulator: waveform parameters apply live, no enable/disable needed
        self._gen_phase = 0.0
        self._gen_last_ts = time.perf_counter()

        # Thread-safe Snapshot Cache
        self.cached_tx_data = {k: 0.0 for k in SENSOR_FIELDS}
        self.cached_tx_data["p_a"] = 750.0
        self.cached_tx_data.update({
            "global_error": False, "adc_error": False, "fpga_error": False,
            "bmp280_error": False,
            "start_tx": 0xAA, "gen_enabled": False, "gen_wave_type": "Sine",
            "gen_target": "err_el", "gen_amplitude": 10.0, "gen_frequency": 1.0,
            "gen_offset": 0.0,
        })
        self.cached_period = 0.1

        # Buffered file logging: lines accumulate and flush every 500 ms,
        # so per-message disk access never stalls the GUI thread
        self.log_file_buf = []
        self.root.after(500, self.flush_log_file)

        self.setup_gui()
        self.refresh_ports()
        self.load_settings()
        self.update_tx_cache()
        self.refresh_rx_display()
        self.root.after(20, self.generator_tick)

    def parse_hex(self, val_str, default_val):
        s = str(val_str).strip().lower()
        if s.startswith('0x'): s = s[2:]
        if s.endswith('h'): s = s[:-1]

        cyrillic_to_latin = str.maketrans('авсе', 'abce')
        s = s.translate(cyrillic_to_latin)

        if not s: return default_val
        try:
            return int(s, 16) & 0xFF
        except ValueError:
            return default_val

    def reformat_start_bytes(self, event=None):
        tx_val = self.parse_hex(self.start_byte_tx_var.get(), 0xAA)
        self.start_byte_tx_var.set(f"0x{tx_val:02X}")

        rx_val = self.parse_hex(self.start_byte_rx_var.get(), 0x55)
        self.start_byte_rx_var.set(f"0x{rx_val:02X}")
        self.update_tx_cache()
        self.save_settings()

    def show_help(self):
        help_window = tk.Toplevel(self.root)
        help_window.title("HELP / СПРАВКА - PSPM Simulator")
        help_window.geometry("1050x850")
        help_window.transient(self.root)
        help_window.grab_set()

        help_window.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 1050) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 850) // 2
        help_window.geometry(f"+{x}+{y}")

        help_font = tkfont.Font(family=self.log_font_family.get(), size=self.log_font_size.get())
        help_text = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, font=help_font)
        help_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        help_text.insert("1.0", HELP_EN + "\n\n" + HELP_RU)
        help_text.configure(state='disabled')

        ttk.Button(help_window, text="Close", command=help_window.destroy).pack(pady=10)

    def save_settings(self):
        try:
            settings = {
                "port": self.port_var.get(),
                "baudrate": self.baud_var.get(),
                "parity": self.parity_var.get(),
                "databits": self.databits_var.get(),
                "stopbits": self.stopbits_var.get(),
                "period": self.period_var.get(),
                "start_byte_tx": self.start_byte_tx_var.get(),
                "start_byte_rx": self.start_byte_rx_var.get(),
                "global_hex_mode": self.global_hex_mode.get(),
                "rx_hex_mode": self.rx_hex_mode.get(),
                "send_on_change": self.send_on_change.get(),
                "log_enabled": self.log_enabled.get(),
                "log_view_enabled": self.log_view_enabled.get(),
                "freeze_view": self.freeze_view.get(),
                "check_crc_rx": self.check_crc_rx_var.get(),
                "font_family": self.log_font_family.get(),
                "font_size": self.log_font_size.get(),
                "gen_enabled": self.gen_enabled.get(),
                "gen_wave_type": self.gen_wave_type.get(),
                "gen_target": self.gen_target.get(),
                "gen_amplitude": self.get_safe_float(self.gen_amplitude, 10.0),
                "gen_frequency": self.get_safe_float(self.gen_frequency, 1.0),
                "gen_offset": self.get_safe_float(self.gen_offset, 0.0),
                "sensors": {k: round(getattr(self, k).get(), 2) for k in SENSOR_FIELDS},
                "status": {k: getattr(self, k).get() for k in ["global_error", "adc_error", "fpga_error", "bmp280_error"]},
                "window_geometry": self.root.geometry(),
            }
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

                if "port" in settings: self.port_var.set(settings["port"])
                if "baudrate" in settings: self.baud_var.set(settings["baudrate"])
                if "parity" in settings: self.parity_var.set(settings["parity"])
                if "databits" in settings: self.databits_var.set(settings["databits"])
                if "stopbits" in settings: self.stopbits_var.set(settings["stopbits"])
                if "period" in settings: self.period_var.set(settings["period"])
                if "start_byte_tx" in settings: self.start_byte_tx_var.set(settings["start_byte_tx"])
                if "start_byte_rx" in settings: self.start_byte_rx_var.set(settings["start_byte_rx"])
                if "global_hex_mode" in settings: self.global_hex_mode.set(settings["global_hex_mode"])
                if "rx_hex_mode" in settings: self.rx_hex_mode.set(settings["rx_hex_mode"])
                if "send_on_change" in settings: self.send_on_change.set(settings["send_on_change"])
                if "log_enabled" in settings: self.log_enabled.set(settings["log_enabled"])
                if "log_view_enabled" in settings: self.log_view_enabled.set(settings["log_view_enabled"])
                if "freeze_view" in settings: self.freeze_view.set(settings["freeze_view"])
                if "check_crc_rx" in settings: self.check_crc_rx_var.set(settings["check_crc_rx"])

                if "font_family" in settings: self.log_font_family.set(settings["font_family"])
                if "font_size" in settings: self.log_font_size.set(settings["font_size"])

                new_f = (self.log_font_family.get(), self.log_font_size.get())
                self.apply_new_font(new_f)

                if "gen_enabled" in settings: self.gen_enabled.set(settings["gen_enabled"])
                if "gen_wave_type" in settings: self.gen_wave_type.set(settings["gen_wave_type"])
                if "gen_target" in settings: self.gen_target.set(settings["gen_target"])
                if "gen_amplitude" in settings: self.gen_amplitude.set(settings["gen_amplitude"])
                if "gen_frequency" in settings: self.gen_frequency.set(settings["gen_frequency"])
                if "gen_offset" in settings: self.gen_offset.set(settings["gen_offset"])

                sens = settings.get("sensors", {})
                for k in SENSOR_FIELDS:
                    if k in sens: getattr(self, k).set(round(sens[k], 2))
                st = settings.get("status", {})
                for k in ["global_error", "adc_error", "fpga_error", "bmp280_error"]:
                    if k in st: getattr(self, k).set(st[k])

                if "window_geometry" in settings:
                    try: self.root.geometry(settings["window_geometry"])
                    except: pass
            except Exception:
                pass

    def open_font_dialog(self):
        font_win = tk.Toplevel(self.root)
        font_win.title("Font Settings")
        font_win.geometry("450x400")
        font_win.resizable(True, True)
        font_win.transient(self.root)
        font_win.grab_set()

        font_win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 450) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 400) // 2
        font_win.geometry(f"+{x}+{y}")

        main_frame = ttk.Frame(font_win, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_lbl = ttk.Label(main_frame, text="Font Settings", font=('TkDefaultFont', 11, 'bold'))
        title_lbl.pack(side=tk.TOP, pady=(0, 10))

        family_var = tk.StringVar(value=self.log_font_family.get())
        size_var = tk.IntVar(value=self.log_font_size.get())

        font_frame = ttk.Frame(main_frame)
        font_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        ttk.Label(font_frame, text="Font:").pack(side=tk.LEFT, padx=(0, 10))
        available_fonts = list(tkfont.families())
        available_fonts.sort()
        font_combo = ttk.Combobox(font_frame, textvariable=family_var, values=available_fonts, state="readonly", width=30)
        font_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        size_frame = ttk.Frame(main_frame)
        size_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        ttk.Label(size_frame, text="Size:").pack(side=tk.LEFT, padx=(0, 10))
        size_spin = ttk.Spinbox(size_frame, textvariable=size_var, from_=8, to=72, width=5)
        size_spin.pack(side=tk.LEFT)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        preview_frame = ttk.LabelFrame(main_frame, text="Preview", padding="10")
        preview_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(10, 0))

        preview_label = tk.Label(preview_frame, text="AaBbCcYyZz\n0123456789", bg="white", relief="sunken", height=2)
        preview_label.pack(fill=tk.BOTH, expand=True)

        def update_preview(*args):
            try:
                new_f = tkfont.Font(family=family_var.get(), size=size_var.get())
                preview_label.configure(font=new_f)
            except: pass

        family_var.trace_add('write', update_preview)
        size_var.trace_add('write', update_preview)
        update_preview()

        def apply_font():
            new_f = (family_var.get(), size_var.get())
            self.apply_new_font(new_f)
            font_win.destroy()

        ttk.Button(btn_frame, text="Apply (OK)", command=apply_font).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=font_win.destroy).pack(side=tk.RIGHT, padx=5)

    def update_widget_tree_font(self, parent, new_font):
        """Recursively update font option on all eligible widgets in the hierarchy."""
        try:
            parent.configure(font=new_font)
        except tk.TclError:
            pass

        for child in parent.winfo_children():
            self.update_widget_tree_font(child, new_font)

    def apply_new_font(self, new_font):
        try:
            self.log_font_family.set(new_font[0])
            self.log_font_size.set(new_font[1])

            self.root.option_add('*Font', new_font)

            style = ttk.Style()
            style.configure('.', font=new_font)
            style.configure('TLabel', font=new_font)
            style.configure('TButton', font=new_font)
            style.configure('TEntry', font=new_font)
            style.configure('TCombobox', font=new_font)
            style.configure('TCheckbutton', font=new_font)
            style.configure('TRadiobutton', font=new_font)
            style.configure('TLabelframe.Label', font=new_font)

            self.update_widget_tree_font(self.root, new_font)

            self.save_settings()
        except Exception as e:
            messagebox.showerror("Font Error", f"Error applying font: {str(e)}")

    def get_safe_float(self, var, fallback=0.0):
        try:
            return float(var.get())
        except (tk.TclError, ValueError):
            return fallback

    def update_tx_cache(self):
        for k in SENSOR_FIELDS:
            self.cached_tx_data[k] = self.get_safe_float(getattr(self, k))
        for k in ["global_error", "adc_error", "fpga_error", "bmp280_error"]:
            self.cached_tx_data[k] = getattr(self, k).get()
        self.cached_tx_data["start_tx"] = self.parse_hex(self.start_byte_tx_var.get(), 0xAA)
        self.cached_tx_data["gen_enabled"] = self.gen_enabled.get()
        self.cached_tx_data["gen_wave_type"] = self.gen_wave_type.get()
        self.cached_tx_data["gen_target"] = self.gen_target.get()
        self.cached_tx_data["gen_amplitude"] = self.get_safe_float(self.gen_amplitude, 10.0)
        self.cached_tx_data["gen_frequency"] = self.get_safe_float(self.gen_frequency, 1.0)
        self.cached_tx_data["gen_offset"] = self.get_safe_float(self.gen_offset, 0.0)
        try:
            self.cached_period = max(0.01, min(1.0, float(self.period_var.get()) / 1000.0))
        except ValueError:
            self.cached_period = 0.1

    def on_gui_value_change(self, *args):
        self.update_tx_cache()
        # Direct send only if send_on_change is enabled and streaming is inactive
        if self.send_on_change.get() and not self.stream_active and self.is_connected:
            self.send_packet()

    def toggle_rx_hex(self):
        self.refresh_rx_display()
        self.save_settings()

    def refresh_rx_display(self):
        for k in RX_BYTE_OFFSET:
            val = self.raw_rx_data[k]
            if self.rx_hex_mode.get():
                self.rx_vars[k].set(f"0x{val & 0xFFFF:04X} [{RX_BYTE_OFFSET[k]}]")
            else:
                self.rx_vars[k].set(f"{val} [{RX_BYTE_OFFSET[k]}]")

    def create_sensor_slider(self, parent, key, var, from_, to, res):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        ttk.Label(frame, text=SENSOR_LABELS[key], width=20).pack(side=tk.LEFT)
        scale_widget = tk.Scale(frame, from_=from_, to=to, orient=tk.HORIZONTAL, resolution=res,
                                variable=var, length=160, width=10, sliderlength=10,
                                command=lambda v: self.on_gui_value_change())
        scale_widget.pack(side=tk.LEFT, padx=5)
        display_var = tk.StringVar()
        scale = SENSOR_SCALE[key]
        signed = (key != "p_a")

        def update_entry(*args):
            try:
                val = var.get()
                if self.global_hex_mode.get():
                    raw = int(round(val * scale))
                    if signed:
                        raw = max(-32768, min(32767, raw))
                        if raw < 0: raw = (1 << 16) + raw
                    else:
                        raw = max(0, min(65535, raw))
                    display_var.set(f"0x{raw:04X}")
                else:
                    display_var.set(f"{val:.2f}")
            except Exception:
                pass

        def on_entry_change(event=None):
            try:
                text_val = display_var.get().strip()
                if self.global_hex_mode.get():
                    raw = int(text_val, 16)
                    if signed and (raw & 0x8000): raw -= 65536
                    phys_val = raw / scale
                else:
                    phys_val = float(text_val)
                var.set(round(max(from_, min(to, phys_val)), 2))
                self.on_gui_value_change()
            except ValueError:
                pass
            finally:
                update_entry()

        entry = ttk.Entry(frame, textvariable=display_var, width=9)
        entry.pack(side=tk.LEFT, padx=5)
        entry.bind('<Return>', on_entry_change)
        entry.bind('<FocusOut>', on_entry_change)
        var.trace_add('write', update_entry)
        self.global_hex_mode.trace_add('write', update_entry)
        update_entry()

    def setup_gui(self):
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ========== LEFT PANEL ==========
        left_frame = ttk.LabelFrame(main_paned, text="UART Settings", padding="10")
        main_paned.add(left_frame, weight=0)

        ttk.Label(left_frame, text="COM Port:").pack(anchor=tk.W, pady=(0, 2))
        self.port_combo = ttk.Combobox(left_frame, textvariable=self.port_var, width=12)
        self.port_combo.pack(anchor=tk.W, pady=(0, 5))

        ttk.Button(left_frame, text="↻ Refresh", command=self.refresh_ports).pack(anchor=tk.W, pady=(0, 10))

        ttk.Label(left_frame, text="Baudrate:").pack(anchor=tk.W, pady=(0, 2))
        ttk.Combobox(left_frame, textvariable=self.baud_var, width=12,
                     values=["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]).pack(anchor=tk.W, pady=(0, 10))

        ttk.Label(left_frame, text="Parity:").pack(anchor=tk.W, pady=(0, 2))
        ttk.Combobox(left_frame, textvariable=self.parity_var, width=12,
                     values=["None", "Even", "Odd"]).pack(anchor=tk.W, pady=(0, 10))

        ttk.Label(left_frame, text="Data bits:").pack(anchor=tk.W, pady=(0, 2))
        ttk.Combobox(left_frame, textvariable=self.databits_var, width=12,
                     values=["5", "6", "7", "8"]).pack(anchor=tk.W, pady=(0, 10))

        ttk.Label(left_frame, text="Stop bits:").pack(anchor=tk.W, pady=(0, 2))
        ttk.Combobox(left_frame, textvariable=self.stopbits_var, width=12,
                     values=["1", "1.5", "2"]).pack(anchor=tk.W, pady=(0, 10))

        ttk.Label(left_frame, text="Period (ms):").pack(anchor=tk.W, pady=(0, 2))
        ttk.Entry(left_frame, textvariable=self.period_var, width=12).pack(anchor=tk.W, pady=(0, 10))

        self.connect_btn = ttk.Button(left_frame, text="Connect", command=self.toggle_connection)
        self.connect_btn.pack(anchor=tk.W, pady=(5, 5))

        status_frame = ttk.Frame(left_frame)
        status_frame.pack(anchor=tk.W, pady=(5, 0))
        self.conn_indicator = tk.Canvas(status_frame, width=20, height=7, highlightthickness=0)
        self.conn_indicator.create_rectangle(0, 0, 20, 7, fill='red', outline='', tags='rect')
        self.conn_indicator.pack(side=tk.LEFT, padx=(0, 5))
        self.conn_label = ttk.Label(status_frame, text="Disconnected")
        self.conn_label.pack(side=tk.LEFT)

        tx_frame = ttk.Frame(left_frame)
        tx_frame.pack(anchor=tk.W, pady=(10, 2))
        self.tx_indicator = tk.Canvas(tx_frame, width=20, height=7, highlightthickness=0)
        self.tx_indicator.create_rectangle(0, 0, 20, 7, fill='gray', outline='', tags='rect')
        self.tx_indicator.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(tx_frame, text="TX").pack(side=tk.LEFT)

        rx_frame = ttk.Frame(left_frame)
        rx_frame.pack(anchor=tk.W, pady=(2, 0))
        self.rx_indicator = tk.Canvas(rx_frame, width=20, height=7, highlightthickness=0)
        self.rx_indicator.create_rectangle(0, 0, 20, 7, fill='gray', outline='', tags='rect')
        self.rx_indicator.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(rx_frame, text="RX").pack(side=tk.LEFT)

        ttk.Button(left_frame, text="HELP", command=self.show_help).pack(anchor=tk.W, pady=(10, 0))

        # ========== CENTER PANEL ==========
        center_frame = ttk.LabelFrame(main_paned, text="Primary Signal Processing Module (PSPM) Control", padding="10")
        main_paned.add(center_frame, weight=1)

        sensors_frame = ttk.LabelFrame(center_frame, text="Sensor Data D[0..27]", padding="5")
        sensors_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        ttk.Checkbutton(sensors_frame, text="Display all values in packet format (HEX)",
                        variable=self.global_hex_mode).pack(anchor=tk.W, padx=5, pady=(0, 2))

        columns_frame = ttk.Frame(sensors_frame)
        columns_frame.pack(fill=tk.BOTH, expand=True)
        col1 = ttk.Frame(columns_frame)
        col1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        col2 = ttk.Frame(columns_frame)
        col2.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=2)

        col1_keys = [("err_el", -400, 400), ("err_az", -400, 400), ("w_el", -5, 5),
                     ("gun_pos", -15, 15), ("roll", -180, 180), ("v_tank", -20, 20), ("p_a", 0, 1500)]
        col2_keys = [("err_el_10", -40, 40), ("err_az_10", -40, 40), ("w_az", -5, 5),
                     ("pitch", -180, 180), ("v_wind", -25, 25), ("cos_fi", -1, 1)]
        for key, lo, hi in col1_keys:
            self.create_sensor_slider(col1, key, getattr(self, key), lo, hi, 0.01)
        for key, lo, hi in col2_keys:
            self.create_sensor_slider(col2, key, getattr(self, key), lo, hi, 0.01)

        ps_flags_frame = ttk.LabelFrame(center_frame, text="PSPM Status and Errors (Byte 26)", padding="5")
        ps_flags_frame.pack(fill=tk.X, pady=(0, 5))
        sc_frame = ttk.Frame(ps_flags_frame)
        sc_frame.pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(sc_frame, text="GLOBAL_ERROR", variable=self.global_error,
                        command=self.on_gui_value_change).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(sc_frame, text="ADC_ERROR", variable=self.adc_error,
                        command=self.on_gui_value_change).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(sc_frame, text="FPGA_ERROR", variable=self.fpga_error,
                        command=self.on_gui_value_change).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(sc_frame, text="BMP280_ERROR (P_A=0)", variable=self.bmp280_error,
                        command=self.on_gui_value_change).pack(side=tk.LEFT, padx=5)

        send_frame = ttk.Frame(center_frame)
        send_frame.pack(fill=tk.X, pady=10)

        self.send_btn = ttk.Button(send_frame, text="Send Packet", command=self.send_packet, width=12)
        self.send_btn.pack(side=tk.LEFT, padx=5)

        self.stream_btn = ttk.Button(send_frame, text="Start Stream", command=self.toggle_stream, width=12)
        self.stream_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(send_frame, text="Reset to Zero", command=self.reset_to_zero, width=12).pack(side=tk.LEFT, padx=5)

        tx_entry = ttk.Entry(send_frame, textvariable=self.start_byte_tx_var, width=6)
        ttk.Label(send_frame, text="TX Start:").pack(side=tk.LEFT, padx=(20, 2))
        tx_entry.pack(side=tk.LEFT)
        tx_entry.bind('<FocusOut>', self.reformat_start_bytes)
        tx_entry.bind('<Return>', self.reformat_start_bytes)

        rx_entry = ttk.Entry(send_frame, textvariable=self.start_byte_rx_var, width=6)
        ttk.Label(send_frame, text="RX Start:").pack(side=tk.LEFT, padx=(15, 2))
        rx_entry.pack(side=tk.LEFT)
        rx_entry.bind('<FocusOut>', self.reformat_start_bytes)
        rx_entry.bind('<Return>', self.reformat_start_bytes)

        self.send_on_change_check = ttk.Checkbutton(send_frame, text="Send on Change",
                                                    variable=self.send_on_change, command=self.save_settings)
        self.send_on_change_check.pack(side=tk.LEFT, padx=(15, 5))

        # ========== RIGHT PANEL ==========
        right_frame = ttk.LabelFrame(main_paned, text="Diagnostics & BC Commands", padding="10")
        main_paned.add(right_frame, weight=0)

        status_frame2 = ttk.LabelFrame(right_frame, text="Status", padding="5")
        status_frame2.pack(fill=tk.X, pady=(0, 5))

        self.status_label2 = ttk.Label(status_frame2, text="Disconnected", foreground="red")
        self.status_label2.pack(anchor=tk.W)

        counters_frame = ttk.LabelFrame(right_frame, text="Counters", padding="5")
        counters_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Checkbutton(counters_frame, text="Check RX CRC16", variable=self.check_crc_rx_var,
                        command=self.save_settings).pack(anchor=tk.W, pady=(0, 5))

        self.tx_label = ttk.Label(counters_frame, text=f"TX (PSPM->BC): {self.tx_counter}")
        self.tx_label.pack(anchor=tk.W)
        self.rx_label = ttk.Label(counters_frame, text=f"RX (BC->PSPM): {self.rx_counter}")
        self.rx_label.pack(anchor=tk.W)
        self.crc_label = ttk.Label(counters_frame, text=f"CRC Errors: {self.crc_errors}")
        self.crc_label.pack(anchor=tk.W)
        self.xor_label = ttk.Label(counters_frame, text=f"XOR Errors: {self.xor_errors}")
        self.xor_label.pack(anchor=tk.W)

        ttk.Button(counters_frame, text="Reset Counters", command=self.reset_counters).pack(pady=5)

        bc_frame = ttk.LabelFrame(right_frame, text="Data from BC (BC -> PSPM)", padding="5")
        bc_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Checkbutton(bc_frame, text="Display RX in HEX", variable=self.rx_hex_mode,
                        command=self.toggle_rx_hex).pack(anchor=tk.W, pady=(0, 2))

        rx_cols = ttk.Frame(bc_frame)
        rx_cols.pack(fill=tk.X)
        rx_c1 = ttk.Frame(rx_cols)
        rx_c1.pack(side=tk.LEFT, expand=True, fill=tk.X)
        rx_c2 = ttk.Frame(rx_cols)
        rx_c2.pack(side=tk.LEFT, expand=True, fill=tk.X)

        half = (len(RX_LABELS) + 1) // 2
        for key, text in RX_LABELS[:half]:
            row = ttk.Frame(rx_c1)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=text, width=22).pack(side=tk.LEFT)
            ttk.Label(row, textvariable=self.rx_vars[key]).pack(side=tk.LEFT)
        for key, text in RX_LABELS[half:]:
            row = ttk.Frame(rx_c2)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=text, width=22).pack(side=tk.LEFT)
            ttk.Label(row, textvariable=self.rx_vars[key]).pack(side=tk.LEFT)

        generator_frame = ttk.LabelFrame(right_frame, text="Signal Generator", padding="5")
        generator_frame.pack(fill=tk.X)

        ttk.Checkbutton(generator_frame, text="Enable Generator", variable=self.gen_enabled,
                        command=self.toggle_generator).pack(anchor=tk.W, pady=2)

        def make_gen_row(parent, label, var, values=None):
            f = ttk.Frame(parent)
            f.pack(fill=tk.X, pady=2)
            ttk.Label(f, text=label).pack(side=tk.LEFT)
            if values:
                ttk.Combobox(f, textvariable=var, values=values, width=12, state="readonly").pack(side=tk.RIGHT)
            else:
                ttk.Entry(f, textvariable=var, width=8).pack(side=tk.RIGHT)

        make_gen_row(generator_frame, "Target Field:", self.gen_target, SENSOR_FIELDS)
        make_gen_row(generator_frame, "Waveform:", self.gen_wave_type, ["Sine", "Square", "Triangle", "Noise"])
        make_gen_row(generator_frame, "Amplitude:", self.gen_amplitude)
        make_gen_row(generator_frame, "Frequency (Hz):", self.gen_frequency)
        make_gen_row(generator_frame, "Offset:", self.gen_offset)

        # ========== BOTTOM PANEL - LOG ==========
        log_display_frame = ttk.LabelFrame(self.root, text="Event Log", padding="5")
        log_display_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # Pack button frame first at the BOTTOM
        log_btn_frame = ttk.Frame(log_display_frame)
        log_btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        # Pack greedy scrolledtext second at the TOP (leaves room for buttons during window shrink)
        self.log_text = scrolledtext.ScrolledText(log_display_frame, height=12, wrap=tk.WORD)
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.log_text.tag_configure('tx', background='#90EE90')
        self.log_text.tag_configure('rx', background='#FFF44F')
        self.log_text.tag_configure('err', background='#FF9999')

        ttk.Checkbutton(log_btn_frame, text="Log View", variable=self.log_view_enabled).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(log_btn_frame, text="Save Log to File", variable=self.log_enabled,
                        command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(log_btn_frame, text="Freeze View", variable=self.freeze_view,
                        command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(log_btn_frame, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(log_btn_frame, text="Font", command=self.open_font_dialog).pack(side=tk.RIGHT, padx=5)

    def toggle_generator(self):
        if self.gen_enabled.get():
            self.gen_start_time = time.perf_counter()
            self._gen_phase = 0.0
            self._gen_last_ts = time.perf_counter()
        self.update_tx_cache()
        self.save_settings()

    def compute_waveform(self, cache, t, phase=None):
        wave = cache["gen_wave_type"]
        amp, freq, offset = cache["gen_amplitude"], cache["gen_frequency"], cache["gen_offset"]
        if freq <= 0.0: freq = 0.1
        # Phase-accumulation mode: live parameter changes take effect
        # immediately without a phase jump and with correct new frequency.
        if phase is not None:
            self._gen_phase = (phase + freq * (t - self._gen_last_ts)) % 1.0
            angle = 2.0 * math.pi * self._gen_phase
        else:
            angle = 2.0 * math.pi * freq * t

        if wave == "Sine":
            return offset + amp * math.sin(angle)
        if wave == "Square":
            return offset + amp * (1.0 if math.sin(angle) >= 0.0 else -1.0)
        if wave == "Triangle":
            phase_v = (angle / (2.0 * math.pi)) % 1.0
            if phase_v < 0.5:
                return offset - amp + 4.0 * amp * phase_v
            return offset + 3.0 * amp - 4.0 * amp * phase_v
        if wave == "Noise":
            return offset + amp * random.uniform(-1.0, 1.0)
        return offset

    def _gen_waveform_live(self, cache, t):
        # Recompute from freshly read GUI vars, then persist to the TX cache
        # so every packet builder (stream, direct send, burst) sees the change.
        cache = dict(cache)
        cache["gen_amplitude"] = self.get_safe_float(self.gen_amplitude, 10.0)
        cache["gen_frequency"] = self.get_safe_float(self.gen_frequency, 1.0)
        cache["gen_offset"] = self.get_safe_float(self.gen_offset, 0.0)
        cache["gen_wave_type"] = self.gen_wave_type.get()
        val = self.compute_waveform(cache, t, phase=self._gen_phase)
        self._gen_last_ts = t
        cache["gen_target"] = self.gen_target.get()
        self.cached_tx_data.update({k: cache[k] for k in
                                    ("gen_amplitude", "gen_frequency", "gen_offset",
                                     "gen_wave_type", "gen_target")})
        return val

    def generator_tick(self):
        """GUI-thread generator loop (active only when NOT streaming)."""
        try:
            if self.gen_enabled.get() and not self.stream_active:
                now = time.perf_counter()
                tgt = self.gen_target.get()
                if tgt in SENSOR_LIMITS:
                    var = getattr(self, tgt)
                    min_lim, max_lim = SENSOR_LIMITS[tgt]
                    val = self._gen_waveform_live(self.cached_tx_data, now)
                    val = max(min_lim, min(max_lim, val))
                    var.set(round(val, 2))
                    self.update_tx_cache()
        except Exception:
            pass
        finally:
            self.root.after(20, self.generator_tick)

    def update_gui_variable(self, tgt, val):
        try:
            if tgt in SENSOR_LIMITS:
                getattr(self, tgt).set(round(val, 2))
        except Exception:
            pass

    def blink_tx_once(self):
        self.tx_indicator.itemconfig('rect', fill='#00FF00')
        self.root.after(150, lambda: self.tx_indicator.itemconfig('rect', fill='gray'))

    def blink_rx_once(self):
        self.rx_indicator.itemconfig('rect', fill='#FFFF00')
        self.root.after(150, lambda: self.rx_indicator.itemconfig('rect', fill='gray'))

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        self.log_file_buf = []

        if self.log_enabled.get():
            try:
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.write("")
            except Exception:
                pass

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        current_ports = [p.device for p in ports]
        self.port_combo['values'] = current_ports
        if current_ports and not self.port_var.get():
            self.port_var.set(current_ports[0])
        elif self.port_var.get() not in current_ports and current_ports:
            self.port_var.set(current_ports[0])

    def toggle_connection(self):
        if not self.is_connected:
            self.connect()
        else:
            self.disconnect()

    def connect(self):
        try:
            port = self.port_var.get()
            if not port:
                messagebox.showwarning("No Port", "Select COM port first")
                return
            baudrate = int(self.baud_var.get())
            parity_map = {"None": serial.PARITY_NONE, "Even": serial.PARITY_EVEN, "Odd": serial.PARITY_ODD}
            parity = parity_map.get(self.parity_var.get(), serial.PARITY_EVEN)
            stopbits_map = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE, "2": serial.STOPBITS_TWO}
            stopbits = stopbits_map.get(self.stopbits_var.get(), serial.STOPBITS_ONE)

            self.serial_conn = serial.Serial(
                port=port, baudrate=baudrate, parity=parity,
                bytesize=int(self.databits_var.get()), stopbits=stopbits, timeout=1
            )
            self.is_connected = True
            self.connect_btn.configure(text="Disconnect")
            self.conn_indicator.itemconfig('rect', fill='#00FF00')
            self.conn_label.configure(text="Connected")
            self.status_label2.configure(text="Connected", foreground="green")
            self.port_combo.configure(state='disabled')

            self.rx_thread = threading.Thread(target=self.receive_data, daemon=True)
            self.rx_thread.start()
            parity_letter = {"None": "N", "Even": "E", "Odd": "O"}.get(self.parity_var.get(), "?")
            self.log(f"Connected to PSPM on {port} @ {baudrate} {self.databits_var.get()}{parity_letter}{self.stopbits_var.get()}", 'rx')
            self.save_settings()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.disconnect()

    def disconnect(self):
        self.stream_active = False
        if self.stream_job is not None:
            self.root.after_cancel(self.stream_job)
            self.stream_job = None
        if self.serial_conn and self.is_connected:
            try:
                self.serial_conn.close()
            except Exception:
                pass
        self.serial_conn = None
        self.is_connected = False
        self.connect_btn.configure(text="Connect")
        self.conn_indicator.itemconfig('rect', fill='red')
        self.conn_label.configure(text="Disconnected")
        self.status_label2.configure(text="Disconnected", foreground="red")
        self.port_combo.configure(state='normal')
        self.send_btn.configure(state='normal')
        self.stream_btn.configure(text="Start Stream")
        self.tx_indicator.itemconfig('rect', fill='gray')
        self.rx_indicator.itemconfig('rect', fill='gray')
        self.log("Disconnected", 'rx')
        self.save_settings()

    def receive_data(self):
        buffer = bytearray()
        last_rx_time = time.perf_counter()
        idle_timeout = 0.02

        while self.is_connected:
            try:
                if self.serial_conn and self.serial_conn.is_open:
                    waiting = self.serial_conn.in_waiting
                    if waiting > 0:
                        buffer.extend(self.serial_conn.read(waiting))
                        last_rx_time = time.perf_counter()

                        start_rx = self._m_rx_start

                        while len(buffer) >= 32:
                            if buffer[0] == start_rx:
                                packet = bytes(buffer[:32])
                                buffer = buffer[32:]
                                self.root.after(0, self.process_rx_packet, packet)
                            else:
                                buffer.pop(0)
                    else:
                        if len(buffer) > 0 and (time.perf_counter() - last_rx_time) > idle_timeout:
                            buffer.clear()

                time.sleep(0.002)
            except Exception:
                break

    def process_rx_packet(self, data):
        start_rx = self.parse_hex(self.start_byte_rx_var.get(), 0x55)

        if len(data) != 32 or data[0] != start_rx:
            return

        # Validation order mirrors PSPM firmware RX state machine exactly:
        # CRC16 first (bytes 0..28), then XOR_ALL (bytes 0..30).
        # 1. CRC16-CCITT validation
        if self.check_crc_rx_var.get():
            calc_crc = self.calculate_crc16_ccitt(data[:29])
            rx_crc = data[29] | (data[30] << 8)

            if calc_crc != rx_crc:
                self.crc_errors += 1
                self.crc_label.configure(text=f"CRC Errors: {self.crc_errors}")
                self.log(f"RX CRC ERROR: {data.hex(' ')}", 'err')
                return

        # 2. XOR_ALL validation
        calc_xor = 0
        for i in range(31):
            calc_xor ^= data[i]
        rx_xor = data[31]

        if calc_xor != rx_xor:
            self.xor_errors += 1
            self.xor_label.configure(text=f"XOR Errors: {self.xor_errors}")
            self.log(f"RX XOR ERROR: {data.hex(' ')}", 'err')
            return

        self.blink_rx_once()
        self.rx_counter += 1
        self.rx_label.configure(text=f"RX (BC->PSPM): {self.rx_counter}")

        try:
            unpacked = struct.unpack('<hhhhhhhhhh', data[1:21])
            for i, key in enumerate(["asel_a", "asel_d", "asaz_a", "asaz_d", "scale_asel",
                                     "scale_gps", "adj_0_alpha", "scale_asaz", "scale_hps", "adj_0_beta"]):
                self.raw_rx_data[key] = unpacked[i]
            self.refresh_rx_display()
        except Exception:
            pass
        self.log(f"RX BC->PSPM: {data.hex(' ')}", 'rx')

    def calculate_crc16_ccitt(self, data):
        crc = 0xFFFF
        for byte in data:
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return crc

    def pack_int16(self, val, scale, signed=True):
        raw = int(round(val * scale))
        if signed:
            raw = max(-32768, min(32767, raw))
            return struct.pack('<h', raw)
        raw = max(0, min(65535, raw))
        return struct.pack('<H', raw)

    def build_packet(self):
        c = self.cached_tx_data
        if c["gen_enabled"]:
            # Live target read: build_packet always runs in the GUI thread
            # (stream is Tk-after driven), no cross-thread Tcl access here.
            tgt = self.gen_target.get()
            if tgt in SENSOR_LIMITS:
                val = self._gen_waveform_live(c, time.perf_counter())
                min_lim, max_lim = SENSOR_LIMITS[tgt]
                val = max(min_lim, min(max_lim, val))
                c[tgt] = val
                now_perf = time.perf_counter()
                if now_perf - self.last_gui_update >= 0.033:
                    self.last_gui_update = now_perf
                    self.root.after(0, self.update_gui_variable, tgt, val)

        data = bytearray()
        for key in SENSOR_FIELDS:
            # Mirror host.c: pressure fault forces p_a = 0 (paired sentinel)
            if key == "p_a" and c["bmp280_error"]:
                data.extend(self.pack_int16(0.0, SENSOR_SCALE[key], signed=False))
            else:
                data.extend(self.pack_int16(c[key], SENSOR_SCALE[key], signed=(key != "p_a")))

        status = 0
        if c["global_error"]: status |= (1 << 0)
        if c["adc_error"]:    status |= (1 << 1)
        if c["fpga_error"]:   status |= (1 << 2)
        if c["bmp280_error"]: status |= (1 << 3)
        data.append(status)
        data.append(0)

        packet = bytearray()
        packet.append(c["start_tx"])
        packet.extend(data)

        crc = self.calculate_crc16_ccitt(packet)
        packet.append(crc & 0xFF)
        packet.append((crc >> 8) & 0xFF)

        xor_all = 0
        for b in packet:
            xor_all ^= b
        packet.append(xor_all)
        return packet

    def get_tx_log_string(self, packet):
        c = self.cached_tx_data
        if self.global_hex_mode.get():
            return packet.hex(' ')
        return (f"[EL:{c['err_el']:.2f}, EL10:{c['err_el_10']:.2f}, AZ:{c['err_az']:.2f}, "
                f"AZ10:{c['err_az_10']:.2f}, wEL:{c['w_el']:.2f}, wAZ:{c['w_az']:.2f}, "
                f"GUN:{c['gun_pos']:.2f}, ROLL:{c['roll']:.2f}, PITCH:{c['pitch']:.2f}, "
                f"vT:{c['v_tank']:.2f}, vW:{c['v_wind']:.2f}, COS:{c['cos_fi']:.2f}, "
                f"P:{c['p_a']:.2f}] STAT:{packet[26]:02X}")

    def send_packet(self):
        if not self.is_connected:
            return

        packet = self.build_packet()
        try:
            self.serial_conn.write(packet)
            self.tx_counter += 1
            self.tx_label.configure(text=f"TX (PSPM->BC): {self.tx_counter}")
            self.blink_tx_once()
            self.log(f"TX PSPM->BC: {self.get_tx_log_string(packet)}", 'tx')
        except Exception as e:
            self.log(f"Send error: {e}", 'err')
            self.disconnect()

    def get_stream_period_ms(self):
        try:
            period = int(float(self.period_var.get()))
        except ValueError:
            period = 100
        period = max(10, min(1000, period))
        self.period_var.set(str(period))
        return period

    def schedule_stream_tick(self):
        self.stream_job = self.root.after(self.get_stream_period_ms(), self.stream_tick)

    def stream_tick(self):
        # Stream runs in the Tk main loop (same mechanism as the MSB simulator)
        # so logging and GUI updates stay perfectly smooth.
        self.stream_job = None
        if not (self.stream_active and self.is_connected):
            return
        self.send_packet()
        self.schedule_stream_tick()

    def toggle_stream(self):
        if not self.is_connected:
            messagebox.showwarning("Not Connected", "Connect to COM port first")
            return
        if not self.stream_active:
            self.update_tx_cache()
            self.stream_active = True
            self.send_btn.configure(state='disabled')
            self.stream_btn.configure(text="Stop Stream")
            self.log("Stream started", 'tx')
            self.schedule_stream_tick()
            self.save_settings()
        else:
            self.stream_active = False
            if self.stream_job is not None:
                self.root.after_cancel(self.stream_job)
                self.stream_job = None
            self.send_btn.configure(state='normal')
            self.stream_btn.configure(text="Start Stream")
            self.tx_indicator.itemconfig('rect', fill='gray')
            self.log("Stream stopped", 'rx')
            self.save_settings()

    def reset_counters(self):
        self.tx_counter = 0
        self.rx_counter = 0
        self.crc_errors = 0
        self.xor_errors = 0
        self.tx_label.configure(text=f"TX (PSPM->BC): {self.tx_counter}")
        self.rx_label.configure(text=f"RX (BC->PSPM): {self.rx_counter}")
        self.crc_label.configure(text=f"CRC Errors: {self.crc_errors}")
        self.xor_label.configure(text=f"XOR Errors: {self.xor_errors}")
        for key in self.raw_rx_data:
            self.raw_rx_data[key] = 0
        self.refresh_rx_display()
        self.log("Counters reset", 'rx')
        self.save_settings()

    def reset_to_zero(self):
        for k in SENSOR_FIELDS:
            getattr(self, k).set(0.0 if k != "p_a" else 750.0)
        for k in ["global_error", "adc_error", "fpga_error", "bmp280_error"]:
            getattr(self, k).set(False)
        # Generator back to disabled defaults
        self.gen_enabled.set(False)
        self.gen_wave_type.set("Sine")
        self.gen_target.set("err_el")
        self.gen_amplitude.set(10.0)
        self.gen_frequency.set(1.0)
        self.gen_offset.set(0.0)
        self.gen_start_time = time.perf_counter()
        # Start bytes back to firmware constants (host.h: 0xAA TX / 0x55 RX)
        self.start_byte_tx_var.set("0xAA")
        self.start_byte_rx_var.set("0x55")
        self.update_tx_cache()
        # Direct send only if send_on_change is enabled and streaming is inactive
        if self.send_on_change.get() and not self.stream_active and self.is_connected:
            self.send_packet()
        self.log("All variables reset to default zero states", 'tx')

    def log(self, message, tag=None):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Only update log view if freeze_view is not active
        if self.log_view_enabled.get() and not self.freeze_view.get():
            if tag:
                self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
            else:
                self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)

        if self.log_enabled.get():
            self.log_file_buf.append(f"[{timestamp}] {message}\n")

    def flush_log_file(self):
        if self.log_file_buf:
            if self.log_enabled.get():
                try:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        f.write(''.join(self.log_file_buf))
                except Exception:
                    pass
            self.log_file_buf = []
        self.root.after(500, self.flush_log_file)


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    app = PSPM2BCSimulator(root)

    def on_closing():
        app.save_settings()
        app.disconnect()
        if app.log_file_buf and app.log_enabled.get():
            try:
                with open(app.log_file, 'a', encoding='utf-8') as f:
                    f.write(''.join(app.log_file_buf))
            except Exception:
                pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
