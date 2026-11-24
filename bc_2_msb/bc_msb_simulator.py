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
HELP_EN = """BALLISTIC COMPUTER (BC) SIMULATOR FOR MSB - SPECIFICATION
================================================================================

1. OPERATION PRINCIPLE (Hardware Master Mode)
   The hardware MSB board transmits telemetry packets (Start: 0xAA) at 50 Hz (every 20 ms).
   This simulator listens for MSB packets, validates CRC16 & XOR, decodes all 31 inputs,
   and IMMEDIATELY replies with a 32-byte BC Command packet (Start: 0x55).

2. UART SETTINGS (Left Panel)
   COM Port     - Select serial port connected to MSB USART2 (RS-485 line)
   Baudrate     - Selectable 9600..921600 (hardware requires 921600)
   Parity       - Selectable None/Even/Odd (hardware requires Even)
   Data bits    - Selectable 5..8 (hardware requires 8)
   Stop bits    - Selectable 1/1.5/2 (hardware requires 1)
   Period (ms)  - Async TX timer period, 10..1000 ms (default 20 = 50 Hz)

3. PACKET STRUCTURE MSB -> BC (RECEIVE - 32 bytes)
   Byte 0       - 0xAA (Header)
   Bytes 1..2   - Target Distance (1 LSB = 5 m, forced 0 when SRD flag is 0)
   Byte 3       - Ammo Type (0=NONE, 1=APDS, 2=HEAT, 3=HEF, 4=MG, 5=GM)
   Byte 4       - Flags 1 (CC, DC, SRD, BC_EN, RL, WS, PSCC)
   Byte 5       - Flags 2 (K1, BTN_CANNON, RF, UR, REM, DF, SCF_ON, SCF_ON_ADD)
   Bytes 6..28  - Reserved (0x00)
   Bytes 29-30  - CRC16-CCITT (Little Endian)
   Byte 31      - XOR_ALL Checksum

4. PACKET STRUCTURE BC -> MSB (TRANSMIT - 32 bytes)
   Byte 0       - 0x55 (Header)
   Byte 1       - BC Control Flags:
                  [0] ENA_SHOOTING     : Enable Shooting
                  [1] GMEE             : Rocket Elevation Output
                  [2] RANGE_OVER_1280  : Range > 1280 m
                  [3] UOI              : UOI Signal Active
                  [4] INHIBIT_SHOOTING : Inhibit Shooting
                  [5] WIND_SENSOR_ON   : Enable Wind Sensor
                  [6] BC_ON            : BC operating (drives P22 discrete)
                  [7] BC_READY         : BC ready   (drives P23 discrete)
   Bytes 2..28  - Reserved (0x00)
   Bytes 29-30  - CRC16-CCITT (Little Endian)
   Byte 31      - XOR_ALL Checksum

5. AUTOMATION & TRANSMIT MODES
   Auto-Reply on MSB Packet - reply with a BC packet after every valid MSB packet
   Auto-Set Range > 1280m   - bit [2] follows the received distance automatically
   Send on Change           - any command click sends the packet immediately
   Async TX + Period (ms)   - autonomous sender: BC packet every N ms independently
                              of MSB traffic (Period field is in the left panel)
   Both Auto-Reply and Async TX may run together (~2x traffic, packets identical).

6. RECEIVED FLAGS INDICATION
   MSB input flags are shown as read-only LED indicators (green = 1, dark = 0),
   not checkboxes. RX side never affects the transmitted packet.
================================================================================
"""

