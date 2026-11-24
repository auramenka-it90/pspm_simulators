#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ФАЙЛ: vt100_full_sim.py
- Индикаторы: узкие горизонтальные планки (высота 8 пикс, ширина 20 пикс):
  * OFF -> темно-серый (#252A34)
  * ON  -> ярко-зеленый (#00FF00)
- Глобальное переключение Bold/Normal для всего экрана целиком (как в MicroBlaze)
- Сохранение геометрии 1:1 как в cu_simulator.py
- Отклик всех 6 кнопок 0 мс
"""

import os
import re
import sys
import time
import json
import threading
import queue
import ctypes
import tkinter as tk

# Включение DPI-Awareness как в cu_simulator.py
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

# Определение рабочей папки 1:1 как в cu_simulator.py
if getattr(sys, 'frozen', False):
    app_dir = os.path.dirname(os.path.abspath(sys.executable))
else:
    app_dir = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(app_dir, "vt100_sim_config.json")
FONT_FILE   = os.path.join(app_dir, "font.coe")

# ==============================================================================
# ЦВЕТОВАЯ ПАЛИТРА
# ==============================================================================
COLOR_PANEL_BG  = "#525A69"
COLOR_BTN_BG    = "#404856"
COLOR_BTN_FG    = "#FFFFFF"
COLOR_BTN_ACT   = "#808A9D"
COLOR_LABEL_TXT = "#FFFFFF"

# Единые цвета для всех 3 индикаторов
COLOR_IND_OFF     = "#252A34"   # Темно-серый
COLOR_IND_OFF_OUT = "#181B22"
COLOR_IND_ON      = "#00FF00"   # Ярко-зеленый
COLOR_IND_ON_OUT  = "#88FF88"

# ==============================================================================
# 1. ЗАГРУЗКА 512 СИМВОЛОВ font.coe (0..255 = Normal, 256..511 = Bold)
# ==============================================================================
def load_all_fonts(filepath=FONT_FILE):
    norm_dict = {i: [0]*16 for i in range(256)}
    bold_dict = {i: [0]*16 for i in range(256)}

    if not os.path.exists(filepath):
        return norm_dict, bold_dict

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    text = re.sub(r";.*", "", text)
    hex_tokens = re.findall(r"\b[0-9a-fA-F]{2}\b", text)
    hex_bytes = [int(t, 16) for t in hex_tokens]

    total_chars = len(hex_bytes) // 16

    if total_chars >= 512:
        for i in range(256):
            norm_dict[i] = hex_bytes[i * 16 : (i + 1) * 16]
            bold_dict[i] = hex_bytes[(256 + i) * 16 : (256 + i + 1) * 16]
    elif total_chars >= 256:
        for i in range(256):
            bold_dict[i] = hex_bytes[i * 16 : (i + 1) * 16]
            norm_dict[i] = [b & ~(b >> 1) for b in bold_dict[i]]

    return norm_dict, bold_dict

font_norm_data, font_bold_data = load_all_fonts(FONT_FILE)

# ==============================================================================
# 2. РЕНДЕР СИМВОЛОВ (16x32)
# ==============================================================================
SCALE = 2
GW = 8 * SCALE
GH = 16 * SCALE

glyph_cache = {}

def make_glyph_img(matrix_16, is_inv=False, is_undl=False):
    fg = (10, 10, 12) if is_inv else (235, 235, 240)
    bg = (235, 235, 240) if is_inv else (10, 10, 12)

    ppm = bytearray(f"P6 {GW} {GH} 255\n".encode("ascii"))
    for r in range(16):
        b = matrix_16[r] if r < len(matrix_16) else 0
        if is_undl and r == 14:
            b = 0xFF

        row_px = bytearray()
        for c in range(8):
            bit = (b >> (7 - c)) & 0x01
            row_px.extend((fg if bit else bg) * SCALE)
        for _ in range(SCALE):
            ppm.extend(row_px)
    return tk.PhotoImage(data=bytes(ppm), format="PPM")

def get_glyph_img(code, is_inv, is_undl, is_bold):
    key = (code, is_inv, is_undl, is_bold)
    if key not in glyph_cache:
        matrix = font_bold_data.get(code, [0]*16) if is_bold else font_norm_data.get(code, [0]*16)
        glyph_cache[key] = make_glyph_img(matrix, is_inv, is_undl)
    return glyph_cache[key]

# ==============================================================================
# 3. НЕЗАВИСАЮЩИЙ ДРАЙВЕР СВЯЗИ
# ==============================================================================
class ComDriver:
    def __init__(self, rx_cb, status_cb):
        self.rx_cb = rx_cb
        self.status_cb = status_cb
        self.ser = None
        self.running = False
        self.rx_bytes_total = 0
        self.tx_bytes_total = 0

    def connect_async(self, port_name, baud=921600):
        threading.Thread(target=self._do_connect, args=(port_name, baud), daemon=True).start()

    def _do_connect(self, port_name, baud):
        self.disconnect()
        if not HAS_SERIAL:
            self.status_cb(False, "NO PYSERIAL")
            return

        try:
            s = serial.Serial(
                port=port_name,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.02,
                write_timeout=0.2
            )
            try:
                s.set_buffer_size(rx_size=65536, tx_size=65536)
            except:
                pass

            self.ser = s
            self.running = True
            self.rx_bytes_total = 0
            self.tx_bytes_total = 0
            threading.Thread(target=self._rx_loop, daemon=True).start()
            self.status_cb(True, "OK")
        except Exception:
            self.status_cb(False, "TIMEOUT")

    def disconnect(self):
        self.running = False
        if self.ser and self.ser.is_open:
            try: self.ser.close()
            except: pass
        self.ser = None

    def _rx_loop(self):
        while self.running and self.ser and self.ser.is_open:
            try:
                avail = self.ser.in_waiting
                if avail > 0:
                    raw = self.ser.read(avail)
                    self.rx_bytes_total += len(raw)
                    self.rx_cb(raw)
                else:
                    time.sleep(0.002)
            except:
                break
        self.disconnect()

    def send(self, data: bytes):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(data)
                self.ser.flush()
                self.tx_bytes_total += len(data)
            except:
                pass

# ==============================================================================
# 4. FSM ПАРСЕР VT100
# ==============================================================================
class VT100Engine:
    def __init__(self, tx_func):
        self.tx_func = tx_func
        self.cols = 64
        self.rows = 19
        self.cursor_x = 0
        self.cursor_y = 0
        self.attr_inv = False
        self.attr_undl = False
        self.is_bold_global = True
        self.state = "NORMAL"
        self.params = []
        self.buffer = [[(0x20, False, False) for _ in range(self.cols)] for _ in range(self.rows)]
        self.is_dirty = True

    def clear(self):
        for r in range(self.rows):
            for c in range(self.cols):
                self.buffer[r][c] = (0x20, False, False)
        self.cursor_x = 0
        self.cursor_y = 0
        self.is_dirty = True

    def put_byte(self, b: int):
        if self.cursor_x >= self.cols:
            self.cursor_x = 0
            self.cursor_y = (self.cursor_y + 1) % self.rows
        self.buffer[self.cursor_y][self.cursor_x] = (b, self.attr_inv, self.attr_undl)
        self.cursor_x += 1
        if self.cursor_x >= self.cols:
            self.cursor_x = 0
            self.cursor_y = (self.cursor_y + 1) % self.rows
        self.is_dirty = True

    def feed(self, raw_bytes: bytes):
        for b in raw_bytes:
            self._parse_byte(b)

    def _parse_byte(self, b: int):
        if b == 0x13: self.cols = 64; self.is_dirty = True; return
        elif b == 0x14: self.cols = 48; self.is_dirty = True; return
        if b == 0x08:
            if self.cursor_x > 0:
                self.cursor_x -= 1
                self.buffer[self.cursor_y][self.cursor_x] = (0x20, False, False)
                self.is_dirty = True
            return
        elif b == 0x09: self.cursor_x = min(self.cols - 1, self.cursor_x + 4); return
        elif b == 0x0A: self.cursor_y = min(self.rows - 1, self.cursor_y + 1); return
        elif b == 0x0D: self.cursor_x = 0; return
        elif b == 0x1B: self.state = "ESCAPE"; return

        if self.state == "NORMAL":
            self.put_byte(b)
        elif self.state == "ESCAPE":
            self.state = "NORMAL"
            if b == ord('['):
                self.state = "GET_PARAMS"
                self.params = [0]
            elif b == ord('('):   # ESC ( -> Normal Font
                if self.is_bold_global:
                    self.is_bold_global = False
                    force_full_redraw()
            elif b == ord(')'):   # ESC ) -> Bold Font
                if not self.is_bold_global:
                    self.is_bold_global = True
                    force_full_redraw()
            elif b == ord('c'):
                self.clear()
        elif self.state == "GET_PARAMS":
            ch = chr(b)
            if ch.isdigit():
                self.params[-1] = self.params[-1] * 10 + int(ch)
            elif ch == ';':
                self.params.append(0)
            elif ch == '?':
                pass
            else:
                self._exec_cmd(ch)
                self.state = "NORMAL"

    def _exec_cmd(self, cmd: str):
        global is_mux_vt100, adjust_permitted
        p0 = self.params[0] if len(self.params) > 0 else 0
        p1 = self.params[1] if len(self.params) > 1 else 0

        if cmd in ('H', 'f'):
            self.cursor_y = max(0, min(self.rows - 1, p0))
            self.cursor_x = max(0, min(self.cols - 1, p1))
        elif cmd == 'A': self.cursor_y = max(0, self.cursor_y - (p0 if p0 > 0 else 1))
        elif cmd == 'B': self.cursor_y = min(self.rows - 1, self.cursor_y + (p0 if p0 > 0 else 1))
        elif cmd == 'C': self.cursor_x = min(self.cols - 1, self.cursor_x + (p0 if p0 > 0 else 1))
        elif cmd == 'D': self.cursor_x = max(0, self.cursor_x - (p0 if p0 > 0 else 1))
        elif cmd == 'J':
            if p0 == 2: self.clear()
        elif cmd == 'K':
            if p0 == 2:
                for c in range(self.cols): self.buffer[self.cursor_y][c] = (0x20, False, False)
            elif p0 == 0:
                for c in range(self.cursor_x, self.cols): self.buffer[self.cursor_y][c] = (0x20, False, False)
            elif p0 == 1:
                for c in range(0, self.cursor_x + 1): self.buffer[self.cursor_y][c] = (0x20, False, False)
            self.is_dirty = True
        elif cmd == 'm':
            for a in self.params:
                if a == 0:
                    self.attr_inv = False
                    self.attr_undl = False
                elif a == 4:
                    self.attr_undl = True
                elif a == 7:
                    self.attr_inv = True
        elif cmd == 'n' and p0 == 5:
            if is_mux_vt100:
                self.tx_func(b"\x1B[0n")
        elif cmd == 'c':
            if is_mux_vt100:
                mode_val = 4 if adjust_permitted else 0
                self.tx_func(f"\x1B[?{mode_val}c".encode('ascii'))

# ==============================================================================
# 5. ГРАФИЧЕСКИЙ ИНТЕРФЕЙС
# ==============================================================================
root = tk.Tk()
root.title("VT100 Terminal Simulator (Hardware Digital Twin)")
root.configure(bg=COLOR_PANEL_BG)
root.resizable(False, False)

def load_settings():
    cfg = {"window_geometry": None, "port": "NO PORT", "adjust_permitted": True}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
        except Exception:
            pass
    return cfg

saved_cfg = load_settings()

port_var = tk.StringVar(value=saved_cfg.get("port", "NO PORT"))
adjust_permitted = saved_cfg.get("adjust_permitted", True)

def save_settings():
    try:
        cfg = {
            "window_geometry": root.geometry(),
            "port": port_var.get(),
            "adjust_permitted": adjust_permitted
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4)
    except Exception:
        pass

if saved_cfg.get("window_geometry"):
    try:
        root.geometry(saved_cfg["window_geometry"])
    except Exception:
        pass

btn_style = {
    "bg": COLOR_BTN_BG,
    "fg": COLOR_BTN_FG,
    "activebackground": COLOR_BTN_ACT,
    "activeforeground": "#000000",
    "font": ("Arial", 14, "bold"),
    "width": 11,
    "height": 3,
    "relief": "raised",
    "bd": 4,
    "takefocus": 0
}

btn_top_style = {
    "bg": COLOR_BTN_BG,
    "fg": COLOR_BTN_FG,
    "activebackground": COLOR_BTN_ACT,
    "activeforeground": "#000000",
    "font": ("Arial", 9, "bold"),
    "relief": "raised",
    "bd": 3,
    "takefocus": 0,
    "pady": 3
}

# УЗКАЯ ГОРИЗОНТАЛЬНАЯ ПЛАНКА-ИНДИКАТОР: ширина увеличена в 2 раза (20 px), высота уменьшена в 2 раза (8 px)
def create_rect_indicator(parent):
    c = tk.Canvas(parent, width=24, height=12, bg=COLOR_PANEL_BG, highlightthickness=0, takefocus=0)
    r = c.create_rectangle(2, 2, 22, 10, fill=COLOR_IND_OFF, outline=COLOR_IND_OFF_OUT, width=1)
    return c, r

def set_rect_indicator(canvas_widget, rect_id, on: bool):
    fill_col = COLOR_IND_ON if on else COLOR_IND_OFF
    out_col  = COLOR_IND_ON_OUT if on else COLOR_IND_OFF_OUT
    canvas_widget.itemconfig(rect_id, fill=fill_col, outline=out_col)

# Верхняя панель
top_frame = tk.Frame(root, bg=COLOR_PANEL_BG, takefocus=0)
top_frame.pack(fill="x", padx=20, pady=(12, 0))

top_row = tk.Frame(top_frame, bg=COLOR_PANEL_BG, takefocus=0)
top_row.pack(fill="x")

# --- ЛЕВЫЙ БЛОК: СВЯЗЬ COM ---
com_left_frame = tk.Frame(top_row, bg=COLOR_PANEL_BG, takefocus=0)
com_left_frame.pack(side="left")

tk.Label(com_left_frame, text="COM PORT:", bg=COLOR_PANEL_BG, fg=COLOR_LABEL_TXT, font=("Arial", 9, "bold")).pack(side="left", padx=(0, 6))

port_menu = tk.OptionMenu(com_left_frame, port_var, port_var.get())
port_menu.config(width=9, **btn_top_style)
port_menu["menu"].config(bg=COLOR_BTN_BG, fg="#FFFFFF", activebackground=COLOR_BTN_ACT, font=("Arial", 9, "bold"))
port_menu.pack(side="left", padx=(0, 4))

# 1. Горизонтальная планка-индикатор COM
ind_com_canvas, ind_com_rect = create_rect_indicator(com_left_frame)
ind_com_canvas.pack(side="left", padx=(2, 6))

def update_ports():
    menu = port_menu["menu"]
    menu.delete(0, "end")
    ports = [p.device for p in serial.tools.list_ports.comports()] if HAS_SERIAL else []
    if ports:
        for p in ports:
            menu.add_command(label=p, command=lambda v=p: on_select_port(v))
        if port_var.get() not in ports and port_var.get() == "NO PORT":
            port_var.set(ports[0])
    else:
        port_var.set("NO PORT")
        menu.add_command(label="NO PORT", command=lambda: port_var.set("NO PORT"))

def on_select_port(p_name):
    port_var.set(p_name)
    save_settings()

btn_scan = tk.Button(com_left_frame, text="REFRESH", width=8, command=update_ports, **btn_top_style)
btn_scan.pack(side="left", padx=4)

rx_queue = queue.Queue()

def on_status_change(ok, msg):
    root.after(0, lambda: _apply_status(ok, msg))

def _apply_status(ok, msg):
    if ok:
        btn_conn.config(text="DISCONNECT", state="normal")
        set_rect_indicator(ind_com_canvas, ind_com_rect, True)
        uart_info_lbl.config(text="LINK ACTIVE @ 921600 Baud | RX: 0 B | TX: 0 B")
        save_settings()
    else:
        btn_conn.config(text="CONNECT", state="normal")
        set_rect_indicator(ind_com_canvas, ind_com_rect, False)
        uart_info_lbl.config(text=f"ERROR: {msg}")
        reset_to_camera_mode()

driver = ComDriver(rx_cb=rx_queue.put, status_cb=on_status_change)
vt100 = VT100Engine(tx_func=driver.send)

def toggle_connect():
    if driver.ser and driver.ser.is_open:
        driver.disconnect()
        btn_conn.config(text="CONNECT")
        set_rect_indicator(ind_com_canvas, ind_com_rect, False)
        uart_info_lbl.config(text="COMM SETTINGS: 921600 Baud | 8N1 | Full-Duplex")
        reset_to_camera_mode()
    else:
        p = port_var.get()
        if p and p != "NO PORT":
            btn_conn.config(text="CONNECTING...", state="disabled")
            driver.connect_async(p, 921600)

btn_conn = tk.Button(com_left_frame, text="CONNECT", width=11, command=toggle_connect, **btn_top_style)
btn_conn.pack(side="left", padx=(4, 0))

# --- ПРАВЫЙ БЛОК: РЕЖИМЫ (MUX + ADJUST) ---
mux_right_frame = tk.Frame(top_row, bg=COLOR_PANEL_BG, takefocus=0)
mux_right_frame.pack(side="right")

is_mux_vt100 = False

# 2. Горизонтальная планка-индикатор MUX
ind_mux_canvas, ind_mux_rect = create_rect_indicator(mux_right_frame)
ind_mux_canvas.pack(side="right", padx=(4, 0))

def reset_to_camera_mode():
    global is_mux_vt100
    is_mux_vt100 = False
    set_rect_indicator(ind_mux_canvas, ind_mux_rect, False)
    btn_mux.config(bg=COLOR_BTN_BG)
    force_draw_camera()

def toggle_mux():
    global is_mux_vt100
    is_mux_vt100 = not is_mux_vt100
    set_rect_indicator(ind_mux_canvas, ind_mux_rect, is_mux_vt100)
    if is_mux_vt100:
        btn_mux.config(bg="#5B6577")
        force_draw_vt100()
    else:
        btn_mux.config(bg=COLOR_BTN_BG)
        force_draw_camera()

btn_mux = tk.Button(mux_right_frame, text="MUX: MENU (TAB 2s)", width=18, command=toggle_mux, **btn_top_style)
btn_mux.pack(side="right", padx=(8, 2))

# 3. Горизонтальная планка-индикатор ADJUST
ind_adj_canvas, ind_adj_rect = create_rect_indicator(mux_right_frame)
ind_adj_canvas.pack(side="right", padx=(4, 0))

def update_adjust_btn_ui():
    set_rect_indicator(ind_adj_canvas, ind_adj_rect, adjust_permitted)
    if adjust_permitted:
        btn_adjust.config(text="ADJUST: ON [4]", bg="#5B6577")
    else:
        btn_adjust.config(text="ADJUST: OFF [0]", bg=COLOR_BTN_BG)

def toggle_adjust():
    global adjust_permitted
    adjust_permitted = not adjust_permitted
    update_adjust_btn_ui()
    save_settings()

btn_adjust = tk.Button(mux_right_frame, width=16, command=toggle_adjust, **btn_top_style)
btn_adjust.pack(side="right", padx=(0, 2))
update_adjust_btn_ui()

uart_info_lbl = tk.Label(top_frame,
                         text="COMM SETTINGS: 921600 Baud | 8N1 | Full-Duplex",
                         bg=COLOR_PANEL_BG, fg=COLOR_LABEL_TXT, font=("Arial", 9, "bold"))
uart_info_lbl.pack(anchor="w", pady=(4, 0))

update_ports()

# Экран (64x19)
COLS, ROWS = 64, 19
SCREEN_W, SCREEN_H = COLS * GW, ROWS * GH

canvas = tk.Canvas(root, width=SCREEN_W, height=SCREEN_H, bg="#0A0A0C", highlightthickness=2, highlightbackground="#2E333C", takefocus=0)
canvas.pack(padx=20, pady=12)

canvas_cells = [[None for _ in range(COLS)] for _ in range(ROWS)]
current_rendered = [[(0x20, False, False, True) for _ in range(COLS)] for _ in range(ROWS)]
default_blank_img = get_glyph_img(0x20, False, False, True)

for r in range(ROWS):
    for c in range(COLS):
        canvas_cells[r][c] = canvas.create_image(c * GW, r * GH, anchor="nw", image=default_blank_img)

# ==============================================================================
# 6. ВИДЕОИСТОЧНИКИ: КАМЕРА И VT100
# ==============================================================================
app_start_ts = time.time()
spin_chars = ['|', '/', '-', '\\']
spin_idx = 0
last_spin_ts = 0.0

def force_draw_camera():
    global spin_idx
    up_secs = int(time.time() - app_start_ts)
    h = up_secs // 3600
    m = (up_secs % 3600) // 60
    s = up_secs % 60
    cam_str = f"[ EXTERNAL VIDEO: CAMERA ]  {spin_chars[spin_idx]}  [{h:02d}:{m:02d}:{s:02d}]"
    cam_bytes = cam_str.encode("cp1251", errors="replace")
    start_c = (COLS - len(cam_bytes)) // 2

    for r in range(ROWS):
        for c in range(COLS):
            val = (0x20, False, False, vt100.is_bold_global)
            if r == 9 and start_c <= c < start_c + len(cam_bytes):
                val = (cam_bytes[c - start_c], False, False, vt100.is_bold_global)
            if val != current_rendered[r][c]:
                current_rendered[r][c] = val
                canvas.itemconfig(canvas_cells[r][c], image=get_glyph_img(val[0], val[1], val[2], val[3]))

def force_draw_vt100():
    for r in range(ROWS):
        for c in range(COLS):
            b, inv, undl = vt100.buffer[r][c]
            val = (b, inv, undl, vt100.is_bold_global)
            current_rendered[r][c] = val
            canvas.itemconfig(canvas_cells[r][c], image=get_glyph_img(b, inv, undl, vt100.is_bold_global))

def force_full_redraw():
    vt100.is_dirty = True
    if is_mux_vt100:
        force_draw_vt100()

# ==============================================================================
# 7. ПАНЕЛЬ 6 КНОПОК ПУЛЬТА
# ==============================================================================
panel_frame = tk.Frame(root, bg=COLOR_PANEL_BG, takefocus=0)
panel_frame.pack(fill="x", padx=20, pady=10)

keypad_frame = tk.Frame(panel_frame, bg=COLOR_PANEL_BG, takefocus=0)
keypad_frame.pack(pady=5)

def flash_btn(btn, payload):
    btn.config(bg=COLOR_BTN_ACT)
    driver.send(payload)
    root.after(100, lambda: btn.config(bg=COLOR_BTN_BG))

def on_tab_action(e=None):
    flash_btn(btn_tab, b"\x09")
    return "break"

btn_up    = tk.Button(keypad_frame, text="UP",    command=lambda: flash_btn(btn_up,    b"\x1B[A"), **btn_style)
btn_left  = tk.Button(keypad_frame, text="LEFT",  command=lambda: flash_btn(btn_left,  b"\x1B[D"), **btn_style)
btn_enter = tk.Button(keypad_frame, text="ENTER", command=lambda: flash_btn(btn_enter, b"\x0D"),   **btn_style)
btn_right = tk.Button(keypad_frame, text="RIGHT", command=lambda: flash_btn(btn_right, b"\x1B[C"), **btn_style)
btn_down  = tk.Button(keypad_frame, text="DOWN",  command=lambda: flash_btn(btn_down,  b"\x1B[B"), **btn_style)

btn_tab_style = btn_style.copy()
btn_tab_style["width"] = 14
btn_tab   = tk.Button(keypad_frame, text="TAB",   command=on_tab_action, **btn_tab_style)

btn_up.grid(row=0, column=1, padx=6, pady=6)
btn_left.grid(row=1, column=0, padx=6, pady=6)
btn_enter.grid(row=1, column=1, padx=6, pady=6)
btn_right.grid(row=1, column=2, padx=6, pady=6)
btn_down.grid(row=2, column=1, padx=6, pady=6)
btn_tab.grid(row=2, column=4, padx=(100, 0), pady=6)

# ==============================================================================
# 8. ПРИВЯЗКА КЛАВИАТУРЫ ПК
# ==============================================================================
root.bind_all("<Up>",     lambda e: flash_btn(btn_up,    b"\x1B[A"))
root.bind_all("<Down>",   lambda e: flash_btn(btn_down,  b"\x1B[B"))
root.bind_all("<Left>",   lambda e: flash_btn(btn_left,  b"\x1B[D"))
root.bind_all("<Right>",  lambda e: flash_btn(btn_right, b"\x1B[C"))
root.bind_all("<Return>", lambda e: flash_btn(btn_enter, b"\x0D"))

root.bind("<Tab>", on_tab_action)
root.bind_all("<Tab>", on_tab_action)
root.bind_class("Button", "<Tab>", on_tab_action)
root.bind_class("Canvas", "<Tab>", on_tab_action)
root.bind_class("Frame",  "<Tab>", on_tab_action)

# ==============================================================================
# 9. ГЛАВНЫЙ ЦИКЛ ОБНОВЛЕНИЯ (20 мс)
# ==============================================================================
def update_loop():
    global spin_idx, last_spin_ts

    chunk = bytearray()
    while not rx_queue.empty():
        try: chunk.extend(rx_queue.get_nowait())
        except: break

    if chunk:
        vt100.feed(chunk)

    if driver.running:
        uart_info_lbl.config(
            text=f"LINK ACTIVE @ 921600 Baud | RX: {driver.rx_bytes_total} B | TX: {driver.tx_bytes_total} B"
        )

    if is_mux_vt100:
        if vt100.is_dirty:
            for r in range(ROWS):
                for c in range(COLS):
                    b, inv, undl = vt100.buffer[r][c]
                    val = (b, inv, undl, vt100.is_bold_global)
                    if val != current_rendered[r][c]:
                        current_rendered[r][c] = val
                        canvas.itemconfig(canvas_cells[r][c], image=get_glyph_img(b, inv, undl, vt100.is_bold_global))
            vt100.is_dirty = False
    else:
        now = time.time()
        if now - last_spin_ts >= 0.5:
            last_spin_ts = now
            spin_idx = (spin_idx + 1) % 4
            force_draw_camera()

    root.after(20, update_loop)

reset_to_camera_mode()
update_loop()

def on_closing():
    save_settings()
    driver.disconnect()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)
root.mainloop()