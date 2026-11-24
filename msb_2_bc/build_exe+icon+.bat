@echo off & python -x "%~f0" %* & exit /b
# ==============================================================================
# PURE PYTHON BUILDER - ZERO CMD.EXE BUGS & TASKBAR ICON FIX
# ==============================================================================
import os
import sys
import shutil
import subprocess

def setup():
    for pkg, mod in [("pyinstaller", "PyInstaller"), ("pillow", "PIL")]:
        try:
            __import__(mod)
        except ImportError:
            print(f"[i] Установка компонента {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", pkg])

def main():
    setup()
    from PIL import Image

    print("=" * 60)
    print("         PYTHON TO EXE BUILDER (TASKBAR ICON FIX)")
    print("=" * 60)
    print()

    # 1. Запрос .py файла
    py_input = input("1. Перетащите сюда ваш .py файл: ").strip().strip('"').strip("'")
    if not os.path.isfile(py_input):
        print(f"\n[!] ОШИБКА: Файл не найден: {py_input}")
        input("\nНажмите Enter для выхода...")
        return

    work_dir = os.path.dirname(os.path.abspath(py_input))
    base_name = os.path.splitext(os.path.basename(py_input))[0]

    # 2. Запрос картинки / иконки (любой формат: PNG, JPG, ICO)
    img_input = input("\n2. Перетащите сюда картинку (.png, .jpg, .ico) [или Enter]: ").strip().strip('"').strip("'")
    
    ico_file = None
    if img_input and os.path.isfile(img_input):
        print("\n[i] Конвертирую изображение в настоящий Windows ICO...")
        try:
            img = Image.open(img_input).convert("RGBA")
            ico_file = os.path.join(work_dir, "_temp_icon.ico")
            img.save(ico_file, format="ICO", sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])
            print("[OK] Иконка успешно создана!")
        except Exception as e:
            print(f"[!] Предупреждение: Не удалось обработать картинку ({e}). Сборка без нее.")
            ico_file = None

    # 3. Подготовка автоматического патча для устранения "перышка" Tkinter
    target_build_py = py_input
    temp_patched_py = None

    if ico_file and os.path.isfile(ico_file):
        print("[i] Применяю автоматический фикс панели задач Windows...")
        try:
            with open(py_input, "r", encoding="utf-8", errors="ignore") as f_src:
                original_code = f_src.read()

            patch_header = f"""# -*- coding: utf-8 -*-
# --- AUTO-INJECTED WINDOWS TASKBAR & TKINTER ICON FIX ---
import sys, os
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("{base_name}.app.id.2026")
    except Exception:
        pass
    try:
        import tkinter as _tk_patch
        _orig_tk_init = _tk_patch.Tk.__init__
        def _patched_tk_init(self, *args, **kwargs):
            _orig_tk_init(self, *args, **kwargs)
            try:
                self.iconbitmap(default=sys.executable)
            except Exception:
                try:
                    _base_p = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
                    _ico_p = os.path.join(_base_p, "_temp_icon.ico")
                    if os.path.exists(_ico_p):
                        self.iconbitmap(_ico_p)
                except Exception:
                    pass
        _tk_patch.Tk.__init__ = _patched_tk_init
    except Exception:
        pass
# --- END AUTO-INJECTED FIX ---

"""
            temp_patched_py = os.path.join(work_dir, f"_build_temp_{base_name}.py")
            with open(temp_patched_py, "w", encoding="utf-8", errors="ignore") as f_dst:
                f_dst.write(patch_header + original_code)

            target_build_py = temp_patched_py
        except Exception as e:
            print(f"[!] Не удалось пропатчить код ({e}), компилирую оригинал.")
            target_build_py = py_input

    print("\n" + "=" * 60)
    print(f"   Идет сборка {base_name}.exe ... Пожалуйста, подождите")
    print("=" * 60 + "\n")

    # 4. Формирование команды PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name", base_name
    ]

    if ico_file and os.path.isfile(ico_file):
        cmd.extend(["--icon", ico_file])
        cmd.extend(["--add-data", f"{ico_file};."])

    cmd.append(target_build_py)

    # 5. Запуск PyInstaller
    build_success = False
    try:
        subprocess.run(cmd, cwd=work_dir, check=True)
        build_success = True
    except subprocess.CalledProcessError:
        print("\n[!] ОШИБКА СБОРКИ PyInstaller!")

    # 6. Очистка временного пропатченного файла
    if temp_patched_py and os.path.exists(temp_patched_py):
        try: os.remove(temp_patched_py)
        except: pass

    if not build_success:
        if ico_file and os.path.exists(ico_file):
            try: os.remove(ico_file)
            except: pass
        input("\nНажмите Enter для выхода...")
        return

    # 7. Перемещение финального EXE
    dist_exe = os.path.join(work_dir, "dist", f"{base_name}.exe")
    final_exe = os.path.join(work_dir, f"{base_name}.exe")
    if os.path.isfile(dist_exe):
        shutil.move(dist_exe, final_exe)

    # 8. Очистка временных папок сборщика
    for folder in ["build", "dist"]:
        p = os.path.join(work_dir, folder)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)

    spec = os.path.join(work_dir, f"{base_name}.spec")
    if os.path.isfile(spec):
        try: os.remove(spec)
        except: pass

    if ico_file and os.path.isfile(ico_file):
        try: os.remove(ico_file)
        except: pass

    print("=" * 60)
    print("   [УСПЕХ] Сборка полностью завершена!")
    print(f"   Файл готов: {final_exe}")
    print("=" * 60)
    print()
    input("Нажмите Enter для завершения...")

if __name__ == "__main__":
    main()