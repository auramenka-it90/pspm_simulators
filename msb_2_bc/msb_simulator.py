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
import ctypes

# Определение реальной папки программы (работает и в .py, и в .exe)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ================================================================================
# HELP TEXTS
# ================================================================================
HELP_EN = """MSB SIMULATOR - DETAILED HELP & SPECIFICATION
================================================================================

1. UART SETTINGS (Left Panel)
   COM Port     - Select serial port (COM1, COM2, COM3...)
   Baudrate     - Data rate, fixed at 921600
   Parity       - Fixed at Even
   Data bits    - Fixed at 8
   Stop bits    - Fixed at 1
   Period (ms)  - Interval for Stream mode (10..1000 ms)

2. CONNECTION
   Connect/Disconnect - Opens/closes the COM port
   Indicator          - Red = Disconnected, Green = Connected

3. PACKET STRUCTURE MSB -> BC (32 bytes)
   Byte 0       - 0xAA (Start byte, adjustable)
   Bytes 1..28  - D[0]..D[27] (Data field 28 bytes)
   Bytes 29-30  - CRC16-CCITT (Little endian)
   Byte 31      - XOR_ALL

4. PACKET STRUCTURE BC -> MSB (32 bytes)
   Byte 0       - 0x55 (Start byte, adjustable)
   Bytes 1..28  - D[0]..D[27] (Data field 28 bytes)
   Bytes 29-30  - CRC16-CCITT (Little endian)
   Byte 31      - XOR_ALL

5. DATA FIELD D[0..27] - MSB -> BC (TRANSMIT)
   Bytes 0..1   - DISTANCE (1 LSB = 5 m). Max: 327675 m.
   Byte 2       - AMMO_TYPE (0=NONE, 1=APDS, 2=HEAT, 3=HEF, 4=MG, 5=GM)
   Byte 3       - FLAGS1:
                  [0] CC    : Duplicate
                  [1] DC    : Target designation
                  [2] SRD   : SetResetDistance (JK-trigger)
                  [3] BC_EN : BC Enable
                  [4] RL    : Rocket Launch
                  [5] WS    : Wind Sensor enabled
                  [6] PSCC  : Alignment scheme power
   Byte 4       - FLAGS2:
                  [0] K1         : Control
                  [1] BTN_CANNON : Cannon Button
                  [2] RF         : Reset Filters
                  [3] UR         : Unlock Reticle
                  [4] REM        : Rocket Elevation Mode
                  [5] DF         : DF Code
                  [6] SCF_ON     : SCF On
                  [7] SCF_ON_ADD : SCF On Add
   Bytes 5..14  - RESERVED (Always 0)
   Byte 15      - RX ECHO (NON-STANDARD debug extension: copy of BC flag byte
                  when Mirror RX is enabled; the real MSB always sends 0 here)
   Bytes 16..27 - RESERVED (Always 0)

6. DATA FIELD D[0..27] - BC -> MSB (RECEIVE)
   Byte 0       - FLAGS:
                  [0] ENA_SHOOTING     : Shooting Enabled
                  [1] GMEE             : Rocket Elevation Issued
                  [2] RANGE_OVER_1280  : Range > 1280 m
                  [3] UOI              : UOI Active
                  [4] INHIBIT_SHOOTING : Shooting Inhibited
                  [5] WIND_SENSOR_ON   : Wind Sensor On
                  [6] BC_ON            : BC Operating (MSB discrete P22)
                  [7] BC_READY         : BC Ready    (MSB discrete P23)
   Bytes 1..27  - RESERVED (Always 0)

7. SRD LOGIC
   SRD = 0 (Off) -> Packet sends DISTANCE = 0
   SRD = 1 (On)  -> Packet sends configured DISTANCE

8. SIGNALS (FLAGS)
   CC, DC, SRD, BC_EN, RL, WS, PSCC, K1, GUN TRG, RF, UR, REM, DF, SCF_ON, SCF_ON_ADD.
   GUN TRG uses debounce protection (hold '1', release '0').

9. CONTROL BUTTONS
   Send Packet    - Send single packet
   Start Stream   - Send continuously (Interval = Period)
   TX Start / RX Start - Override start bytes
   Mirror RX (Byte 15) - Echo the received flag byte back in MSB packet
   Send on Change - Instantly transmit the packet upon any parameter adjustment.
   Reset Flags    - Clear all flags, set APDS and 1600m
   Reset Counters - Reset diagnostic counters
   Clear Log      - Clear text output

10. LOGGING & SETTINGS
    Log View         - Show log in window
    Save Log to File - Write log to file
    Font             - Configure font (saved in JSON)
    Check RX CRC16   - If disabled, only XOR is checked on reception

11. CRC16-CCITT
    Polynomial: 0x1021, init: 0xFFFF

12. XOR_ALL
    xor_all = (Start) xor D[0] xor ... xor D[27] xor CRC_L xor CRC_H
================================================================================
"""

