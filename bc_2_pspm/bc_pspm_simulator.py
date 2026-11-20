import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import font as tkfont
import serial
import serial.tools.list_ports
import threading
import time
from datetime import datetime
from collections import deque
import json
import os
import sys
import struct
import ctypes

# Определение реальной папки программы (работает и в .py, и в .exe)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ================================================================================
# HELP TEXTS
# ================================================================================
HELP_EN = """BALLISTIC COMPUTER (BC) SIMULATOR FOR PSPM BOARD - SPECIFICATION
================================================================================

1. OPERATION PRINCIPLE (Hardware Master Mode, 400 Hz)
   The hardware PSPM board is the timing master: it transmits telemetry packets
   (Start: 0xAA) every 2.5 ms (400 Hz). This simulator listens for PSPM packets,
   validates CRC16 & XOR, decodes all telemetry values, and IMMEDIATELY replies
   with a 32-byte BC command packet (Start: 0x55) carrying 10 DAC setpoints.
   Parsing and auto-reply run in the RX thread so the 400 Hz line rate is kept;
   the GUI refreshes at 20 Hz and MUST not slow the link.

2. UART SETTINGS (Left Panel)
   COM Port     - Serial port connected to PSPM USART2 (RS-485 line)
   Baudrate     - Hardware requires 921600
   Parity       - Hardware requires Even
   Data bits    - Hardware requires 8
    Stop bits    - Hardware requires 1
    NOTE: this simulator is SLAVE by design: it answers each PSPM packet
    immediately (Auto-Reply). There is no independent TX timer.

3. PACKET PSPM -> BC (RECEIVE, 32 bytes, header 0xAA)
   Byte 0       - 0xAA
   Bytes 1..2   - ERR_EL     elevation error  +-400 arcmin (1 LSB = 400/32768)
   Bytes 2..3   - ERR_EL_10  elevation x10     +-40 arcmin
   Bytes 4..5   - ERR_AZ     azimuth error     +-400 arcmin
   Bytes 6..7   - ERR_AZ_10  azimuth x10       +-40 arcmin
   Bytes 8..9   - W_EL       elev. rate        +-5 deg/s   (from DA21/DA22 inputs)
   Bytes 10..11 - W_AZ       azim. rate        +-5 deg/s
   Bytes 12..13 - GUN_POS    gun position      +-15 deg
   Bytes 14..15 - ROLL       hull roll BAM16   +-180 deg
   Bytes 16..17 - PITCH      hull pitch BAM16  +-180 deg
   Bytes 18..19 - V_TANK     tank speed        +-20 m/s
   Bytes 20..21 - V_WIND     crosswind         +-25 m/s
   Bytes 22..23 - COS_FI     turret cosine     -1.0..+1.0
   Bytes 24..25 - P_A        pressure (uint16) 0..1500 mmHg (0 = fault sentinel)
   Byte 26      - STATUS: [0] GLOBAL [1] ADC [2] FPGA [3] BMP280 PRESSURE ERROR
   Byte 27      - Reserved
   Bytes 29-30  - CRC16-CCITT (little endian), Byte 31 - XOR_ALL

4. PACKET BC -> PSPM (TRANSMIT, 32 bytes, header 0x55)
   Bytes 1..20  - 10 x int16 DAC setpoints (little endian):
                  1 ASEL_A     Elevation AC      6 SCALE_GPS
                  2 ASEL_D     Elevation DC      7 ADJ_0_ALPHA
                  3 ASAZ_A     Azimuth AC        8 SCALE_ASAZ
                  4 ASAZ_D     Azimuth DC        9 SCALE_HPS
                  5 SCALE_ASEL Elevation scale  10 ADJ_0_BETA
   Bytes 21..28 - Reserved (0x00)
   Bytes 29-30  - CRC16-CCITT, Byte 31 - XOR_ALL
   NOTE: while the PSPM internal DAC debug generator is active (terminal
   DEBUG -> DAC debug gen), PSPM IGNORES BC DAC writes by design.

5. 400 Hz PERFORMANCE NOTES
   - Auto-Reply mirrors every valid PSPM packet (target RX rate ~400 Hz).
   - "Log every packet" is OFF by default: 400+400 lines/s flood the GUI.
   - RX/TX indicators flash once per valid packet (yellow RX / green TX,
     150 ms blanking), same behavior as the PSPM simulator.
   - Rate meter shows measured RX/TX packets per second (expect ~400/400).
   - Validation order mirrors PSPM firmware: CRC16 first, then XOR_ALL.

6. RX STATUS LEDS
   GLOBAL / ADC / FPGA / BMP280 ERROR lamps copy PSPM status byte D[26].
   P_A = 0 mmHg with BMP280 lamp lit = pressure sensor fault sentinel.

7. BUILT-IN OSCILLOSCOPE (under the telemetry table)
   Strip-chart scope for ANY received PSPM signal, values decoded to
   physical units (arcmin, deg/s, deg, m/s, mmHg):
   - Signal   - ERR_EL/ERR_EL10/ERR_AZ/ERR_AZ10, W_EL/W_AZ, GUN_POS, ROLL,
                PITCH, V_TANK, V_WIND, COS_FI, P_A, STATUS.
   - Time/div - 0.25 / 0.5 / 1 / 2 / 5 s per division (8 divisions visible).
   - Freeze / Clear; per-division value and time tick labels, autoscale Y
     with 8% margin, header shows units per division.
   Sampling runs in the RX thread at the true packet rate (up to 400 Hz),
   buffer 8000 samples (~20 s). Tip: select the signal the PSPM generator
   targets to watch its waveform live. P_A is flat at 0 while the BMP280
   ERROR sentinel is active (pressure fault) - this is correct behavior.
================================================================================
"""