HELP_RU = """ИМИТАТОР БОРТОВОГО ВЫЧИСЛИТЕЛЯ (БЦ) ДЛЯ ПЛАТЫ МСБ - СПРАВКА
================================================================================

1. ПРИНЦИП РАБОТЫ (Режим ответа на приём)
   Плата МСБ является ведущей по времени и отправляет кадры (0xAA) каждые 20 мс (50 Гц).
   Имитатор БЦ принимает пакет от МСБ, декодирует дальность, тип снаряда и 15 флагов,
   и АВТОМАТИЧЕСКИ отправляет ответный кадр команд БЦ (0x55) в плату МСБ.

2. СТРУКТУРА ПРИЕМА (МСБ -> БЦ, 32 байта, Заголовок 0xAA)
   Байты 1..2   - Дальность (1 LSB = 5 м, принудительно 0 когда СРД=0)
   Байт 3       - Тип снаряда (0=НЕТ, 1=БОПС/Б, 2=КС/К, 3=ОФС/О, 4=Пулемет/П, 5=УР/У)
   Байт 4       - Флаги 1 (Дубль, ЦУ, СРД/JK, БЦ_ВКЛ, Ракета, ДВ_РАЗР, Схема совмещения)
   Байт 5       - Флаги 2 (К1, Выстрел пушка, Сброс фильтров, Расстопоривание, Превышение...)
   Байты 29-30  - CRC16-CCITT
   Байт 31      - XOR_ALL

3. СТРУКТУРА ОТВЕТА (БЦ -> МСБ, 32 байта, Заголовок 0x55)
   Байт 1       - Команды управления:
                  [0] ENA_SHOOTING     : Разрешение стрельбы
                  [1] GMEE             : Превышение для ракеты
                  [2] RANGE_OVER_1280  : Дальность больше 1280 м
                  [3] UOI              : Сигнал УОИ
                  [4] INHIBIT_SHOOTING : Запрет стрельбы
                  [5] WIND_SENSOR_ON   : Включение датчика ветра
                   [6] BC_ON            : БЦ работает (дискрет P22)
                   [7] BC_READY         : БЦ готов (дискрет P23)

4. НАСТРОЙКИ UART (левая панель)
   COM Port  - порт, подключённый к линии RS-485 платы МСБ
   Baudrate  - выбираемая 9600..921600 (железо требует 921600)
   Parity    - выбираемая None/Even/Odd (железо требует Even)
   Data bits - выбираемые 5..8 (железо требует 8)
   Stop bits - выбираемые 1/1.5/2 (железо требует 1)
   Period,мс - период таймера Async TX, 10..1000 мс (по умолч. 20 = 50 Гц)

5. РЕЖИМЫ ОТПРАВКИ (Automation)
   Auto-Reply            - отвечать пакетом БЦ на каждый принятый кадр МСБ
   Auto-Set Range>1280   - бит [2] повторяет принятую дальность автоматически
   Send on Change        - любое нажатие на команду сразу отправляет пакет
   Async TX + Period     - автономный отправитель: кадр БЦ каждые N мс независимо
                           от трафика МСБ (поле Period - в левой панели)
   Оба режима можно включать вместе (трафик x2, пакеты идентичны).

6. ИНДИКАЦИЯ ПРИНЯТЫХ ФЛАГОВ
   Флаги входа МСБ показаны светодиодными индикаторами (зелёный = 1, тёмный = 0),
   это не чекбоксы. Приём никак не влияет на отправляемый пакет.
================================================================================
"""

class BCSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Ballistic Computer (BC) Simulator for MSB Board v1.6")
        self.root.minsize(1100, 720)
        
        self.settings_file = os.path.join(APP_DIR, "bc_msb_simulator_settings.json")
        self.log_file = os.path.join(APP_DIR, "bc_msb_log.txt")
        
        # Serial connection
        self.serial_conn = None
        self.is_connected = False
        self.rx_thread = None
        
        # Diagnostic Counters
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
        
        # Start Bytes
        self.start_byte_tx_var = tk.StringVar(value="0x55") # BC -> MSB
        self.start_byte_rx_var = tk.StringVar(value="0xAA") # MSB -> BC
        
        # Transmit Control Commands (BC -> MSB)
        self.cmd_ena_shooting = tk.BooleanVar(value=False)
        self.cmd_gmee = tk.BooleanVar(value=False)
        self.cmd_range_over_1280 = tk.BooleanVar(value=False)
        self.cmd_uoi = tk.BooleanVar(value=False)
        self.cmd_inhibit_shooting = tk.BooleanVar(value=False)
        self.cmd_wind_sensor_on = tk.BooleanVar(value=False)
        self.cmd_bc_on = tk.BooleanVar(value=False)
        self.cmd_bc_ready = tk.BooleanVar(value=False)
        
        self.auto_reply_var = tk.BooleanVar(value=True)
        self.auto_range_calc_var = tk.BooleanVar(value=True)
        self.send_on_change = tk.BooleanVar(value=True)
        
        # Asynchronous autonomous transmit (independent of MSB traffic)
        self.async_tx_var = tk.BooleanVar(value=False)
        self.async_tx_period_var = tk.StringVar(value="20")
        self.async_tx_job = None
        
        # Received Telemetry from MSB (MSB -> BC)
        self.rx_distance_m = tk.StringVar(value="0 m")
        self.rx_ammo_type = tk.StringVar(value="NONE (0)")
        
        # Received Flags Part 1
        self.rx_cc = tk.BooleanVar()
        self.rx_dc = tk.BooleanVar()
        self.rx_srd = tk.BooleanVar()
        self.rx_bc_en = tk.BooleanVar()
        self.rx_rl = tk.BooleanVar()
        self.rx_ws = tk.BooleanVar()
        self.rx_pscc = tk.BooleanVar()
        
        # Received Flags Part 2
        self.rx_k1 = tk.BooleanVar()
        self.rx_btn_cannon = tk.BooleanVar()
        self.rx_rf = tk.BooleanVar()
        self.rx_ur = tk.BooleanVar()
        self.rx_rem = tk.BooleanVar()
        self.rx_df = tk.BooleanVar()
        self.rx_scf_on = tk.BooleanVar()
        self.rx_scf_on_add = tk.BooleanVar()
        
        # Log and GUI Options
        self.log_enabled = tk.BooleanVar(value=True)
        self.log_view_enabled = tk.BooleanVar(value=True)
        self.freeze_view = tk.BooleanVar(value=False)
        self.check_crc_rx_var = tk.BooleanVar(value=True)
        
        # Font settings
        self.log_font_family = tk.StringVar(value="Consolas")
        self.log_font_size = tk.IntVar(value=10)
        
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
        tx_val = self.parse_hex(self.start_byte_tx_var.get(), 0x55)
        self.start_byte_tx_var.set(f"0x{tx_val:02X}")
        rx_val = self.parse_hex(self.start_byte_rx_var.get(), 0xAA)
        self.start_byte_rx_var.set(f"0x{rx_val:02X}")
        self.save_settings()

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

    def build_bc_packet(self):
        data = bytearray(28)
        
        flags = 0
        if self.cmd_ena_shooting.get():     flags |= 0x01
        if self.cmd_gmee.get():             flags |= 0x02
        if self.cmd_range_over_1280.get():  flags |= 0x04
        if self.cmd_uoi.get():              flags |= 0x08
        if self.cmd_inhibit_shooting.get(): flags |= 0x10
        if self.cmd_wind_sensor_on.get():   flags |= 0x20
        if self.cmd_bc_on.get():            flags |= 0x40
        if self.cmd_bc_ready.get():         flags |= 0x80
        
        data[0] = flags
        
        packet = bytearray()
        start_tx = self.parse_hex(self.start_byte_tx_var.get(), 0x55)
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
        if not self.is_connected or not self.serial_conn:
            return
        
        packet = self.build_bc_packet()
        try:
            self.serial_conn.write(packet)
            self.tx_counter += 1
            self.tx_label.configure(text=f"TX (BC->MSB): {self.tx_counter}")
            self.blink_tx_once()
            self.log(f"TX BC->MSB: {packet.hex(' ')}", 'tx')
        except Exception as e:
            self.log(f"Send error: {e}", 'err')
            self.disconnect()

    def on_command_toggle(self):
        if self.send_on_change.get() and self.is_connected:
            self.send_packet()
        self.save_settings()

    def get_async_tx_period_ms(self):
        try:
            period = int(self.async_tx_period_var.get())
        except ValueError:
            period = 20
        period = max(10, min(1000, period))
        self.async_tx_period_var.set(str(period))
        return period

    def on_async_tx_toggle(self):
        # Restart timer so the new state/period takes effect immediately
        if self.async_tx_job is not None:
            self.root.after_cancel(self.async_tx_job)
            self.async_tx_job = None
        if self.async_tx_var.get() and self.is_connected:
            self.schedule_async_tx()
        self.save_settings()

    def schedule_async_tx(self):
        period = self.get_async_tx_period_ms()
        self.async_tx_job = self.root.after(period, self.async_tx_tick)

    def async_tx_tick(self):
        self.async_tx_job = None
        if not (self.async_tx_var.get() and self.is_connected):
            return
        self.send_packet()
        self.schedule_async_tx()

    def process_rx_packet(self, data):
        start_rx = self.parse_hex(self.start_byte_rx_var.get(), 0xAA)
        if len(data) != 32 or data[0] != start_rx:
            return

        # 1. XOR Checksum
        calc_xor = 0
        for i in range(31):
            calc_xor ^= data[i]
        if calc_xor != data[31]:
            self.xor_errors += 1
            self.xor_label.configure(text=f"XOR Errors: {self.xor_errors}")
            self.log(f"RX XOR ERROR: {data.hex(' ')}", 'err')
            return

        # 2. CRC16 Checksum
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
        self.rx_label.configure(text=f"RX (MSB->BC): {self.rx_counter}")
        self.log(f"RX MSB->BC: {data.hex(' ')}", 'rx')

        # 3. Decode Payload
        raw_distance = data[1] | (data[2] << 8)
        dist_m = raw_distance * 5
        self.rx_distance_m.set(f"{dist_m} m ({raw_distance} LSB)")

        if self.auto_range_calc_var.get():
            self.cmd_range_over_1280.set(dist_m > 1280)

        # Ammo Type (Byte 3)
        ammo_id = data[3] & 0x0F
        ammo_names = {0: "NONE (0)", 1: "APDS (1)", 2: "HEAT (2)", 3: "HEF (3)", 4: "MG (4)", 5: "GM (5)"}
        self.rx_ammo_type.set(ammo_names.get(ammo_id, f"UNKNOWN ({ammo_id})"))

        # Flags 1 (Byte 4)
        f1 = data[4]
        self.rx_cc.set(bool(f1 & 0x01))
        self.rx_dc.set(bool(f1 & 0x02))
        self.rx_srd.set(bool(f1 & 0x04))
        self.rx_bc_en.set(bool(f1 & 0x08))
        self.rx_rl.set(bool(f1 & 0x10))
        self.rx_ws.set(bool(f1 & 0x20))
        self.rx_pscc.set(bool(f1 & 0x40))

        # Flags 2 (Byte 5)
        f2 = data[5]
        self.rx_k1.set(bool(f2 & 0x01))
        self.rx_btn_cannon.set(bool(f2 & 0x02))
        self.rx_rf.set(bool(f2 & 0x04))
        self.rx_ur.set(bool(f2 & 0x08))
        self.rx_rem.set(bool(f2 & 0x10))
        self.rx_df.set(bool(f2 & 0x20))
        self.rx_scf_on.set(bool(f2 & 0x40))
        self.rx_scf_on_add.set(bool(f2 & 0x80))
        self.update_rx_leds()

        # 4. Immediate Auto-Response
        if self.auto_reply_var.get():
            self.send_packet()

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
                        start_rx = self.parse_hex(self.start_byte_rx_var.get(), 0xAA)
                            
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

    def setup_gui(self):
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # ========== LEFT PANEL: UART SETTINGS ==========
        left_frame = ttk.LabelFrame(main_paned, text="UART Settings (BC Mode)", padding="10")
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
        period_entry = ttk.Entry(left_frame, textvariable=self.async_tx_period_var, width=12)
        period_entry.pack(anchor=tk.W, pady=(0,10))
        period_entry.bind('<FocusOut>', lambda e: (self.get_async_tx_period_ms(), self.save_settings()))
        
        self.connect_btn = ttk.Button(left_frame, text="Connect", command=self.toggle_connection)
        self.connect_btn.pack(anchor=tk.W, pady=(5,5))
        
        status_frame = ttk.Frame(left_frame)
        status_frame.pack(anchor=tk.W, pady=(5,0))
        self.conn_indicator = tk.Canvas(status_frame, width=20, height=7, highlightthickness=0)
        self.conn_indicator.create_rectangle(0, 0, 20, 7, fill='red', outline='', tags='rect')
        self.conn_indicator.pack(side=tk.LEFT, padx=(0,5))
        self.conn_label = ttk.Label(status_frame, text="Disconnected")
        self.conn_label.pack(side=tk.LEFT)
        
        # TX/RX Indicators
        tx_frame = ttk.Frame(left_frame)
        tx_frame.pack(anchor=tk.W, pady=(15,2))
        self.tx_indicator = tk.Canvas(tx_frame, width=20, height=7, highlightthickness=0)
        self.tx_indicator.create_rectangle(0, 0, 20, 7, fill='gray', outline='', tags='rect')
        self.tx_indicator.pack(side=tk.LEFT, padx=(0,5))
        ttk.Label(tx_frame, text="TX (BC->MSB)").pack(side=tk.LEFT)
        
        rx_frame = ttk.Frame(left_frame)
        rx_frame.pack(anchor=tk.W, pady=(2,0))
        self.rx_indicator = tk.Canvas(rx_frame, width=20, height=7, highlightthickness=0)
        self.rx_indicator.create_rectangle(0, 0, 20, 7, fill='gray', outline='', tags='rect')
        self.rx_indicator.pack(side=tk.LEFT, padx=(0,5))
        ttk.Label(rx_frame, text="RX (MSB->BC)").pack(side=tk.LEFT)
        
        # HELP BUTTON
        ttk.Button(left_frame, text="HELP", command=self.show_help).pack(anchor=tk.W, pady=(20,0))
        
        # ========== CENTER PANEL: COMMANDS BC -> MSB (TRANSMIT) ==========
        center_frame = ttk.LabelFrame(main_paned, text="Ballistic Computer Commands (BC -> MSB)", padding="10")
        main_paned.add(center_frame, weight=1)
        
        cmd_group = ttk.LabelFrame(center_frame, text="Active Control Flags (Byte 1)", padding="10")
        cmd_group.pack(fill=tk.X, pady=(0,10))
        
        ttk.Checkbutton(cmd_group, text="[0] ENA_SHOOTING (Enable shooting)", variable=self.cmd_ena_shooting, command=self.on_command_toggle).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(cmd_group, text="[1] GMEE (Rocket elevation)", variable=self.cmd_gmee, command=self.on_command_toggle).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(cmd_group, text="[2] RANGE_OVER_1280 (Range > 1280 m)", variable=self.cmd_range_over_1280, command=self.on_command_toggle).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(cmd_group, text="[3] UOI (UOI signal active)", variable=self.cmd_uoi, command=self.on_command_toggle).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(cmd_group, text="[4] INHIBIT_SHOOTING (Inhibit shooting)", variable=self.cmd_inhibit_shooting, command=self.on_command_toggle).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(cmd_group, text="[5] WIND_SENSOR_ON (Wind sensor on)", variable=self.cmd_wind_sensor_on, command=self.on_command_toggle).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(cmd_group, text="[6] BC_ON (BC operating, discrete P22)", variable=self.cmd_bc_on, command=self.on_command_toggle).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(cmd_group, text="[7] BC_READY (BC ready, discrete P23)", variable=self.cmd_bc_ready, command=self.on_command_toggle).pack(anchor=tk.W, pady=2)
        
        opt_group = ttk.LabelFrame(center_frame, text="Automation & Transmit Modes", padding="10")
        opt_group.pack(fill=tk.X, pady=(0,10))
        
        ttk.Checkbutton(opt_group, text="Auto-Reply on MSB Packet (Hardware Master Mode)", variable=self.auto_reply_var, command=self.save_settings).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(opt_group, text="Auto-Set 'Range > 1280m' based on received distance", variable=self.auto_range_calc_var, command=self.save_settings).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(opt_group, text="Send on Change (Immediate TX upon click)", variable=self.send_on_change, command=self.save_settings).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(opt_group, text="Async TX: send BC packet by timer (period - left panel)", variable=self.async_tx_var, command=self.on_async_tx_toggle).pack(anchor=tk.W, pady=2)
        
        tx_row = ttk.Frame(center_frame)
        tx_row.pack(fill=tk.X, pady=10)
        
        self.manual_send_btn = ttk.Button(tx_row, text="Send Packet (Manual)", command=self.send_packet, width=20)
        self.manual_send_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Label(tx_row, text="TX Header:").pack(side=tk.LEFT, padx=(10,2))
        tx_hdr_entry = ttk.Entry(tx_row, textvariable=self.start_byte_tx_var, width=6)
        tx_hdr_entry.pack(side=tk.LEFT)
        tx_hdr_entry.bind('<FocusOut>', self.reformat_start_bytes)
        
        ttk.Label(tx_row, text="RX Header:").pack(side=tk.LEFT, padx=(15,2))
        rx_hdr_entry = ttk.Entry(tx_row, textvariable=self.start_byte_rx_var, width=6)
        rx_hdr_entry.pack(side=tk.LEFT)
        rx_hdr_entry.bind('<FocusOut>', self.reformat_start_bytes)
        
        # ========== RIGHT PANEL: RECEIVED TELEMETRY (MSB -> BC) ==========
        right_frame = ttk.LabelFrame(main_paned, text="MSB Board Live Telemetry (RECEIVE)", padding="10")
        main_paned.add(right_frame, weight=1)
        
        # Distance & Ammo Box
        tel_header_frame = ttk.Frame(right_frame)
        tel_header_frame.pack(fill=tk.X, pady=(0,5))
        
        dist_box = ttk.LabelFrame(tel_header_frame, text="Distance", padding="5")
        dist_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,2))
        self.dist_lbl = ttk.Label(dist_box, textvariable=self.rx_distance_m, font=('TkDefaultFont', 11, 'bold'))
        self.dist_lbl.pack()
        
        ammo_box = ttk.LabelFrame(tel_header_frame, text="Ammunition Type", padding="5")
        ammo_box.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(2,0))
        self.ammo_lbl = ttk.Label(ammo_box, textvariable=self.rx_ammo_type, font=('TkDefaultFont', 11, 'bold'))
        self.ammo_lbl.pack()
        
        # Flags Part 1 & 2 Received (LED indicators, read-only)
        flags_rx_container = ttk.Frame(right_frame)
        flags_rx_container.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.rx_led_rows = []
        
        f1_rx_frame = ttk.LabelFrame(flags_rx_container, text="Flags Part 1 (Byte 4)", padding="5")
        f1_rx_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,2))
        
        for text, var in [
            ("CC (duplicate)", self.rx_cc),
            ("DC (target designation)", self.rx_dc),
            ("SRD (distance latch JK)", self.rx_srd),
            ("BC_EN (BC enable)", self.rx_bc_en),
            ("RL (rocket launch)", self.rx_rl),
            ("WS (wind sensor)", self.rx_ws),
            ("PSCC (alignment power)", self.rx_pscc),
        ]:
            self.rx_led_rows.append(self.make_led_row(f1_rx_frame, text, var))
            
        f2_rx_frame = ttk.LabelFrame(flags_rx_container, text="Flags Part 2 (Byte 5)", padding="5")
        f2_rx_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(2,0))
        
        for text, var in [
            ("K1 (control)", self.rx_k1),
            ("BTN_CANNON (cannon trigger)", self.rx_btn_cannon),
            ("RF (reset filters)", self.rx_rf),
            ("UR (unlock reticle)", self.rx_ur),
            ("REM (rocket elevation)", self.rx_rem),
            ("DF (DF code)", self.rx_df),
            ("SCF_ON", self.rx_scf_on),
            ("SCF_ON_ADD", self.rx_scf_on_add),
        ]:
            self.rx_led_rows.append(self.make_led_row(f2_rx_frame, text, var))
            
        # Counters
        counters_frame = ttk.LabelFrame(right_frame, text="Diagnostic Counters", padding="5")
        counters_frame.pack(fill=tk.X, pady=5)
        
        ttk.Checkbutton(counters_frame, text="Check RX CRC16", variable=self.check_crc_rx_var, command=self.save_settings).pack(anchor=tk.W)
        self.rx_label = ttk.Label(counters_frame, text=f"RX (MSB->BC): {self.rx_counter}")
        self.rx_label.pack(anchor=tk.W)
        self.tx_label = ttk.Label(counters_frame, text=f"TX (BC->MSB): {self.tx_counter}")
        self.tx_label.pack(anchor=tk.W)
        self.crc_label = ttk.Label(counters_frame, text=f"CRC Errors: {self.crc_errors}")
        self.crc_label.pack(anchor=tk.W)
        self.xor_label = ttk.Label(counters_frame, text=f"XOR Errors: {self.xor_errors}")
        self.xor_label.pack(anchor=tk.W)
        
        ttk.Button(counters_frame, text="Reset Counters", command=self.reset_counters).pack(pady=3)

        # ========== BOTTOM PANEL: EVENT LOG ==========
        log_display_frame = ttk.LabelFrame(self.root, text="Communication Event Log", padding="5")
        log_display_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0,5))
        
        log_btn_frame = ttk.Frame(log_display_frame)
        log_btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_display_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.log_text.tag_configure('tx', background='#90EE90') # Green
        self.log_text.tag_configure('rx', background='#FFF44F') # Yellow
        self.log_text.tag_configure('err', background='#FF9999') # Red
        
        ttk.Checkbutton(log_btn_frame, text="Log View", variable=self.log_view_enabled, command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(log_btn_frame, text="Save Log to File", variable=self.log_enabled, command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(log_btn_frame, text="Freeze View", variable=self.freeze_view, command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(log_btn_frame, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(log_btn_frame, text="Font", command=self.open_font_dialog).pack(side=tk.RIGHT, padx=5)

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

    def update_rx_leds(self):
        for led, var in self.rx_led_rows:
            if var.get():
                led.itemconfig('led', fill='#39FF14')
                led.itemconfig('halo', fill='#0C6B1A', outline='#39FF14')
            else:
                led.itemconfig('led', fill='#333333')
                led.itemconfig('halo', fill='#242424', outline='#4d4d4d')

    def blink_rx_once(self):
        self.rx_indicator.itemconfig('rect', fill='#FFFF00')
        self.root.after(150, lambda: self.rx_indicator.itemconfig('rect', fill='gray'))

    def log(self, message, tag=None):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
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

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        self.log_file_buf = []
        if self.log_enabled.get():
            try:
                with open(self.log_file, 'w', encoding='utf-8') as f: f.write("")
            except: pass

    def reset_counters(self):
        self.tx_counter = 0
        self.rx_counter = 0
        self.crc_errors = 0
        self.xor_errors = 0
        self.tx_label.configure(text=f"TX (BC->MSB): {self.tx_counter}")
        self.rx_label.configure(text=f"RX (MSB->BC): {self.rx_counter}")
        self.crc_label.configure(text=f"CRC Errors: {self.crc_errors}")
        self.xor_label.configure(text=f"XOR Errors: {self.xor_errors}")
        self.log("Counters reset", 'rx')

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        current_ports = [p.device for p in ports]
        self.port_combo['values'] = current_ports
        if current_ports and not self.port_var.get():
            self.port_var.set(current_ports[0])

    def toggle_connection(self):
        if not self.is_connected: self.connect()
        else: self.disconnect()

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
            self.serial_conn = serial.Serial(port=port, baudrate=baudrate, parity=parity, bytesize=int(self.databits_var.get()), stopbits=stopbits, timeout=1)
            self.is_connected = True
            self.connect_btn.configure(text="Disconnect")
            self.conn_indicator.itemconfig('rect', fill='#00FF00')
            self.conn_label.configure(text="Connected")
            self.port_combo.configure(state='disabled')
            
            self.rx_thread = threading.Thread(target=self.receive_data, daemon=True)
            self.rx_thread.start()
            if self.async_tx_var.get():
                self.schedule_async_tx()
            parity_letter = {"None": "N", "Even": "E", "Odd": "O"}.get(self.parity_var.get(), "?")
            self.log(f"Connected to MSB on {port} @ {baudrate} {self.databits_var.get()}{parity_letter}{self.stopbits_var.get()}", 'rx')
            self.save_settings()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.disconnect()

    def disconnect(self):
        if self.async_tx_job is not None:
            self.root.after_cancel(self.async_tx_job)
            self.async_tx_job = None
        if self.serial_conn and self.is_connected:
            try: self.serial_conn.close()
            except: pass
        self.serial_conn = None
        self.is_connected = False
        self.connect_btn.configure(text="Connect")
        self.conn_indicator.itemconfig('rect', fill='red')
        self.conn_label.configure(text="Disconnected")
        self.port_combo.configure(state='normal')
        self.tx_indicator.itemconfig('rect', fill='gray')
        self.rx_indicator.itemconfig('rect', fill='gray')
        self.log("Disconnected", 'rx')
        self.save_settings()

    def show_help(self):
        help_window = tk.Toplevel(self.root)
        help_window.title("HELP / СПРАВКА - BC Simulator")
        help_window.geometry("1000x750")
        help_window.transient(self.root)
        help_window.grab_set()
        
        help_window.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 1000) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 750) // 2
        help_window.geometry(f"+{x}+{y}")
        
        help_font = tkfont.Font(family=self.log_font_family.get(), size=self.log_font_size.get())
        help_text = scrolledtext.ScrolledText(help_window, wrap=tk.WORD, font=help_font)
        help_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        help_text.insert("1.0", HELP_EN + "\n\n" + HELP_RU)
        help_text.configure(state='disabled')
        
        ttk.Button(help_window, text="Close", command=help_window.destroy).pack(pady=10)

    def update_widget_tree_font(self, parent, new_font):
        try: parent.configure(font=new_font)
        except tk.TclError: pass
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
            style.configure('TLabelframe.Label', font=new_font)
            self.update_widget_tree_font(self.root, new_font)
            self.save_settings()
        except Exception as e:
            messagebox.showerror("Font Error", str(e))

    def open_font_dialog(self):
        font_win = tk.Toplevel(self.root)
        font_win.title("Font Settings")
        font_win.geometry("450x400")
        font_win.resizable(True, True)
        font_win.transient(self.root)
        font_win.grab_set()
        
        main_frame = ttk.Frame(font_win, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
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
            try: preview_label.configure(font=tkfont.Font(family=family_var.get(), size=size_var.get()))
            except: pass

        family_var.trace_add('write', update_preview)
        size_var.trace_add('write', update_preview)
        update_preview()
        
        def apply_font():
            self.apply_new_font((family_var.get(), size_var.get()))
            font_win.destroy()

        ttk.Button(btn_frame, text="Apply (OK)", command=apply_font).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=font_win.destroy).pack(side=tk.RIGHT, padx=5)

    def save_settings(self):
        try:
            settings = {
                "port": self.port_var.get(),
                "baudrate": self.baud_var.get(),
                "parity": self.parity_var.get(),
                "databits": self.databits_var.get(),
                "stopbits": self.stopbits_var.get(),
                "start_byte_tx": self.start_byte_tx_var.get(),
                "start_byte_rx": self.start_byte_rx_var.get(),
                "auto_reply": self.auto_reply_var.get(),
                "auto_range_calc": self.auto_range_calc_var.get(),
                "send_on_change": self.send_on_change.get(),
                "async_tx": self.async_tx_var.get(),
                "async_tx_period": self.async_tx_period_var.get(),
                "check_crc_rx": self.check_crc_rx_var.get(),
                "cmd_ena_shooting": self.cmd_ena_shooting.get(),
                "cmd_gmee": self.cmd_gmee.get(),
                "cmd_range_over_1280": self.cmd_range_over_1280.get(),
                "cmd_uoi": self.cmd_uoi.get(),
                "cmd_inhibit_shooting": self.cmd_inhibit_shooting.get(),
                "cmd_wind_sensor_on": self.cmd_wind_sensor_on.get(),
                "cmd_bc_on": self.cmd_bc_on.get(),
                "cmd_bc_ready": self.cmd_bc_ready.get(),
                "log_enabled": self.log_enabled.get(),
                "log_view_enabled": self.log_view_enabled.get(),
                "freeze_view": self.freeze_view.get(),
                "font_family": self.log_font_family.get(),
                "font_size": self.log_font_size.get(),
                "window_geometry": self.root.geometry(),
                "tx_counter": self.tx_counter,
                "rx_counter": self.rx_counter,
                "crc_errors": self.crc_errors,
                "xor_errors": self.xor_errors
            }
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    s = json.load(f)
                if "port" in s: self.port_var.set(s["port"])
                if "baudrate" in s: self.baud_var.set(str(s["baudrate"]))
                if "parity" in s: self.parity_var.set(s["parity"])
                if "databits" in s: self.databits_var.set(str(s["databits"]))
                if "stopbits" in s: self.stopbits_var.set(str(s["stopbits"]))
                if "start_byte_tx" in s: self.start_byte_tx_var.set(s["start_byte_tx"])
                if "start_byte_rx" in s: self.start_byte_rx_var.set(s["start_byte_rx"])
                if "auto_reply" in s: self.auto_reply_var.set(s["auto_reply"])
                if "auto_range_calc" in s: self.auto_range_calc_var.set(s["auto_range_calc"])
                if "send_on_change" in s: self.send_on_change.set(s["send_on_change"])
                if "async_tx" in s: self.async_tx_var.set(s["async_tx"])
                if "async_tx_period" in s: self.async_tx_period_var.set(str(s["async_tx_period"]))
                if "check_crc_rx" in s: self.check_crc_rx_var.set(s["check_crc_rx"])
                
                # Загрузка команд БЦ
                if "cmd_ena_shooting" in s: self.cmd_ena_shooting.set(s["cmd_ena_shooting"])
                if "cmd_gmee" in s: self.cmd_gmee.set(s["cmd_gmee"])
                if "cmd_range_over_1280" in s: self.cmd_range_over_1280.set(s["cmd_range_over_1280"])
                if "cmd_uoi" in s: self.cmd_uoi.set(s["cmd_uoi"])
                if "cmd_inhibit_shooting" in s: self.cmd_inhibit_shooting.set(s["cmd_inhibit_shooting"])
                if "cmd_wind_sensor_on" in s: self.cmd_wind_sensor_on.set(s["cmd_wind_sensor_on"])
                if "cmd_bc_on" in s: self.cmd_bc_on.set(s["cmd_bc_on"])
                if "cmd_bc_ready" in s: self.cmd_bc_ready.set(s["cmd_bc_ready"])
                
                # Загрузка опций лога
                if "log_enabled" in s: self.log_enabled.set(s["log_enabled"])
                if "log_view_enabled" in s: self.log_view_enabled.set(s["log_view_enabled"])
                if "freeze_view" in s: self.freeze_view.set(s["freeze_view"])
                
                # Загрузка положения окна
                if "window_geometry" in s and s["window_geometry"]:
                    try:
                        self.root.geometry(s["window_geometry"])
                    except: pass

                if "font_family" in s and "font_size" in s:
                    new_f = (s["font_family"], s["font_size"])
                    self.apply_new_font(new_f)
            except Exception:
                pass

def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    root = tk.Tk()
    app = BCSimulator(root)
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