HELP_RU = """ИМИТАТОР MSB - ПОДРОБНАЯ СПРАВКА И СПЕЦИФИКАЦИЯ
================================================================================

1. UART НАСТРОЙКИ (левая панель)
   COM Port     - выбор последовательного порта (COM1, COM2, COM3...)
   Baudrate     - скорость обмена, фиксировано 921600
   Parity       - чётность, фиксировано Even
   Data bits    - биты данных, фиксировано 8
   Stop bits    - стоп-биты, фиксировано 1
   Period (ms)  - интервал отправки в режиме Stream (10..1000 мс)

2. ПОДКЛЮЧЕНИЕ
   Кнопка Connect/Disconnect - открывает/закрывает COM-порт
   Индикатор Connected       - красный = отключён, зелёный = подключён

3. СТРУКТУРА ПАКЕТА MSB -> BC (32 байта)
   Байт 0       - 0xAA (стартовый байт, можно менять)
   Байты 1..28  - D[0]..D[27] (поле данных 28 байт)
   Байты 29-30  - CRC16-CCITT (little endian)
   Байт 31      - XOR_ALL

4. СТРУКТУРА ПАКЕТА BC -> MSB (32 байта)
   Байт 0       - 0x55 (стартовый байт, можно менять)
   Байты 1..28  - D[0]..D[27] (поле данных 28 байт)
   Байты 29-30  - CRC16-CCITT (little endian)
   Байт 31      - XOR_ALL

5. ПОЛЕ D[0..27] - MSB -> BC (ПЕРЕДАЧА)
   Байты 0..1   - DISTANCE (дистанции, 1 LSB = 5 м). Макс: 327675 м.
   Байт 2       - AMMO_TYPE (0=NONE, 1=APDS(Б), 2=HEAT(К), 3=HEF(О), 4=MG(П), 5=GM(У))
   Байт 3       - FLAGS1:
                  [0] CC    : Дубль
                  [1] DC    : Целеуказание (ЦУ)
                  [2] SRD   : SetResetDistance (JK-триггер)
                  [3] BC_EN : Включение BC
                  [4] RL    : Ракета вылетела
                  [5] WS    : Датчик ветра разрешен
                  [6] PSCC  : Питание схемы совмещения
   Байт 4       - FLAGS2:
                  [0] K1         : Контроль
                  [1] BTN_CANNON : Выстрел пушка
                  [2] RF         : Обнуление фильтров
                  [3] UR         : Расстопоривание прицела
                  [4] REM        : Режим превышения для ракеты
                  [5] DF         : Код ДФ
                  [6] SCF_ON     : Включение СУО
                  [7] SCF_ON_ADD : Включение СУО дополнительно
   Байты 5..14  - RESERVED (всегда 0)
   Байт 15      - ЭХО BC_FLAGS (НЕ СТАНДАРТНО: отладочное расширение, копия
                  байта флагов от BC при включенном зеркале; реальная МСБ
                  всегда шлёт здесь 0)
   Байты 16..27 - RESERVED (всегда 0)

6. ПОЛЕ D[0..27] - BC -> MSB (ПРИЁМ)
   Байт 0       - FLAGS:
                  [0] ENA_SHOOTING     : Разрешение выстрела
                  [1] GMEE             : Выдача превышения для ракеты
                  [2] RANGE_OVER_1280  : Дальность больше 1280 м
                  [3] UOI              : Сигнал УОИ активен
                  [4] INHIBIT_SHOOTING : Запрет разрешения выстрела
                  [5] WIND_SENSOR_ON   : Включение датчика ветра
                  [6] BC_ON            : БЦ работает (дискрет МСБ P22)
                  [7] BC_READY         : БЦ готов (дискрет МСБ P23)
   Байты 1..27  - RESERVED (всегда 0)

7. ЛОГИКА SRD
   SRD = 0 (выключен) -> в пакет передаётся DISTANCE = 0
   SRD = 1 (включён)  -> в пакет передаётся введённое значение DISTANCE

8. СИГНАЛЫ (ФЛАГИ)
   CC, DC, SRD, BC_EN, RL, WS, PSCC, K1, GUN TRG, RF, UR, REM, DF, SCF_ON, SCF_ON_ADD.
   Кнопка GUN TRG работает с защитой от дребезга (удержание '1', отпускание '0').

9. КНОПКИ УПРАВЛЕНИЯ
   Send Packet    - одиночная отправка
   Start Stream   - циклическая отправка (с интервалом Period)
   TX Start / RX Start - возможность переопределить стартовые байты
   Mirror RX (Byte 15) - дублировать принятый байт флагов обратно в пакет MSB
   Send on Change - отправка пакета по изменению любого параметра.
   Reset Flags    - сбросить все флаги в 0, выставить APDS и 1600м
   Reset Counters - сброс счётчиков
   Clear Log      - очистка лога

10. ЛОГИРОВАНИЕ И НАСТРОЙКИ
    Log View         - отображение лога в окне
    Save Log to File - запись лога в файл
    Font             - настройка шрифта лога (сохраняется в JSON)
    Check RX CRC16   - если снята, при приёме проверяется только XOR

11. CRC16-CCITT
    Полином: 0x1021, init: 0xFFFF

12. XOR_ALL
    xor_all = (Старт) xor D[0] xor ... xor D[27] xor CRC_L xor CRC_H
================================================================================
"""

class MSBSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Mode Switching Board (MSB) Simulator v1.5")
        self.root.minsize(1100, 700)
        
        self.settings_file = os.path.join(APP_DIR, "msb_simulator_settings.json")
        self.log_file = os.path.join(APP_DIR, "msb_log.txt")
        
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
        self.period_var = tk.StringVar(value="20")
        
        # Start Bytes
        self.start_byte_tx_var = tk.StringVar(value="0xAA")
        self.start_byte_rx_var = tk.StringVar(value="0x55")
        
        # Signal States
        self.flags1 = 0
        self.flags2 = 0
        self.distance_m = 1600
        
        # Flag Variables
        self.cc_var = tk.BooleanVar()
        self.dc_var = tk.BooleanVar()
        self.bc_en_var = tk.BooleanVar()
        self.rl_var = tk.BooleanVar()
        self.ws_var = tk.BooleanVar()
        self.pscc_var = tk.BooleanVar()
        
        self.k1_var = tk.BooleanVar()
        self.rf_var = tk.BooleanVar()
        self.ur_var = tk.BooleanVar()
        self.rem_var = tk.BooleanVar()
        self.df_var = tk.BooleanVar()
        self.scf_on_var = tk.BooleanVar()
        self.scf_on_add_var = tk.BooleanVar()
        
        self.srd_var = tk.BooleanVar(value=False)
        self.btn_cannon_var = tk.BooleanVar(value=False)
        
        self.log_enabled = tk.BooleanVar(value=True)
        self.log_view_enabled = tk.BooleanVar(value=True)
        self.freeze_view = tk.BooleanVar(value=False)
        self.send_on_change = tk.BooleanVar(value=False)
        
        self.check_crc_rx_var = tk.BooleanVar(value=True)
        self.mirror_rx_var = tk.BooleanVar(value=False)
        
        # Font settings
        self.log_font_family = tk.StringVar(value="Consolas")
        self.log_font_size = tk.IntVar(value=10)
        
        # RX Variables
        self.bc_ena_shooting = tk.BooleanVar()
        self.bc_gmee = tk.BooleanVar()
        self.bc_range_over_1280 = tk.BooleanVar()
        self.bc_uoi = tk.BooleanVar()
        self.bc_inhibit_shooting = tk.BooleanVar()
        self.bc_wind_sensor_on = tk.BooleanVar()
        self.bc_rfu6 = tk.BooleanVar()
        self.bc_rfu7 = tk.BooleanVar()
        
        # Storage for received BC byte (for Echo in D[15])
        self.last_rx_bc_flags = 0
        
        # Buffered file logging: lines accumulate and flush every 500 ms,
        # so per-message disk access never stalls the GUI thread
        self.log_file_buf = []
        self.root.after(500, self.flush_log_file)
        
        self.setup_gui()
        self.refresh_ports()
        self.load_settings()

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
        self.save_settings()
        
    def show_help(self):
        help_window = tk.Toplevel(self.root)
        help_window.title("HELP / СПРАВКА - MSB Simulator")
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
                "mirror_rx": self.mirror_rx_var.get(),
                "send_on_change": self.send_on_change.get(),
                "distance": self.distance_m,
                "ammo_type": self.ammo_var.get(),
                "log_enabled": self.log_enabled.get(),
                "log_view_enabled": self.log_view_enabled.get(),
                "freeze_view": self.freeze_view.get(),
                "check_crc_rx": self.check_crc_rx_var.get(),
                "font_family": self.log_font_family.get(),
                "font_size": self.log_font_size.get(),
                "flags": {
                    "cc": self.cc_var.get(),
                    "dc": self.dc_var.get(),
                    "bc_en": self.bc_en_var.get(),
                    "rl": self.rl_var.get(),
                    "ws": self.ws_var.get(),
                    "pscc": self.pscc_var.get(),
                    "k1": self.k1_var.get(),
                    "rf": self.rf_var.get(),
                    "ur": self.ur_var.get(),
                    "rem": self.rem_var.get(),
                    "df": self.df_var.get(),
                    "scf_on": self.scf_on_var.get(),
                    "scf_on_add": self.scf_on_add_var.get(),
                    "srd": self.srd_var.get(),
                    "btn_cannon": self.btn_cannon_var.get()
                },
                "window_geometry": self.root.geometry(),
                "tx_counter": self.tx_counter,
                "rx_counter": self.rx_counter,
                "crc_errors": self.crc_errors,
                "xor_errors": self.xor_errors
            }
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
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
                if "mirror_rx" in settings: self.mirror_rx_var.set(settings["mirror_rx"])
                if "send_on_change" in settings: self.send_on_change.set(settings["send_on_change"])
                
                if "distance" in settings:
                    self.distance_m = settings["distance"]
                    self.distance_var.set(str(self.distance_m))
                    self.distance_slider.set(self.distance_m)
                if "ammo_type" in settings:
                    self.ammo_var.set(settings["ammo_type"])
                if "log_enabled" in settings:
                    self.log_enabled.set(settings["log_enabled"])
                if "log_view_enabled" in settings:
                    self.log_view_enabled.set(settings["log_view_enabled"])
                if "freeze_view" in settings:
                    self.freeze_view.set(settings["freeze_view"])
                if "check_crc_rx" in settings:
                    self.check_crc_rx_var.set(settings["check_crc_rx"])
                
                if "font_family" in settings: self.log_font_family.set(settings["font_family"])
                if "font_size" in settings: self.log_font_size.set(settings["font_size"])
                
                new_f = (self.log_font_family.get(), self.log_font_size.get())
                self.apply_new_font(new_f)
                
                if "flags" in settings:
                    f_set = settings["flags"]
                    if "cc" in f_set: self.cc_var.set(f_set["cc"])
                    if "dc" in f_set: self.dc_var.set(f_set["dc"])
                    if "bc_en" in f_set: self.bc_en_var.set(f_set["bc_en"])
                    if "rl" in f_set: self.rl_var.set(f_set["rl"])
                    if "ws" in f_set: self.ws_var.set(f_set["ws"])
                    if "pscc" in f_set: self.pscc_var.set(f_set["pscc"])
                    if "k1" in f_set: self.k1_var.set(f_set["k1"])
                    if "rf" in f_set: self.rf_var.set(f_set["rf"])
                    if "ur" in f_set: self.ur_var.set(f_set["ur"])
                    if "rem" in f_set: self.rem_var.set(f_set["rem"])
                    if "df" in f_set: self.df_var.set(f_set["df"])
                    if "scf_on" in f_set: self.scf_on_var.set(f_set["scf_on"])
                    if "scf_on_add" in f_set: self.scf_on_add_var.set(f_set["scf_on_add"])
                    if "srd" in f_set: self.srd_var.set(f_set["srd"])
                    if "btn_cannon" in f_set: self.btn_cannon_var.set(f_set["btn_cannon"])
                
                if "window_geometry" in settings:
                    try: self.root.geometry(settings["window_geometry"])
                    except: pass
                
                if "tx_counter" in settings:
                    self.tx_counter = settings["tx_counter"]
                    self.tx_label.configure(text=f"TX (MSB->BC): {self.tx_counter}")
                if "rx_counter" in settings:
                    self.rx_counter = settings["rx_counter"]
                    self.rx_label.configure(text=f"RX (BC->MSB): {self.rx_counter}")
                if "crc_errors" in settings:
                    self.crc_errors = settings["crc_errors"]
                    self.crc_label.configure(text=f"CRC Errors: {self.crc_errors}")
                if "xor_errors" in settings:
                    self.xor_errors = settings["xor_errors"]
                    self.xor_label.configure(text=f"XOR Errors: {self.xor_errors}")
                
                self.update_flags1()
                self.update_flags2()
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
        
        # Title
        title_lbl = ttk.Label(main_frame, text="Font Settings", font=('TkDefaultFont', 11, 'bold'))
        title_lbl.pack(side=tk.TOP, pady=(0, 10))
        
        family_var = tk.StringVar(value=self.log_font_family.get())
        size_var = tk.IntVar(value=self.log_font_size.get())
        
        # Font family
        font_frame = ttk.Frame(main_frame)
        font_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        ttk.Label(font_frame, text="Font:").pack(side=tk.LEFT, padx=(0, 10))
        available_fonts = list(tkfont.families())
        available_fonts.sort()
        font_combo = ttk.Combobox(font_frame, textvariable=family_var, values=available_fonts, state="readonly", width=30)
        font_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Size
        size_frame = ttk.Frame(main_frame)
        size_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        ttk.Label(size_frame, text="Size:").pack(side=tk.LEFT, padx=(0, 10))
        size_spin = ttk.Spinbox(size_frame, textvariable=size_var, from_=8, to=72, width=5)
        size_spin.pack(side=tk.LEFT)
        
        # Bottom Buttons packed first
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        
        # Preview Frame packed last (Greedy middle widget)
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
            
        def cancel_action():
            font_win.destroy()

        ttk.Button(btn_frame, text="Apply (OK)", command=apply_font).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=cancel_action).pack(side=tk.RIGHT, padx=5)
    
    def update_widget_tree_font(self, parent, new_font):
        """Recursively update font option on all eligible widgets in the hierarchy."""
        try:
            parent.configure(font=new_font)
        except tk.TclError:
            pass # Widget class does not support direct font option
            
        for child in parent.winfo_children():
            self.update_widget_tree_font(child, new_font)

    def apply_new_font(self, new_font):
        try:
            self.log_font_family.set(new_font[0])
            self.log_font_size.set(new_font[1])
            
            # 1. Update options database for newly spawned elements
            self.root.option_add('*Font', new_font)
            
            # 2. Force style configurations across TTK style map
            style = ttk.Style()
            style.configure('.', font=new_font)
            style.configure('TLabel', font=new_font)
            style.configure('TButton', font=new_font)
            style.configure('TEntry', font=new_font)
            style.configure('TCombobox', font=new_font)
            style.configure('TCheckbutton', font=new_font)
            style.configure('TRadiobutton', font=new_font)
            style.configure('TLabelframe.Label', font=new_font)
            
            # 3. Recursively update existing widgets
            self.update_widget_tree_font(self.root, new_font)
            
            self.save_settings()
        except Exception as e:
            messagebox.showerror("Font Error", f"Error applying font: {str(e)}")

    def on_btn_cannon_press(self, event):
        self.btn_cannon_var.set(True)
        self.update_flags2()
        # Direct send only if send_on_change is enabled and streaming is inactive
        if self.send_on_change.get() and not self.stream_active and self.is_connected:
            self.send_packet()
    
    def on_btn_cannon_release(self, event):
        self.btn_cannon_var.set(False)
        self.update_flags2()
        # Direct send only if send_on_change is enabled and streaming is inactive
        if self.send_on_change.get() and not self.stream_active and self.is_connected:
            self.send_packet()
            
    def reset_flags(self):
        self.distance_m = 1600
        self.distance_var.set(str(self.distance_m))
        self.distance_slider.set(self.distance_m)
        self.ammo_var.set("APDS")
        
        self.cc_var.set(False)
        self.dc_var.set(False)
        self.bc_en_var.set(False)
        self.rl_var.set(False)
        self.ws_var.set(False)
        self.pscc_var.set(False)
        self.srd_var.set(False)
        
        self.k1_var.set(False)
        self.rf_var.set(False)
        self.ur_var.set(False)
        self.rem_var.set(False)
        self.df_var.set(False)
        self.scf_on_var.set(False)
        self.scf_on_add_var.set(False)
        self.btn_cannon_var.set(False)
        
        self.update_flags1()
        self.update_flags2()
        
        # Direct send only if send_on_change is enabled and streaming is inactive
        if self.send_on_change.get() and not self.stream_active and self.is_connected:
            self.send_packet()
            
        self.log("Flags reset to defaults", 'tx')
        # OPTIMIZATION: Removed redundant save_settings() disk write
    
    def blink_tx_once(self):
        self.tx_indicator.itemconfig('rect', fill='#00FF00')
        self.root.after(150, lambda: self.tx_indicator.itemconfig('rect', fill='gray'))
    
    def make_led_row(self, parent, text, var):
        row = ttk.Frame(parent)
        row.pack(anchor=tk.W, pady=1)
        try:
            led_bg = ttk.Style().lookup('TLabelframe', 'background') or 'SystemButtonFace'
        except tk.TclError:
            led_bg = 'SystemButtonFace'
        led = tk.Canvas(row, width=18, height=18, highlightthickness=0, bg=led_bg)
        led.create_oval(1, 1, 17, 17, fill='#333333', outline='#4d4d4d', width=2, tags='halo')
        led.create_oval(4, 4, 14, 14, fill='#333333', outline='', tags='led')
        led.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(row, text=text).pack(side=tk.LEFT)
        return (led, var)
    
    def update_bc_leds(self):
        for led, var in self.bc_led_rows:
            if var.get():
                led.itemconfig('led', fill='#39FF14')
                led.itemconfig('halo', fill='#0C6B1A', outline='#39FF14')
            else:
                led.itemconfig('led', fill='#333333')
                led.itemconfig('halo', fill='#242424', outline='#4d4d4d')
    
    def blink_rx_once(self):
        self.rx_indicator.itemconfig('rect', fill='#FFFF00')
        self.root.after(150, lambda: self.rx_indicator.itemconfig('rect', fill='gray'))
    
    def setup_gui(self):
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # ========== LEFT PANEL ==========
        left_frame = ttk.LabelFrame(main_paned, text="UART Settings", padding="10")
        main_paned.add(left_frame, weight=0)
        
        ttk.Label(left_frame, text="COM Port:").pack(anchor=tk.W, pady=(0,2))
        self.port_combo = ttk.Combobox(left_frame, textvariable=self.port_var, width=12)
        self.port_combo.pack(anchor=tk.W, pady=(0,5))
        
        ttk.Button(left_frame, text="↻ Refresh", command=self.refresh_ports).pack(anchor=tk.W, pady=(0,10))
        
        ttk.Label(left_frame, text="Baudrate:").pack(anchor=tk.W, pady=(0,2))
        baud_combo = ttk.Combobox(left_frame, textvariable=self.baud_var, width=12,
                                   values=["9600","19200","38400","57600","115200","230400","460800","921600"])
        baud_combo.pack(anchor=tk.W, pady=(0,10))
        
        ttk.Label(left_frame, text="Parity:").pack(anchor=tk.W, pady=(0,2))
        parity_combo = ttk.Combobox(left_frame, textvariable=self.parity_var, width=12,
                                     values=["None","Even","Odd"])
        parity_combo.pack(anchor=tk.W, pady=(0,10))
        
        ttk.Label(left_frame, text="Data bits:").pack(anchor=tk.W, pady=(0,2))
        databits_combo = ttk.Combobox(left_frame, textvariable=self.databits_var, width=12,
                                       values=["5","6","7","8"])
        databits_combo.pack(anchor=tk.W, pady=(0,10))
        
        ttk.Label(left_frame, text="Stop bits:").pack(anchor=tk.W, pady=(0,2))
        stopbits_combo = ttk.Combobox(left_frame, textvariable=self.stopbits_var, width=12,
                                       values=["1","1.5","2"])
        stopbits_combo.pack(anchor=tk.W, pady=(0,10))
        
        ttk.Label(left_frame, text="Period (ms):").pack(anchor=tk.W, pady=(0,2))
        period_entry = ttk.Entry(left_frame, textvariable=self.period_var, width=12)
        period_entry.pack(anchor=tk.W, pady=(0,10))
        
        self.connect_btn = ttk.Button(left_frame, text="Connect", command=self.toggle_connection)
        self.connect_btn.pack(anchor=tk.W, pady=(5,5))
        
        status_frame = ttk.Frame(left_frame)
        status_frame.pack(anchor=tk.W, pady=(5,0))
        self.conn_indicator = tk.Canvas(status_frame, width=20, height=7, highlightthickness=0)
        self.conn_indicator.create_rectangle(0, 0, 20, 7, fill='red', outline='', tags='rect')
        self.conn_indicator.pack(side=tk.LEFT, padx=(0,5))
        self.conn_label = ttk.Label(status_frame, text="Disconnected")
        self.conn_label.pack(side=tk.LEFT)
        
        tx_frame = ttk.Frame(left_frame)
        tx_frame.pack(anchor=tk.W, pady=(10,2))
        self.tx_indicator = tk.Canvas(tx_frame, width=20, height=7, highlightthickness=0)
        self.tx_indicator.create_rectangle(0, 0, 20, 7, fill='gray', outline='', tags='rect')
        self.tx_indicator.pack(side=tk.LEFT, padx=(0,5))
        ttk.Label(tx_frame, text="TX").pack(side=tk.LEFT)
        
        rx_frame = ttk.Frame(left_frame)
        rx_frame.pack(anchor=tk.W, pady=(2,0))
        self.rx_indicator = tk.Canvas(rx_frame, width=20, height=7, highlightthickness=0)
        self.rx_indicator.create_rectangle(0, 0, 20, 7, fill='gray', outline='', tags='rect')
        self.rx_indicator.pack(side=tk.LEFT, padx=(0,5))
        ttk.Label(rx_frame, text="RX").pack(side=tk.LEFT)
        
        ttk.Button(left_frame, text="HELP", command=self.show_help).pack(anchor=tk.W, pady=(10,0))
        
        # ========== CENTER PANEL ==========
        center_frame = ttk.LabelFrame(main_paned, text="Mode Switching Board Control", padding="10")
        main_paned.add(center_frame, weight=1)
        
        # Distance
        dist_frame = ttk.LabelFrame(center_frame, text="Distance to Target", padding="5")
        dist_frame.pack(fill=tk.X, pady=(0,5))
        
        ttk.Label(dist_frame, text="Distance (meters):").pack(anchor=tk.W)
        
        dist_value_frame = ttk.Frame(dist_frame)
        dist_value_frame.pack(fill=tk.X, pady=5)
        
        self.distance_var = tk.StringVar(value="1600")
        distance_entry = ttk.Entry(dist_value_frame, textvariable=self.distance_var, width=8)
        distance_entry.pack(side=tk.LEFT, padx=(0,10))
        distance_entry.bind('<KeyRelease>', self.on_distance_entry)
        
        ttk.Label(dist_value_frame, text="(1 LSB = 5 m)").pack(side=tk.LEFT)
        
        self.distance_slider = tk.Scale(dist_frame, from_=0, to=10000, orient=tk.HORIZONTAL,
                                         resolution=5, command=self.on_distance_slider,
                                         length=200, width=12, sliderlength=12)
        self.distance_slider.set(1600)
        self.distance_slider.pack(fill=tk.X, pady=5)
        
        # Ammo type
        ammo_frame = ttk.LabelFrame(center_frame, text="Ammunition Type", padding="5")
        ammo_frame.pack(fill=tk.X, pady=(0,5))
        
        self.ammo_var = tk.StringVar(value="APDS")
        ammo_row = ttk.Frame(ammo_frame)
        ammo_row.pack()
        for val, text in [("NONE","NONE"), ("APDS","APDS"), ("HEAT","HEAT"), ("HEF","HEF"), ("MG","MG"), ("GM","GM")]:
            ttk.Radiobutton(ammo_row, text=text, variable=self.ammo_var, value=val, command=self.on_flag_toggle).pack(side=tk.LEFT, padx=3)
        
        # -------------------------------------------------------------------------
        # FLAGS 
        # -------------------------------------------------------------------------
        flags_container = ttk.Frame(center_frame)
        flags_container.pack(fill=tk.X, pady=(0,5))
        
        # Flags part 1
        flags1_frame = ttk.LabelFrame(flags_container, text="Flags Part 1 (MSB -> BC)", padding="5")
        flags1_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,2))
        
        ttk.Checkbutton(flags1_frame, text="CC (duplicate)", variable=self.cc_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags1_frame, text="DC (target designation)", variable=self.dc_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags1_frame, text="BC_EN (BC enable)", variable=self.bc_en_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags1_frame, text="RL (rocket launch)", variable=self.rl_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags1_frame, text="WS (wind sensor)", variable=self.ws_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags1_frame, text="PSCC (power supply)", variable=self.pscc_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        
        # SRD
        srd_frame = ttk.LabelFrame(flags1_frame, text="SRD (JK Trigger)", padding="5")
        srd_frame.pack(fill=tk.X, pady=(5,0))
        ttk.Checkbutton(srd_frame, text="SRD (SetResetDistance)", variable=self.srd_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        
        # Flags part 2
        flags2_frame = ttk.LabelFrame(flags_container, text="Flags Part 2 (MSB -> BC)", padding="5")
        flags2_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(2,0))
        
        ttk.Checkbutton(flags2_frame, text="K1 (control)", variable=self.k1_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags2_frame, text="BTN_CANNON", variable=self.btn_cannon_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags2_frame, text="RF (reset filters)", variable=self.rf_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags2_frame, text="UR (unlock reticle)", variable=self.ur_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags2_frame, text="REM (rocket elevation mode)", variable=self.rem_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags2_frame, text="DF (DF code)", variable=self.df_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags2_frame, text="SCF_ON", variable=self.scf_on_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        ttk.Checkbutton(flags2_frame, text="SCF_ON_ADD", variable=self.scf_on_add_var, command=self.on_flag_toggle).pack(anchor=tk.W)
        
        # ACTION BUTTONS ROW
        act_frame = ttk.Frame(center_frame)
        act_frame.pack(fill=tk.X, pady=5)
        
        # GUN TRG Button
        self.cannon_btn = ttk.Button(act_frame, text="GUN TRG", width=12)
        self.cannon_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.cannon_btn.bind('<ButtonPress-1>', self.on_btn_cannon_press)
        self.cannon_btn.bind('<ButtonRelease-1>', self.on_btn_cannon_release)
        
        # Reset Flags Button
        ttk.Button(act_frame, text="Reset Flags", command=self.reset_flags, width=12).pack(side=tk.LEFT)
        
        # Send/Stream Control Row
        send_frame = ttk.Frame(center_frame)
        send_frame.pack(fill=tk.X, pady=10)
        
        self.send_btn = ttk.Button(send_frame, text="Send Packet", command=self.send_packet, width=12)
        self.send_btn.pack(side=tk.LEFT, padx=5)
        
        self.stream_btn = ttk.Button(send_frame, text="Start Stream", command=self.toggle_stream, width=12)
        self.stream_btn.pack(side=tk.LEFT, padx=5)
        
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
        
        # Mirror RX Checkbox
        self.mirror_check = ttk.Checkbutton(send_frame, text="Mirror RX (Byte 15)", variable=self.mirror_rx_var, command=self.save_settings)
        self.mirror_check.pack(side=tk.LEFT, padx=(15, 5))
        
        # ADDITION: "Send on Change" Checkbox inside send_frame control row
        self.send_on_change_check = ttk.Checkbutton(send_frame, text="Send on Change", variable=self.send_on_change, command=self.save_settings)
        self.send_on_change_check.pack(side=tk.LEFT, padx=(15, 5))
        
        # ========== RIGHT PANEL ==========
        right_frame = ttk.LabelFrame(main_paned, text="Diagnostics & BC Commands", padding="10")
        main_paned.add(right_frame, weight=0)
        
        status_frame2 = ttk.LabelFrame(right_frame, text="Status", padding="5")
        status_frame2.pack(fill=tk.X, pady=(0,5))
        
        self.status_label2 = ttk.Label(status_frame2, text="Disconnected", foreground="red")
        self.status_label2.pack(anchor=tk.W)
        
        counters_frame = ttk.LabelFrame(right_frame, text="Counters", padding="5")
        counters_frame.pack(fill=tk.X, pady=(0,5))
        
        ttk.Checkbutton(counters_frame, text="Check RX CRC16", variable=self.check_crc_rx_var, command=self.save_settings).pack(anchor=tk.W, pady=(0,5))
        
        self.tx_label = ttk.Label(counters_frame, text=f"TX (MSB->BC): {self.tx_counter}")
        self.tx_label.pack(anchor=tk.W)
        self.rx_label = ttk.Label(counters_frame, text=f"RX (BC->MSB): {self.rx_counter}")
        self.rx_label.pack(anchor=tk.W)
        self.crc_label = ttk.Label(counters_frame, text=f"CRC Errors: {self.crc_errors}")
        self.crc_label.pack(anchor=tk.W)
        self.xor_label = ttk.Label(counters_frame, text=f"XOR Errors: {self.xor_errors}")
        self.xor_label.pack(anchor=tk.W)
        
        ttk.Button(counters_frame, text="Reset Counters", command=self.reset_counters).pack(pady=5)
        
        bc_frame = ttk.LabelFrame(right_frame, text="Commands from BC (BC -> MSB)", padding="5")
        bc_frame.pack(fill=tk.X)
        
        # Received BC command bits shown as read-only LED indicators
        self.bc_led_rows = []
        for i, (text, var) in enumerate([
            ("BIT0: ENA_SHOOTING", self.bc_ena_shooting),
            ("BIT1: GMEE", self.bc_gmee),
            ("BIT2: RANGE_OVER_1280", self.bc_range_over_1280),
            ("BIT3: UOI", self.bc_uoi),
            ("BIT4: INHIBIT_SHOOTING", self.bc_inhibit_shooting),
            ("BIT5: WIND_SENSOR_ON", self.bc_wind_sensor_on),
            ("BIT6: BC_ON", self.bc_rfu6),
            ("BIT7: BC_READY", self.bc_rfu7),
        ]):
            self.bc_led_rows.append(self.make_led_row(bc_frame, text, var))
        
        # ========== BOTTOM PANEL - LOG ==========
        log_display_frame = ttk.LabelFrame(self.root, text="Event Log", padding="5")
        log_display_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0,5))
        
        # OPTIMIZATION: Pack button frame first at the BOTTOM
        log_btn_frame = ttk.Frame(log_display_frame)
        log_btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        
        # OPTIMIZATION: Pack greedy scrolledtext second at the TOP (leaves room for buttons during window shrink)
        self.log_text = scrolledtext.ScrolledText(log_display_frame, height=12, wrap=tk.WORD)
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.log_text.tag_configure('tx', background='#90EE90')
        self.log_text.tag_configure('rx', background='#FFF44F')
        self.log_text.tag_configure('err', background='#FF9999')
        
        self.log_view_check = ttk.Checkbutton(log_btn_frame, text="Log View", variable=self.log_view_enabled)
        self.log_view_check.pack(side=tk.LEFT, padx=5)
        
        self.log_check = ttk.Checkbutton(log_btn_frame, text="Save Log to File", variable=self.log_enabled, command=self.save_settings)
        self.log_check.pack(side=tk.LEFT, padx=5)
        
        # ERGONOMIC ADDITION: Freeze View stops GUI logs while keeping files and streams active
        self.freeze_check = ttk.Checkbutton(log_btn_frame, text="Freeze View", variable=self.freeze_view, command=self.save_settings)
        self.freeze_check.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(log_btn_frame, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(log_btn_frame, text="Font", command=self.open_font_dialog).pack(side=tk.RIGHT, padx=5)
    
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        self.log_file_buf = []
        
        if self.log_enabled.get():
            try:
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.write("")
            except:
                pass
    
    def on_distance_slider(self, value):
        self.distance_m = int(float(value))
        self.distance_var.set(str(self.distance_m))
        # Direct send only if send_on_change is enabled and streaming is inactive
        if self.send_on_change.get() and not self.stream_active and self.is_connected:
            self.send_packet()
        # OPTIMIZATION: Removed slow synchronous save_settings() disk write from slider command

    def on_distance_entry(self, event):
        try:
            self.distance_m = int(self.distance_var.get())
            if self.distance_m < 0:
                self.distance_m = 0
            if self.distance_m > 10000:
                self.distance_m = 10000
            self.distance_var.set(str(self.distance_m))
            self.distance_slider.set(self.distance_m)
            # Direct send only if send_on_change is enabled and streaming is inactive
            if self.send_on_change.get() and not self.stream_active and self.is_connected:
                self.send_packet()
        except:
            pass
    
    def update_flags1(self):
        self.flags1 = 0
        if self.cc_var.get(): self.flags1 |= 0x01
        if self.dc_var.get(): self.flags1 |= 0x02
        if self.bc_en_var.get(): self.flags1 |= 0x08
        if self.rl_var.get(): self.flags1 |= 0x10
        if self.ws_var.get(): self.flags1 |= 0x20
        if self.pscc_var.get(): self.flags1 |= 0x40
        if self.srd_var.get(): self.flags1 |= 0x04
    
    def update_flags2(self):
        self.flags2 = 0
        if self.k1_var.get(): self.flags2 |= 0x01
        if self.btn_cannon_var.get(): self.flags2 |= 0x02
        if self.rf_var.get(): self.flags2 |= 0x04
        if self.ur_var.get(): self.flags2 |= 0x08
        if self.rem_var.get(): self.flags2 |= 0x10
        if self.df_var.get(): self.flags2 |= 0x20
        if self.scf_on_var.get(): self.flags2 |= 0x40
        if self.scf_on_add_var.get(): self.flags2 |= 0x80
        # OPTIMIZATION: Removed slow save_settings() call here.
        # It was blocking background threads during streams.

    def on_flag_toggle(self):
        """Unified callback for all checkbox and radio changes in UI."""
        self.update_flags1()
        self.update_flags2()
        # Direct send only if send_on_change is enabled and streaming is inactive
        if self.send_on_change.get() and not self.stream_active and self.is_connected:
            self.send_packet()

    def update_srd(self):
        self.on_flag_toggle()
    
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
            parity = parity_map.get(self.parity_var.get(), serial.PARITY_NONE)
            stopbits_map = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE, "2": serial.STOPBITS_TWO}
            stopbits = stopbits_map.get(self.stopbits_var.get(), serial.STOPBITS_ONE)
            
            self.serial_conn = serial.Serial(
                port=port, baudrate=baudrate, parity=parity,
                bytesize=int(self.databits_var.get()), stopbits=stopbits, timeout=1
            )
            self.is_connected = True
            self.connect_btn.configure(text="Disconnect")
            self.conn_indicator.itemconfig('rect', fill='#00FF00')
            self.status_label2.configure(text="Connected", foreground="green")
            self.port_combo.configure(state='disabled')
            
            self.rx_thread = threading.Thread(target=self.receive_data, daemon=True)
            self.rx_thread.start()
            parity_letter = {"None": "N", "Even": "E", "Odd": "O"}.get(self.parity_var.get(), "?")
            self.log(f"Connected to BC on {port} @ {baudrate} {self.databits_var.get()}{parity_letter}{self.stopbits_var.get()}", 'rx')
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
            except:
                pass
        self.serial_conn = None
        self.is_connected = False
        self.connect_btn.configure(text="Connect")
        self.conn_indicator.itemconfig('rect', fill='red')
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
                        
                        start_rx = self.parse_hex(self.start_byte_rx_var.get(), 0x55)
                            
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
                            
                time.sleep(0.001)
            except Exception:
                break
    
    def process_rx_packet(self, data):
        start_rx = self.parse_hex(self.start_byte_rx_var.get(), 0x55)
            
        if len(data) != 32 or data[0] != start_rx:
            return
        
        # 1. XOR validation (XOR first, early return - same order as MSB firmware)
        calc_xor = 0
        for i in range(31):
            calc_xor ^= data[i]
        rx_xor = data[31]
        
        if calc_xor != rx_xor:
            self.xor_errors += 1
            self.xor_label.configure(text=f"XOR Errors: {self.xor_errors}")
            self.log(f"RX XOR ERROR: {data.hex(' ')}", 'err')
            return
            
        # 2. CRC validation
        if self.check_crc_rx_var.get():
            calc_crc = self.calculate_crc16_ccitt(data[:29])
            rx_crc = data[29] | (data[30] << 8)
            
            if calc_crc != rx_crc:
                self.crc_errors += 1
                self.crc_label.configure(text=f"CRC Errors: {self.crc_errors}")
                self.log(f"RX CRC ERROR: {data.hex(' ')}", 'err')
                return

        self.blink_rx_once()
        self.rx_counter += 1
        self.rx_label.configure(text=f"RX (BC->MSB): {self.rx_counter}")
        
        self.log(f"RX BC->MSB: {data.hex(' ')}", 'rx')
        
        bc_flags = data[1]
        self.last_rx_bc_flags = bc_flags
        
        self.bc_ena_shooting.set(bool(bc_flags & 0x01))
        self.bc_gmee.set(bool(bc_flags & 0x02))
        self.bc_range_over_1280.set(bool(bc_flags & 0x04))
        self.bc_uoi.set(bool(bc_flags & 0x08))
        self.bc_inhibit_shooting.set(bool(bc_flags & 0x10))
        self.bc_wind_sensor_on.set(bool(bc_flags & 0x20))
        self.bc_rfu6.set(bool(bc_flags & 0x40))
        self.bc_rfu7.set(bool(bc_flags & 0x80))
        self.update_bc_leds()
    
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
    
    def build_packet(self):
        data = bytearray(28)
        
        if self.srd_var.get():
            distance_raw = self.distance_m // 5
        else:
            distance_raw = 0
        
        data[0] = distance_raw & 0xFF
        data[1] = (distance_raw >> 8) & 0xFF
        
        ammo_map = {"NONE": 0, "APDS": 1, "HEAT": 2, "HEF": 3, "MG": 4, "GM": 5}
        data[2] = ammo_map.get(self.ammo_var.get(), 0)
        
        self.update_flags1()
        data[3] = self.flags1
        
        self.update_flags2()
        data[4] = self.flags2

        # Echo received BC flags byte back in payload reserve D[15]
        if self.mirror_rx_var.get():
            data[15] = self.last_rx_bc_flags
        
        packet = bytearray()
        start_tx = self.parse_hex(self.start_byte_tx_var.get(), 0xAA)
            
        packet.append(start_tx)
        packet.extend(data)
        
        crc = self.calculate_crc16_ccitt(packet)
        packet.append(crc & 0xFF)
        packet.append((crc >> 8) & 0xFF)
        
        xor_all = 0
        for b in packet:
            xor_all ^= b
        packet.append(xor_all)
        
        return packet
    
    def send_packet(self):
        if not self.is_connected:
            return
        
        packet = self.build_packet()
        try:
            self.serial_conn.write(packet)
            self.tx_counter += 1
            self.tx_label.configure(text=f"TX (MSB->BC): {self.tx_counter}")
            
            self.blink_tx_once()
            self.log(f"TX MSB->BC: {packet.hex(' ')}", 'tx')
            # OPTIMIZATION: Removed redundant save_settings() disk write
        except Exception as e:
            self.log(f"Send error: {e}", 'err')
            self.disconnect()
            
    def get_stream_period_ms(self):
        try:
            period = int(float(self.period_var.get()))
        except ValueError:
            period = 20
        period = max(10, min(1000, period))
        self.period_var.set(str(period))
        return period

    def schedule_stream_tick(self):
        self.stream_job = self.root.after(self.get_stream_period_ms(), self.stream_tick)

    def stream_tick(self):
        # Stream runs in the Tk main loop (same mechanism as the BC simulator
        # async TX) so logging and GUI updates stay perfectly smooth.
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
        self.tx_label.configure(text=f"TX (MSB->BC): {self.tx_counter}")
        self.rx_label.configure(text=f"RX (BC->MSB): {self.rx_counter}")
        self.crc_label.configure(text=f"CRC Errors: {self.crc_errors}")
        self.xor_label.configure(text=f"XOR Errors: {self.xor_errors}")
        self.last_rx_bc_flags = 0
        self.log("Counters reset", 'rx')
        self.save_settings()
    
    def log(self, message, tag=None):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # ERGONOMIC OPTIMIZATION: Only update log view if freeze_view is not active
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
    app = MSBSimulator(root)
    
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