HELP_RU = """ИМИТАТОР БОРТОВОГО ВЫЧИСЛИТЕЛЯ (БЦ) ДЛЯ ПЛАТЫ PSPM - СПРАВКА
================================================================================

1. ПРИНЦИП РАБОТЫ (Ведущий - железо, 400 Гц)
   Плата PSPM ведущая по времени: шлёт телеметрию (0xAA) каждые 2,5 мс (400 Гц).
   Имитатор БЦ принимает пакеты, проверяет CRC16 и XOR, декодирует телеметрию
   и МГНОВЕННО отвечает 32-байтным пакетом команд (0x55) с 10 устаовками ЦАП.
   Разбор и автоответ работают в потоке приёма, чтобы держать линию 400 Гц;
   GUI обновляется 20 раз/с и не должен тормозить обмен.

2. НАСТРОЙКИ UART (левая панель)
    COM Port - порт линии RS-485 платы PSPM; скорость 921600, чётность Even,
    8N1 (жестко задано железом). Симулятор - ведомый: отвечает на каждый
    пакет платы мгновенно, независимого таймера передачи нет.

3. ПАКЕТ PSPM -> БЦ (ПРИЁМ, 32 байта, 0xAA)
   Байты 1..27 - ERR_EL, ERR_EL_10, ERR_AZ, ERR_AZ_10 (угл.мин), W_EL, W_AZ
   (±5°/с с входов DA21/DA22), GUN_POS (±15°), ROLL/PITCH корпуса (BAM16),
   V_TANK (±20 м/с), V_WIND (±25 м/с), COS_FI, P_A (мм рт.ст., 0 = авария),
   СТАТУС D[26]: [0]GLOBAL [1]ADC [2]FPGA [3]BMP280. CRC16 + XOR_ALL.

4. ПАКЕТ БЦ -> PSPM (ПЕРЕДАЧА, 32 байта, 0x55)
   Байты 1..20 - 10 x int16 уставок ЦАП:
   1 ASEL_A, 2 ASEL_D, 3 ASAZ_A, 4 ASAZ_D, 5 SCALE_ASEL, 6 SCALE_GPS,
   7 ADJ_0_ALPHA, 8 SCALE_ASAZ, 9 SCALE_HPS, 10 ADJ_0_BETA.
   ВНИМАНИЕ: пока во внутреннем генераторе PSPM (терминал DEBUG -> DAC debug
   gen) включён режим, плата СПРАВЕДЛИВО игнорирует уставки БЦ.

5. ОСОБЕННОСТИ 400 Гц
   - Auto-Reply отвечает на каждый принятый пакет (RX ~400 Гц).
   - «Log every packet» по умолчанию ВЫКЛ: 800 строк/с подвешают GUI.
   - Индикаторы RX/TX вспыхивают на каждый принятый/отправленный пакет
     (жёлтый RX / зелёный TX, гашение 150 мс), как в симуляторе PSPM.
   - Счётчик частоты показывает измеренные пакеты/с (ожидается ~400/400).
   - Порядок проверки как в прошивке: сначала CRC16, затем XOR_ALL.

6. СВЕТОДИОДЫ СТАТУСА
   GLOBAL / ADC / FPGA / BMP280 ERROR копируют байт D[26].
   P_A = 0 при горящем BMP280 - сентинель аварии датчика давления.

7. ВСТРОЕННЫЙ ОСЦИЛЛОГРАФ (под таблицей телеметрии)
   Стрип-диаграмма ЛЮБОГО принятого сигнала PSPM в физических единицах
   (угл. мин, град/с, градусы, м/с, мм рт. ст.):
   - Signal   - ERR_EL/ERR_EL10/ERR_AZ/ERR_AZ10, W_EL/W_AZ, GUN_POS, ROLL,
                PITCH, V_TANK, V_WIND, COS_FI, P_A, STATUS.
   - Time/div - 0.25 / 0.5 / 1 / 2 / 5 с на деление (видно 8 делений).
   - Freeze / Clear; подписи цены деления по вертикали и времени по
     горизонтали, автомасштаб Y с запасом 8%, в шапке - единицы на деление.
   Оцифровка идёт в RX-потоке на реальной скорости пакетов (до 400 Гц),
   буфер 8000 отсчётов (~20 с). Совет: выбирай сигнал, который целит
   генератор PSPM, и наблюдай его форму вживую. P_A лежит на нуле, пока
   активен сентинель BMP280 ERROR (авария давления) - это корректно.
================================================================================
"""

DAC_FIELDS = [
    ("1 ASEL_A (Elev AC)", "asel_a"),
    ("2 ASEL_D (Elev DC)", "asel_d"),
    ("3 ASAZ_A (Azim AC)", "asaz_a"),
    ("4 ASAZ_D (Azim DC)", "asaz_d"),
    ("5 SCALE_ASEL (Elev scale)", "scale_asel"),
    ("6 SCALE_GPS (Gun pos scale)", "scale_gps"),
    ("7 ADJ_0_ALPHA (Elev zero)", "adj_0_alpha"),
    ("8 SCALE_ASAZ (Azim scale)", "scale_asaz"),
    ("9 SCALE_HPS (Hatch scale)", "scale_hps"),
    ("10 ADJ_0_BETA (Azim zero)", "adj_0_beta"),
]

DAC_KEYS = [k for _, k in DAC_FIELDS]

# Decoding LSBs mirror fpga_adc.h / rdc.c (single source of truth: firmware)
LSB_ERR_ARCMIN = 400.0 / 32768.0
LSB_ERR10_ARCMIN = 40.0 / 32768.0
LSB_W_DPS = 5.0 / 32768.0
LSB_GUN_POS_DEG = 30.0 / 65536.0
LSB_BAM16_DEG = 360.0 / 65536.0
LSB_V_TANK = 40.0 / 65536.0
LSB_V_WIND = 50.0 / 65536.0
LSB_COS_FI = 2.0 / 65536.0
LSB_P_A_MMHG = 1500.0 / 65536.0

TELEMETRY_ROWS = [
    ("ERR_EL [']", lambda d: f"{d['err_el'] * LSB_ERR_ARCMIN:+.3f} ({d['err_el']})"),
    ("ERR_EL10 [']", lambda d: f"{d['err_el_10'] * LSB_ERR10_ARCMIN:+.4f} ({d['err_el_10']})"),
    ("ERR_AZ [']", lambda d: f"{d['err_az'] * LSB_ERR_ARCMIN:+.3f} ({d['err_az']})"),
    ("ERR_AZ10 [']", lambda d: f"{d['err_az_10'] * LSB_ERR10_ARCMIN:+.4f} ({d['err_az_10']})"),
    ("W_EL [deg/s]", lambda d: f"{d['w_el'] * LSB_W_DPS:+.4f} ({d['w_el']})"),
    ("W_AZ [deg/s]", lambda d: f"{d['w_az'] * LSB_W_DPS:+.4f} ({d['w_az']})"),
    ("GUN_POS [deg]", lambda d: f"{d['gun_pos'] * LSB_GUN_POS_DEG:+.4f} ({d['gun_pos']})"),
    ("ROLL [deg]", lambda d: f"{d['roll'] * LSB_BAM16_DEG:+.3f} ({d['roll']})"),
    ("PITCH [deg]", lambda d: f"{d['pitch'] * LSB_BAM16_DEG:+.3f} ({d['pitch']})"),
    ("V_TANK [m/s]", lambda d: f"{d['v_tank'] * LSB_V_TANK:+.3f} ({d['v_tank']})"),
    ("V_WIND [m/s]", lambda d: f"{d['v_wind'] * LSB_V_WIND:+.3f} ({d['v_wind']})"),
    ("COS_FI", lambda d: f"{d['cos_fi'] * LSB_COS_FI:+.5f} ({d['cos_fi']})"),
    ("P_A [mmHg]", lambda d: f"{d['p_a'] * LSB_P_A_MMHG:.2f} ({d['p_a']})"),
    ("STATUS D[26]", lambda d: f"0x{d['status']:02X}"),
]

# Oscilloscope channels: display label -> (telemetry dict key, LSB scale, unit)
SCOPE_CHANNELS = [
    ("ERR_EL",   'err_el',    LSB_ERR_ARCMIN,  "arcmin"),
    ("ERR_EL10", 'err_el_10', LSB_ERR10_ARCMIN, "arcmin"),
    ("ERR_AZ",   'err_az',    LSB_ERR_ARCMIN,  "arcmin"),
    ("ERR_AZ10", 'err_az_10', LSB_ERR10_ARCMIN, "arcmin"),
    ("W_EL",     'w_el',      LSB_W_DPS,       "deg/s"),
    ("W_AZ",     'w_az',      LSB_W_DPS,       "deg/s"),
    ("GUN_POS",  'gun_pos',   LSB_GUN_POS_DEG, "deg"),
    ("ROLL",     'roll',      LSB_BAM16_DEG,   "deg"),
    ("PITCH",    'pitch',     LSB_BAM16_DEG,   "deg"),
    ("V_TANK",   'v_tank',    LSB_V_TANK,      "m/s"),
    ("V_WIND",   'v_wind',    LSB_V_WIND,      "m/s"),
    ("COS_FI",   'cos_fi',    LSB_COS_FI,      ""),
    ("P_A",      'p_a',       LSB_P_A_MMHG,    "mmHg"),
    ("STATUS",   'status',    1.0,             "bits"),
]
SCOPE_MAP = {name: (key, lsb, unit) for name, key, lsb, unit in SCOPE_CHANNELS}


class BCPSPMSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Ballistic Computer (BC) Simulator for PSPM Board v1.0 (400 Hz)")
        self.root.minsize(1200, 800)

        self.settings_file = os.path.join(APP_DIR, "bc_pspm_simulator_settings.json")
        self.log_file = os.path.join(APP_DIR, "bc_pspm_log.txt")

        # Serial / threading
        self.serial_conn = None
        self.is_connected = False
        self.rx_thread = None
        self.tx_lock = threading.Lock()
        self.stats_lock = threading.Lock()

        # Counters (updated from RX thread, read by GUI tick)
        self.tx_counter = 0
        self.rx_counter = 0
        self.crc_errors = 0
        self.xor_errors = 0
        self.last_rx_ts = 0.0
        self.last_tx_ts = 0.0
        # Rate meter state
        self._rx_at_sample = 0
        self._tx_at_sample = 0
        self._rate_t0 = time.perf_counter()
        self.rx_rate_hz = 0.0
        self.tx_rate_hz = 0.0

        # Latest decoded telemetry (written by RX thread, read by GUI)
        self.latest_tel = None

        # UART parameters
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="921600")
        self.parity_var = tk.StringVar(value="Even")
        self.databits_var = tk.StringVar(value="8")
        self.stopbits_var = tk.StringVar(value="1")

        # Start bytes: BC transmits 0x55, receives 0xAA from PSPM
        self.start_byte_tx_var = tk.StringVar(value="0x55")
        self.start_byte_rx_var = tk.StringVar(value="0xAA")

        # BC -> PSPM DAC setpoints
        self.dac_vars = {k: tk.StringVar(value="0") for k in DAC_KEYS}
        self.dac_codes = {k: 0 for k in DAC_KEYS}
        self.dac_scales = {}

        # Modes
        self.auto_reply_var = tk.BooleanVar(value=True)
        self.send_on_change = tk.BooleanVar(value=True)

        # Log options: per-packet logging is OFF by default at 400 Hz
        self.log_enabled = tk.BooleanVar(value=True)
        self.log_view_enabled = tk.BooleanVar(value=True)
        self.log_every_packet = tk.BooleanVar(value=False)
        self.freeze_view = tk.BooleanVar(value=False)
        self.check_crc_rx_var = tk.BooleanVar(value=True)

        # GUI display queue drained by the 20 Hz tick
        self.display_q = deque(maxlen=2000)

        # Plain-attribute mirrors for the RX thread: Tk variables are NOT
        # thread safe, calling .get() from a worker thread throws
        # RuntimeError under load and silently kills the RX thread.
        # trace_add fires in the GUI thread and refreshes these mirrors.
        self._m_rx_start = 0xAA
        self._m_tx_start = 0x55
        self._m_check_crc = True
        self._m_auto_reply = True
        self._m_log_pkt = False
        self._m_log_view = True
        self._m_log_file = True
        for var, attr in ((self.check_crc_rx_var, '_m_check_crc'),
                          (self.auto_reply_var, '_m_auto_reply'),
                          (self.log_every_packet, '_m_log_pkt'),
                          (self.log_view_enabled, '_m_log_view'),
                          (self.log_enabled, '_m_log_file')):
            var.trace_add('write', lambda *a, v=var, s=attr: setattr(self, s, v.get()))
        self.start_byte_rx_var.trace_add('write', lambda *a: setattr(
            self, '_m_rx_start', self.parse_hex(self.start_byte_rx_var.get(), 0xAA)))
        self.start_byte_tx_var.trace_add('write', lambda *a: setattr(
            self, '_m_tx_start', self.parse_hex(self.start_byte_tx_var.get(), 0x55)))

        # Font settings
        self.log_font_family = tk.StringVar(value="Consolas")
        self.log_font_size = tk.IntVar(value=10)

        # Buffered file logging (flush every 500 ms)
        self.log_file_buf = []

        # Status Vars for LEDs
        self.st_global = tk.BooleanVar()
        self.st_adc = tk.BooleanVar()
        self.st_fpga = tk.BooleanVar()
        self.st_bmp = tk.BooleanVar()

        # Oscilloscope: (perf_counter, raw_code) samples appended by the RX
        # thread at packet rate; deque.append is thread-safe.
        self.scope_buf = deque(maxlen=8000)
        self.scope_ch_var = tk.StringVar(value="ERR_EL")
        self.scope_win_var = tk.StringVar(value="1.0")
        self.scope_pause = tk.BooleanVar(value=False)
        # Thread-safe mirror of the selected telemetry key for the RX thread
        self._m_scope_key = 'err_el'
        self.scope_ch_var.trace_add(
            'write', lambda *a: setattr(self, '_m_scope_key',
                                        SCOPE_MAP.get(self.scope_ch_var.get(), SCOPE_MAP["ERR_EL"])[0]))

        self.setup_gui()
        self.refresh_ports()
        self.load_settings()

        self.root.after(50, self.gui_tick)
        self.root.after(500, self.flush_log_file)
        self.root.after(100, self.scope_redraw)

    # ------------------------------------------------------------------ utils
    def parse_hex(self, val_str, default_val):
        s = str(val_str).strip().lower()
        if s.startswith('0x'): s = s[2:]
        if s.endswith('h'): s = s[:-1]
        s = s.translate(str.maketrans('авсе', 'abce'))
        if not s: return default_val
        try:
            return int(s, 16) & 0xFF
        except ValueError:
            return default_val

    def reformat_start_bytes(self, event=None):
        self.start_byte_tx_var.set(f"0x{self.parse_hex(self.start_byte_tx_var.get(), 0x55):02X}")
        self.start_byte_rx_var.set(f"0x{self.parse_hex(self.start_byte_rx_var.get(), 0xAA):02X}")
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

    # ------------------------------------------------------------- TX packet
    def build_bc_packet(self):
        packet = bytearray()
        packet.append(self._m_tx_start)
        with self.stats_lock:
            codes = [self.dac_codes[k] for k in DAC_KEYS]
        packet.extend(struct.pack('<hhhhhhhhhh', *codes))
        packet.extend(b'\x00' * 8)
        crc = self.calculate_crc16_ccitt(packet)
        packet.append(crc & 0xFF)
        packet.append((crc >> 8) & 0xFF)
        xor_all = 0
        for b in packet:
            xor_all ^= b
        packet.append(xor_all)
        return bytes(packet)

    def send_packet(self, from_thread=False):
        if not self.is_connected or not self.serial_conn:
            return
        packet = self.build_bc_packet()
        try:
            with self.tx_lock:
                self.serial_conn.write(packet)
            with self.stats_lock:
                self.tx_counter += 1
                self.last_tx_ts = time.perf_counter()
            self.root.after(0, self.blink_tx_once)
            if self._m_log_pkt:
                self.queue_log(f"TX BC->PSPM: {packet.hex(' ')}", 'tx')
        except Exception as e:
            self.queue_log(f"Send error: {e}", 'err')
            if not from_thread:
                self.disconnect()

    # ------------------------------------------------------------- RX packet
    def process_rx_packet(self, data, from_thread=True):
        if len(data) != 32 or data[0] != self._m_rx_start:
            return

        # Validation order mirrors PSPM firmware: CRC16 first, then XOR
        if self._m_check_crc:
            calc_crc = self.calculate_crc16_ccitt(data[:29])
            rx_crc = data[29] | (data[30] << 8)
            if calc_crc != rx_crc:
                with self.stats_lock:
                    self.crc_errors += 1
                self.queue_log(f"RX CRC ERROR: {data.hex(' ')}", 'err')
                return

        calc_xor = 0
        for i in range(31):
            calc_xor ^= data[i]
        if calc_xor != data[31]:
            with self.stats_lock:
                self.xor_errors += 1
            self.queue_log(f"RX XOR ERROR: {data.hex(' ')}", 'err')
            return

        with self.stats_lock:
            self.rx_counter += 1
            self.last_rx_ts = time.perf_counter()
        self.root.after(0, self.blink_rx_once)

        try:
            # 12 x int16 (errors/rates/angles/speeds) + uint16 p_a + status byte
            vals = struct.unpack('<hhhhhhhhhhhhHB', data[1:28])
            tel = {
                'err_el': vals[0], 'err_el_10': vals[1], 'err_az': vals[2], 'err_az_10': vals[3],
                'w_el': vals[4], 'w_az': vals[5], 'gun_pos': vals[6], 'roll': vals[7],
                'pitch': vals[8], 'v_tank': vals[9], 'v_wind': vals[10], 'cos_fi': vals[11],
                'p_a': vals[12], 'status': vals[13],
            }
            self.latest_tel = tel
            try:
                self.scope_buf.append((time.perf_counter(), tel[self._m_scope_key]))
            except (KeyError, TypeError):
                pass
        except Exception:
            return

        if self._m_log_pkt:
            self.queue_log(f"RX PSPM->BC: {data.hex(' ')}", 'rx')

        # Auto-Reply: BC mirrors every valid PSPM frame (hardware master mode)
        if from_thread and self._m_auto_reply:
            self.send_packet(from_thread=True)

    def receive_data(self):
        buffer = bytearray()
        while self.is_connected:
            try:
                if self.serial_conn and self.serial_conn.is_open:
                    waiting = self.serial_conn.in_waiting
                    if waiting > 0:
                        buffer.extend(self.serial_conn.read(waiting))
                        start_rx = self._m_rx_start
                        while len(buffer) >= 32:
                            if buffer[0] == start_rx:
                                packet = bytes(buffer[:32])
                                buffer = buffer[32:]
                                self.process_rx_packet(packet)
                            else:
                                buffer.pop(0)
                    else:
                        time.sleep(0.0005)
                else:
                    break
            except Exception as e:
                if self.is_connected:
                    try:
                        self.log_file_buf.append(f"RX thread aborted: {e!r}\n")
                    except Exception:
                        pass
                break

    # ------------------------------------------------------------- GUI
    def create_dac_row(self, parent, label, key):
        f = ttk.Frame(parent)
        f.pack(fill=tk.X, pady=1)
        ttk.Label(f, text=label, width=28).pack(side=tk.LEFT)
        e = ttk.Entry(f, textvariable=self.dac_vars[key], width=9)
        e.pack(side=tk.LEFT, padx=4)
        v = tk.StringVar(value="0")
        lab = ttk.Label(f, textvariable=v, width=10)
        lab.pack(side=tk.LEFT)

        def on_slider(val):
            raw = max(-32768, min(32767, int(float(val))))
            with self.stats_lock:
                self.dac_codes[key] = raw
            self.dac_vars[key].set(str(raw))
            v.set(f"0x{raw & 0xFFFF:04X}")

        def set_code(raw):
            raw = max(-32768, min(32767, int(raw)))
            with self.stats_lock:
                self.dac_codes[key] = raw
            self.dac_vars[key].set(str(raw))
            v.set(f"0x{raw & 0xFFFF:04X}")
            scale.set(raw)
            return raw

        def apply(event=None):
            try:
                raw = int(self.dac_vars[key].get(), 0)
            except ValueError:
                with self.stats_lock:
                    raw = self.dac_codes[key]
            set_code(raw)
            # Send on Change
            if self.send_on_change.get() and self.is_connected:
                self.send_packet()
            self.save_settings()

        # Classic tk.Scale, styled exactly like the pspm_2_bc simulator sliders
        scale = tk.Scale(f, from_=-32768, to=32767, orient=tk.HORIZONTAL,
                         resolution=1, length=160, width=10, sliderlength=10,
                         command=on_slider)
        scale.pack(side=tk.LEFT, padx=6)
        scale.bind('<ButtonRelease-1>', apply)
        self.dac_scales[key] = (scale, v)
        with self.stats_lock:
            init = self.dac_codes[key]
        scale.set(init)
        v.set(f"0x{init & 0xFFFF:04X}")

        e.bind('<Return>', apply)
        e.bind('<FocusOut>', apply)
        return apply

    def setup_gui(self):
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ========== LEFT PANEL ==========
        left_frame = ttk.LabelFrame(main_paned, text="UART Settings (BC Mode)", padding="10")
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
        tx_frame.pack(anchor=tk.W, pady=(15, 2))
        self.tx_indicator = tk.Canvas(tx_frame, width=20, height=7, highlightthickness=0)
        self.tx_indicator.create_rectangle(0, 0, 20, 7, fill='gray', outline='', tags='rect')
        self.tx_indicator.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(tx_frame, text="TX (BC->PSPM)").pack(side=tk.LEFT)

        rx_frame = ttk.Frame(left_frame)
        rx_frame.pack(anchor=tk.W, pady=(2, 0))
        self.rx_indicator = tk.Canvas(rx_frame, width=20, height=7, highlightthickness=0)
        self.rx_indicator.create_rectangle(0, 0, 20, 7, fill='gray', outline='', tags='rect')
        self.rx_indicator.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(rx_frame, text="RX (PSPM->BC)").pack(side=tk.LEFT)

        self.rate_label = ttk.Label(left_frame, text="RX rate: -- Hz | TX rate: -- Hz")
        self.rate_label.pack(anchor=tk.W, pady=(8, 0))

        # Counters live in the LEFT panel: the right telemetry pane clips them
        # vertically when the window is short (greedy telemetry list on top)
        counters_frame = ttk.LabelFrame(left_frame, text="Diagnostics", padding="5")
        counters_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Checkbutton(counters_frame, text="Check RX CRC16", variable=self.check_crc_rx_var,
                        command=self.save_settings).pack(anchor=tk.W)
        ttk.Checkbutton(counters_frame, text="Log every packet (400 Hz!)",
                        variable=self.log_every_packet, command=self.save_settings).pack(anchor=tk.W)
        self.rx_label = ttk.Label(counters_frame, text=f"RX (PSPM->BC): {self.rx_counter}")
        self.rx_label.pack(anchor=tk.W)
        self.tx_label = ttk.Label(counters_frame, text=f"TX (BC->PSPM): {self.tx_counter}")
        self.tx_label.pack(anchor=tk.W)
        self.crc_label = ttk.Label(counters_frame, text=f"CRC Errors: {self.crc_errors}", width=24, anchor='w')
        self.crc_label.pack(anchor=tk.W)
        self.xor_label = ttk.Label(counters_frame, text=f"XOR Errors: {self.xor_errors}", width=24, anchor='w')
        self.xor_label.pack(anchor=tk.W)
        ttk.Button(counters_frame, text="Reset Counters", command=self.reset_counters).pack(pady=3, fill=tk.X)

        ttk.Button(left_frame, text="HELP", command=self.show_help).pack(anchor=tk.W, pady=(15, 0))

        # ========== CENTER PANEL: BC -> PSPM COMMANDS ==========
        center_frame = ttk.LabelFrame(main_paned, text="BC Commands / DAC Setpoints (BC -> PSPM, int16)", padding="10")
        main_paned.add(center_frame, weight=0)

        dac_group = ttk.LabelFrame(center_frame, text="10 DAC channels (dec, hex shown after apply)", padding="5")
        dac_group.pack(fill=tk.X, pady=(0, 8))
        for label, key in DAC_FIELDS:
            self.create_dac_row(dac_group, label, key)

        btn_row = ttk.Frame(center_frame)
        btn_row.pack(fill=tk.X, pady=4)
        ttk.Button(btn_row, text="All DAC = 0", command=self.dac_zero_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="All DAC = +32767", command=lambda: self.dac_set_all(32767)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="All DAC = -32768", command=lambda: self.dac_set_all(-32768)).pack(side=tk.LEFT, padx=2)

        opt_group = ttk.LabelFrame(center_frame, text="Automation & Transmit Modes", padding="5")
        opt_group.pack(fill=tk.X, pady=(4, 4))
        ttk.Checkbutton(opt_group, text="Auto-Reply on PSPM Packet (400 Hz mirror, recommended)",
                        variable=self.auto_reply_var, command=self.save_settings).pack(anchor=tk.W)
        ttk.Checkbutton(opt_group, text="Send on Change (immediate TX on apply)",
                        variable=self.send_on_change, command=self.save_settings).pack(anchor=tk.W)

        tx_row = ttk.Frame(center_frame)
        tx_row.pack(fill=tk.X, pady=8)
        ttk.Button(tx_row, text="Send Packet (Manual)", command=self.send_packet).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(tx_row, text="TX Header:").pack(side=tk.LEFT, padx=(10, 2))
        tx_hdr = ttk.Entry(tx_row, textvariable=self.start_byte_tx_var, width=6)
        tx_hdr.pack(side=tk.LEFT)
        tx_hdr.bind('<FocusOut>', self.reformat_start_bytes)
        ttk.Label(tx_row, text="RX Header:").pack(side=tk.LEFT, padx=(15, 2))
        rx_hdr = ttk.Entry(tx_row, textvariable=self.start_byte_rx_var, width=6)
        rx_hdr.pack(side=tk.LEFT)
        rx_hdr.bind('<FocusOut>', self.reformat_start_bytes)

        # ========== RIGHT PANEL: PSPM LIVE TELEMETRY ==========
        right_frame = ttk.LabelFrame(main_paned, text="PSPM Live Telemetry (RECEIVE @ 400 Hz, value + raw code)", padding="10")
        main_paned.add(right_frame, weight=1)

        tel_frame = ttk.Frame(right_frame)
        tel_frame.pack(fill=tk.BOTH, expand=True)
        self.tel_labels = {}
        for name, fmt in TELEMETRY_ROWS:
            row = ttk.Frame(tel_frame)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=name, width=18).pack(side=tk.LEFT)
            var = tk.StringVar(value="--")
            ttk.Label(row, textvariable=var, font=('Consolas', 10)).pack(side=tk.LEFT)
            self.tel_labels[name] = var

        led_frame = ttk.LabelFrame(right_frame, text="PSPM Status Byte D[26]", padding="5")
        led_frame.pack(fill=tk.X, pady=5)
        self.status_led_rows = [
            self.make_led_row(led_frame, "GLOBAL_ERROR", self.st_global),
            self.make_led_row(led_frame, "ADC_ERROR", self.st_adc),
            self.make_led_row(led_frame, "FPGA_ERROR", self.st_fpga),
            self.make_led_row(led_frame, "BMP280 PRESSURE ERROR", self.st_bmp),
        ]

        # ========== OSCILLOSCOPE (any PSPM telemetry signal, autoscale) ==========
        # Lives under the telemetry table: the scope shows the shape of the
        # very values listed above it.
        scope_group = ttk.LabelFrame(right_frame, text="Oscilloscope (PSPM signals)", padding="5")
        scope_group.pack(fill=tk.X, side=tk.BOTTOM, pady=(4, 0))
        scope_ctrl = ttk.Frame(scope_group)
        scope_ctrl.pack(fill=tk.X)
        ttk.Label(scope_ctrl, text="Signal:").pack(side=tk.LEFT)
        scope_ch = ttk.Combobox(scope_ctrl, textvariable=self.scope_ch_var, width=10,
                                values=[name for name, _, _, _ in SCOPE_CHANNELS], state='readonly')
        scope_ch.pack(side=tk.LEFT, padx=(2, 8))
        scope_ch.bind('<<ComboboxSelected>>', lambda e: self.save_settings())
        ttk.Label(scope_ctrl, text="Time/div:").pack(side=tk.LEFT)
        scope_win = ttk.Combobox(scope_ctrl, textvariable=self.scope_win_var, width=5,
                                 values=["0.25", "0.5", "1.0", "2.0", "5.0"], state='readonly')
        scope_win.pack(side=tk.LEFT, padx=(2, 8))
        scope_win.bind('<<ComboboxSelected>>', lambda e: self.save_settings())
        # Freeze/Clear on their own row so they never clip when the panel shrinks
        scope_ctrl2 = ttk.Frame(scope_group)
        scope_ctrl2.pack(fill=tk.X, pady=(2, 0))
        ttk.Checkbutton(scope_ctrl2, text="Freeze", variable=self.scope_pause).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(scope_ctrl2, text="Clear", width=6,
                   command=self.scope_buf.clear).pack(side=tk.LEFT)
        self.scope_canvas = tk.Canvas(scope_group, height=170, bg='#0a0a0a', highlightthickness=1,
                                      highlightbackground='#555555')
        self.scope_canvas.pack(fill=tk.X, pady=(4, 0))
        self.scope_info = ttk.Label(scope_group, text="samples: 0")
        self.scope_info.pack(anchor=tk.W)

        # ========== BOTTOM: LOG ==========
        log_display_frame = ttk.LabelFrame(self.root, text="Communication Event Log", padding="5")
        log_display_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        log_btn_frame = ttk.Frame(log_display_frame)
        log_btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_display_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.log_text.tag_configure('tx', background='#90EE90')
        self.log_text.tag_configure('rx', background='#FFF44F')
        self.log_text.tag_configure('err', background='#FF9999')
        ttk.Checkbutton(log_btn_frame, text="Log View", variable=self.log_view_enabled,
                        command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(log_btn_frame, text="Save Log to File", variable=self.log_enabled,
                        command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(log_btn_frame, text="Freeze View", variable=self.freeze_view,
                        command=self.save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(log_btn_frame, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(log_btn_frame, text="Font", command=self.open_font_dialog).pack(side=tk.RIGHT, padx=5)

    # ------------------------------------------------------- GUI refresh 20 Hz
    def gui_tick(self):
        now = time.perf_counter()
        with self.stats_lock:
            rx_c, tx_c = self.rx_counter, self.tx_counter
            crc_e, xor_e = self.crc_errors, self.xor_errors
        tel = self.latest_tel
        if tel is not None:
            for name, fmt in TELEMETRY_ROWS:
                try:
                    self.tel_labels[name].set(fmt(tel))
                except Exception:
                    pass
            st = tel['status']
            self.st_global.set(bool(st & 0x01))
            self.st_adc.set(bool(st & 0x02))
            self.st_fpga.set(bool(st & 0x04))
            self.st_bmp.set(bool(st & 0x08))
            self.update_status_leds()

        # Drain log display queue (max 50 lines per tick to keep GUI responsive)
        if self.log_view_enabled.get() and not self.freeze_view.get():
            drained = 0
            while self.display_q and drained < 50:
                msg, tag = self.display_q.popleft()
                if tag:
                    self.log_text.insert(tk.END, msg + "\n", tag)
                else:
                    self.log_text.insert(tk.END, msg + "\n")
                drained += 1
            if drained:
                self.log_text.see(tk.END)

        # Counter labels every tick (50 ms) for smooth rolling like pspm_2_bc;
        # rate math stays on the 500 ms sampling window below.
        self.rx_label.configure(text=f"RX (PSPM->BC): {rx_c}")
        self.tx_label.configure(text=f"TX (BC->PSPM): {tx_c}")
        self.crc_label.configure(text=f"CRC Errors: {crc_e}")
        self.xor_label.configure(text=f"XOR Errors: {xor_e}")

        # Rate meter every ~500 ms
        if now - self._rate_t0 >= 0.5:
            dt = now - self._rate_t0
            with self.stats_lock:
                rx_c, tx_c = self.rx_counter, self.tx_counter
            self.rx_rate_hz = (rx_c - self._rx_at_sample) / dt
            self.tx_rate_hz = (tx_c - self._tx_at_sample) / dt
            self._rx_at_sample, self._tx_at_sample = rx_c, tx_c
            self._rate_t0 = now
            self.rate_label.configure(text=f"RX rate: {self.rx_rate_hz:.0f} Hz | TX rate: {self.tx_rate_hz:.0f} Hz")

        self.root.after(50, self.gui_tick)

    # ------------------------------------------------------- LED blink (pspm-style)
    def blink_tx_once(self):
        self.tx_indicator.itemconfig('rect', fill='#00FF00')
        self.root.after(150, lambda: self.tx_indicator.itemconfig('rect', fill='gray'))

    def blink_rx_once(self):
        self.rx_indicator.itemconfig('rect', fill='#FFFF00')
        self.root.after(150, lambda: self.rx_indicator.itemconfig('rect', fill='gray'))

    # ------------------------------------------------------- Oscilloscope redraw
    def scope_redraw(self):
        try:
            if not self.scope_pause.get():
                c = self.scope_canvas
                w, h = c.winfo_width(), c.winfo_height()
                if w > 20 and h > 20:
                    c.delete('all')
                    for i in range(1, 8):
                        x = w * i / 8.0
                        c.create_line(x, 0, x, h, fill='#1f3d1f')
                    for i in range(1, 5):
                        y = h * i / 4.0
                        c.create_line(0, y, w, y, fill='#1f3d1f')

                    now = time.perf_counter()
                    span = float(self.scope_win_var.get())
                    name = self.scope_ch_var.get()
                    key, lsb, unit = SCOPE_MAP.get(name, SCOPE_MAP["ERR_EL"])
                    samples = [(t, v * lsb) for (t, v) in self.scope_buf if now - t <= span]

                    if len(samples) >= 2:
                        vals = [v for _, v in samples]
                        vmin, vmax = min(vals), max(vals)
                        if vmax - vmin < 1e-9:
                            pad = max(abs(vmax) * 0.1, 1.0)
                        else:
                            pad = (vmax - vmin) * 0.08
                        vmin -= pad
                        vmax += pad
                        scale = h / (vmax - vmin)
                        pts = []
                        for t, v in samples:
                            pts.append(w * (1.0 - (now - t) / span))
                            pts.append(h - (v - vmin) * scale)
                        c.create_line(pts, fill='#00ff00')

                        # Per-division tick labels: vertical (value) on each
                        # horizontal gridline, horizontal (time) on each vertical
                        div_v = (vmax - vmin) / 4.0
                        for i in range(5):
                            yv = h * (4 - i) / 4.0
                            val = vmin + div_v * i
                            c.create_text(2, yv, anchor='w', fill='#66aa66',
                                          font=('Consolas', 7), text=f"{val:.4g}")
                        for i in range(9):
                            xt = w * i / 8.0
                            trel = -span * (8 - i) / 8.0
                            anchor = 'w' if i == 0 else ('e' if i == 8 else 'n')
                            c.create_text(xt, h - 1, anchor=anchor, fill='#66aa66',
                                          font=('Consolas', 7), text=f"{trel:+.2f}")
                        c.create_text(w - 2, h - 10, anchor='se', fill='#66aa66',
                                      font=('Consolas', 7), text="s")

                        c.create_text(4, 4, anchor='nw', fill='#00ff00', font=('Consolas', 8),
                                      text=f"{name}: {div_v:.4g} {unit}/div")
                    self.scope_info.configure(
                        text=f"samples: {len(samples)} / window {span} s  "
                             f"(buf {len(self.scope_buf)})")
        finally:
            self.root.after(100, self.scope_redraw)

    # ------------------------------------------------------- helpers
    def queue_log(self, message, tag=None):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        full = f"[{timestamp}] {message}"
        if self._m_log_view:
            self.display_q.append((full, tag))
        if self._m_log_file:
            self.log_file_buf.append(full + "\n")

    def flush_log_file(self):
        if self.log_file_buf:
            if self.log_enabled.get():
                try:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        f.write(''.join(self.log_file_buf[:4000]))
                except Exception:
                    pass
            del self.log_file_buf[:4000]
        self.root.after(500, self.flush_log_file)

    def dac_zero_all(self):
        self.dac_set_all(0)

    def dac_set_all(self, value):
        value = max(-32768, min(32767, int(value)))
        for key in DAC_KEYS:
            self.dac_vars[key].set(str(value))
        with self.stats_lock:
            for key in DAC_KEYS:
                self.dac_codes[key] = value
        self.sync_dac_ui()
        if self.send_on_change.get() and self.is_connected:
            self.send_packet()
        self.save_settings()

    def sync_dac_ui(self):
        for key in DAC_KEYS:
            if key in self.dac_scales:
                scale, hexlab = self.dac_scales[key]
                with self.stats_lock:
                    raw = self.dac_codes[key]
                scale.set(raw)
                hexlab.set(f"0x{raw & 0xFFFF:04X}")

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

    def update_status_leds(self):
        for led, var in self.status_led_rows:
            if var.get():
                led.itemconfig('led', fill='#39FF14')
                led.itemconfig('halo', fill='#0C6B1A', outline='#39FF14')
            else:
                led.itemconfig('led', fill='#333333')
                led.itemconfig('halo', fill='#242424', outline='#4d4d4d')

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        self.log_file_buf.clear()
        if self.log_enabled.get():
            try:
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.write("")
            except Exception:
                pass

    def reset_counters(self):
        with self.stats_lock:
            self.tx_counter = 0
            self.rx_counter = 0
            self.crc_errors = 0
            self.xor_errors = 0
        self.log_message("Counters reset", 'rx')

    def log_message(self, message, tag=None):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if self.log_view_enabled.get() and not self.freeze_view.get():
            if tag:
                self.log_text.insert(tk.END, f"[{timestamp}] {message}\n", tag)
            else:
                self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
        if self.log_enabled.get():
            self.log_file_buf.append(f"[{timestamp}] {message}\n")

    # ------------------------------------------------------- connection
    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        current_ports = [p.device for p in ports]
        self.port_combo['values'] = current_ports
        if current_ports and not self.port_var.get():
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
            parity_map = {"None": serial.PARITY_NONE, "Even": serial.PARITY_EVEN, "Odd": serial.PARITY_ODD}
            stopbits_map = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE, "2": serial.STOPBITS_TWO}
            self.serial_conn = serial.Serial(
                port=port, baudrate=int(self.baud_var.get()),
                parity=parity_map.get(self.parity_var.get(), serial.PARITY_EVEN),
                bytesize=int(self.databits_var.get()),
                stopbits=stopbits_map.get(self.stopbits_var.get(), serial.STOPBITS_ONE),
                timeout=1)
            self.is_connected = True
            self.connect_btn.configure(text="Disconnect")
            self.conn_indicator.itemconfig('rect', fill='#00FF00')
            self.conn_label.configure(text="Connected")
            self.port_combo.configure(state='disabled')
            self.rx_thread = threading.Thread(target=self.receive_data, daemon=True)
            self.rx_thread.start()
            pl = {"None": "N", "Even": "E", "Odd": "O"}.get(self.parity_var.get(), "?")
            self.log_message(f"Connected to PSPM on {port} @ {self.baud_var.get()} {self.databits_var.get()}{pl}{self.stopbits_var.get()} (400 Hz master mode)", 'rx')
            self.save_settings()
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
            self.disconnect()

    def disconnect(self):
        self.is_connected = False
        if self.serial_conn:
            try:
                self.serial_conn.close()
            except Exception:
                pass
        self.serial_conn = None
        self.connect_btn.configure(text="Connect")
        self.conn_indicator.itemconfig('rect', fill='red')
        self.conn_label.configure(text="Disconnected")
        self.port_combo.configure(state='normal')
        self.tx_indicator.itemconfig('rect', fill='gray')
        self.rx_indicator.itemconfig('rect', fill='gray')
        self.log_message("Disconnected", 'rx')
        self.save_settings()

    # ------------------------------------------------------- help/font
    def show_help(self):
        help_window = tk.Toplevel(self.root)
        help_window.title("HELP / СПРАВКА - BC PSPM Simulator")
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

    def update_widget_tree_font(self, parent, new_font):
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
            for cls in ['.', 'TLabel', 'TButton', 'TEntry', 'TCombobox', 'TCheckbutton', 'TLabelframe.Label']:
                style.configure(cls, font=new_font)
            self.update_widget_tree_font(self.root, new_font)
            self.save_settings()
        except Exception as e:
            messagebox.showerror("Font Error", str(e))

    def open_font_dialog(self):
        font_win = tk.Toplevel(self.root)
        font_win.title("Font Settings")
        font_win.geometry("450x400")
        font_win.transient(self.root)
        font_win.grab_set()
        main_frame = ttk.Frame(font_win, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        family_var = tk.StringVar(value=self.log_font_family.get())
        size_var = tk.IntVar(value=self.log_font_size.get())
        font_frame = ttk.Frame(main_frame)
        font_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        ttk.Label(font_frame, text="Font:").pack(side=tk.LEFT, padx=(0, 10))
        fonts = sorted(tkfont.families())
        ttk.Combobox(font_frame, textvariable=family_var, values=fonts, state="readonly", width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)
        size_frame = ttk.Frame(main_frame)
        size_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        ttk.Label(size_frame, text="Size:").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Spinbox(size_frame, textvariable=size_var, from_=8, to=72, width=5).pack(side=tk.LEFT)
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        preview_frame = ttk.LabelFrame(main_frame, text="Preview", padding="10")
        preview_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(10, 0))
        preview_label = tk.Label(preview_frame, text="AaBbCcYyZz\n0123456789", bg="white", relief="sunken", height=2)
        preview_label.pack(fill=tk.BOTH, expand=True)
        def update_preview(*args):
            try:
                preview_label.configure(font=tkfont.Font(family=family_var.get(), size=size_var.get()))
            except Exception:
                pass
        family_var.trace_add('write', update_preview)
        size_var.trace_add('write', update_preview)
        def apply_font():
            self.apply_new_font((family_var.get(), size_var.get()))
            font_win.destroy()
        ttk.Button(btn_frame, text="Apply (OK)", command=apply_font).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=font_win.destroy).pack(side=tk.RIGHT, padx=5)

    # ------------------------------------------------------- settings
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
                "send_on_change": self.send_on_change.get(),
                "check_crc_rx": self.check_crc_rx_var.get(),
                "log_enabled": self.log_enabled.get(),
                "log_view_enabled": self.log_view_enabled.get(),
                "log_every_packet": self.log_every_packet.get(),
                "freeze_view": self.freeze_view.get(),
                "dac": {k: self.dac_vars[k].get() for k in DAC_KEYS},
                "font_family": self.log_font_family.get(),
                "font_size": self.log_font_size.get(),
                "scope_ch": self.scope_ch_var.get(),
                "scope_win": self.scope_win_var.get(),
                "window_geometry": self.root.geometry(),
            }
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass

    def load_settings(self):
        if not os.path.exists(self.settings_file):
            return
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
            if "send_on_change" in s: self.send_on_change.set(s["send_on_change"])
            if "check_crc_rx" in s: self.check_crc_rx_var.set(s["check_crc_rx"])
            if "log_enabled" in s: self.log_enabled.set(s["log_enabled"])
            if "log_view_enabled" in s: self.log_view_enabled.set(s["log_view_enabled"])
            if "log_every_packet" in s: self.log_every_packet.set(s["log_every_packet"])
            if "freeze_view" in s: self.freeze_view.set(s["freeze_view"])
            for k, v in s.get("dac", {}).items():
                if k in self.dac_vars:
                    self.dac_vars[k].set(str(v))
                    try:
                        self.dac_codes[k] = max(-32768, min(32767, int(v, 0)))
                    except ValueError:
                        self.dac_codes[k] = 0
            self.sync_dac_ui()
            if s.get("scope_ch") in SCOPE_MAP:
                self.scope_ch_var.set(s["scope_ch"])
            if s.get("scope_win") in ("0.25", "0.5", "1.0", "2.0", "5.0"):
                self.scope_win_var.set(s["scope_win"])
            if s.get("window_geometry"):
                try:
                    import re as _re
                    m = _re.match(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', s["window_geometry"])
                    if m:
                        w, h = int(m.group(1)), int(m.group(2))
                        x, y = int(m.group(3)), int(m.group(4))
                        sw = self.root.winfo_screenwidth()
                        sh = self.root.winfo_screenheight()
                        w = max(600, min(w, sw - 20))
                        h = max(400, min(h, sh - 60))
                        x = max(20 - w, min(x, sw - 120))
                        y = max(0, min(y, sh - 80))
                        self.root.geometry(f"{w}x{h}{x:+d}{y:+d}")
                    else:
                        self.root.geometry(s["window_geometry"])
                except Exception:
                    pass
            if "font_family" in s and "font_size" in s:
                self.apply_new_font((s["font_family"], s["font_size"]))
        except Exception:
            pass


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = BCPSPMSimulator(root)

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
