"""
Claude Ghost — горячая клавиша -> выделяешь область экрана -> Claude отвечает
в маленьком полупрозрачном окне в правом верхнем углу.

Авторизация: через Claude Code CLI (`claude auth login`), без API-ключа.
Вход и установку CLI можно сделать из панели Ctrl+Shift+M.
Платформа: Windows 10/11. Запуск из исходников: Python 3.10+, или собранный CG.exe.
"""

import base64
import ctypes
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import tkinter as tk
import urllib.request
import tkinter.font as tkfont

import keyboard
import mss
from PIL import Image, ImageEnhance, ImageTk

APP_NAME = "Claude Ghost"
__version__ = "1.1.3"  # при сборке из тега vX.Y.Z заменяется на X.Y.Z (build.ps1)
UPDATE_REPO = "cl0wster-0/claude-ghost"
FROZEN = getattr(sys, "frozen", False)  # True, если запущен собранный .exe
APP_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
# Настройки и лог храним в %APPDATA%\ClaudeGhost: папка установки может быть только для чтения
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "ClaudeGhost")
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "error.log")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0       # CREATE_NO_WINDOW
NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0     # CREATE_NEW_CONSOLE

# В .exe / pythonw нет консоли — ошибки пишем в файл
if FROZEN or sys.stderr is None:
    try:
        sys.stderr = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or sys.stderr
    except Exception:
        pass

# Перенос config.json от старой версии (лежал рядом со скриптом)
_old_cfg = os.path.join(APP_DIR, "config.json")
if not os.path.exists(CONFIG_PATH) and os.path.exists(_old_cfg):
    try:
        shutil.copyfile(_old_cfg, CONFIG_PATH)
    except Exception:
        pass

DEFAULT_CONFIG = {
    # Горячие клавиши (синтаксис библиотеки `keyboard`)
    "hotkey": "ctrl+shift+space",      # выделить область и спросить
    "hide_hotkey": "ctrl+shift+h",     # спрятать окно ответа
    "quit_hotkey": "ctrl+shift+alt+q", # закрыть программу
    # Модель: "auto" — выбирается по сложности вопроса, "haiku" — самая быстрая,
    # "sonnet" — умнее, "opus" — самая умная. Удобнее менять в оверлее настроек.
    "model": "auto",
    # Effort (сколько модель думает): "auto", "low", "medium", "high", "xhigh", "max"
    "effort": "auto",
    "settings_hotkey": "ctrl+shift+m",
    # Режим Auto: простые вопросы -> fast, сложные -> strong
    "auto_fast": ["haiku", "low"],
    "auto_strong": ["sonnet", "medium"],
    # Картинка больше стольких пикселей (площадь) считается сложной
    "auto_image_area": 300000,
    # Текст (голос) длиннее стольких символов считается сложным
    "auto_text_chars": 160,
    # Слова, при которых вопрос считается сложным (часть слова, без учёта регистра)
    "auto_hard_words": ["код", "программ", "алгоритм", "докаж", "доказ", "вывед", "выведи",
                        "интеграл", "производн", "матриц", "схем", "сложност", "оптимиз",
                        "объясни подробно", "почему", "code", "prove", "derive", "explain why"],
    "system_prompt": (
        "Пользователь присылает вопрос: картинку с частью своего экрана или текст, "
        "распознанный из голоса (в нём могут быть ошибки распознавания). "
        "Дай ответ сразу, максимально коротко: сначала сам ответ, затем при "
        "необходимости 1-2 строки пояснения. Без вступлений. Отвечай на языке вопроса."
    ),
    # Внешний вид окна ответа
    "box_width": 300,
    "box_max_height": 300,
    "box_margin": 14,
    "box_alpha": 0.85,
    "box_bg": "#2b2b2b",
    "box_fg": "#e8e8e8",
    "font": ["Segoe UI", 9],
    # Скрывать ответ автоматически через N секунд (0 = не скрывать)
    "auto_hide_seconds": 0,
    # Проверять обновления на GitHub Releases при запуске (только для установленного .exe)
    "check_updates": True,
    # Держать заранее запущенный процесс claude, чтобы ответ приходил быстрее
    "prewarm": True,
    # Максимальная длинная сторона картинки, отправляемой Claude
    "max_image_side": 1568,
    # Голосовой ввод: нажал — говоришь, нажал ещё раз — вопрос уходит Claude
    "voice_hotkey": "ctrl+shift+v",
    # Модель распознавания речи faster-whisper: tiny / base / small / medium
    # (base — быстро; small — точнее, но медленнее). Скачивается один раз.
    "whisper_model": "base",
    # Язык речи: "ru", "en" ... или null для автоопределения
    "voice_language": "ru",
    # Максимальная длина записи в секундах
    "voice_max_seconds": 60,
    "mic_icon_color": "#e05555",
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:  # плохой JSON — работаем на значениях по умолчанию
            print("config.json error:", e)
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    return cfg


def set_dpi_aware():
    """Чтобы координаты Tk совпадали с пикселями скриншота на экранах с масштабом 125%/150%."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def work_area():
    """Рабочая область основного монитора (без панели задач)."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]
        r = RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        return r.l, r.t, r.r, r.b
    except Exception:
        return None


def find_claude():
    """Путь к claude.exe: PATH или стандартные места установки (PATH может быть ещё не обновлён)."""
    for name in ("claude", "claude.exe", "claude.cmd"):
        p = shutil.which(name)
        if p:
            return p
    home = os.path.expanduser("~")
    for p in (os.path.join(home, ".local", "bin", "claude.exe"),
              os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")):
        if os.path.isfile(p):
            return p
    return None


class ClaudeAccount:
    """Статус входа в Claude Code CLI, вход и установка CLI."""

    INSTALL_PS = (
        "$ErrorActionPreference='Stop';"
        "Write-Host 'Устанавливаю Claude Code CLI...';"
        "irm https://claude.ai/install.ps1 | iex;"
        "$c=Join-Path $env:USERPROFILE '.local\\bin\\claude.exe';"
        "Write-Host ''; Write-Host 'Вход в аккаунт Claude (откроется браузер)...';"
        "& $c auth login --claudeai;"
        "Write-Host ''; Write-Host 'Готово. Это окно можно закрыть.'; Read-Host | Out-Null"
    )

    def __init__(self):
        self.exe = find_claude()
        self.logged_in = None     # None — ещё не проверяли
        self.busy = False         # идёт установка / вход
        self.on_change = None     # вызывается (из потока) после изменения статуса

    def check(self):
        """Обновить статус (блокирующий вызов, ~1 c) — запускать в потоке."""
        self.exe = find_claude()
        if not self.exe:
            self.logged_in = False
            return
        try:
            out = subprocess.run([self.exe, "auth", "status", "--json"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace",
                                 timeout=20, creationflags=NO_WINDOW).stdout
            self.logged_in = bool(json.loads(out[out.find("{"):]).get("loggedIn"))
        except Exception:
            self.logged_in = None

    def check_async(self):
        def _do():
            self.check()
            if self.on_change:
                self.on_change()
        threading.Thread(target=_do, daemon=True).start()

    def status_text(self):
        if self.busy:
            return "Открыто окно входа / установки…"
        if not self.exe:
            return "Claude CLI не установлен"
        if self.logged_in is None:
            return "Claude CLI: проверяю вход…"
        return "Вход в Claude выполнен ✓" if self.logged_in else "Claude CLI установлен, вход не выполнен"

    def action(self):
        """(текст кнопки, функция) для текущего состояния."""
        if self.busy:
            return None, None
        if not self.exe:
            return "Установить CLI и войти", self.install_and_login
        if self.logged_in:
            return "Сменить аккаунт", self.relogin
        return "Войти", self.login

    def _console(self, args):
        """Открыть видимую консоль (нужна для входа), дождаться её закрытия и обновить статус."""
        self.busy = True
        if self.on_change:
            self.on_change()
        def _do():
            try:
                subprocess.Popen(args, creationflags=NEW_CONSOLE).wait()
            except Exception as e:
                print("console error:", e, file=sys.stderr)
            self.busy = False
            self.check()
            if self.on_change:
                self.on_change()
        threading.Thread(target=_do, daemon=True).start()

    def install_and_login(self):
        self._console(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", self.INSTALL_PS])

    def login(self):
        self._console(["cmd", "/c", self.exe, "auth", "login", "--claudeai", "&", "pause"])

    def relogin(self):
        self._console(["cmd", "/c", self.exe, "auth", "logout", "&", self.exe, "auth", "login",
                       "--claudeai", "&", "pause"])


def save_settings(updates):
    """Записать изменения в config.json, не трогая остальные поля."""
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data.update(updates)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def strip_markdown(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return text


# --------------------------------------------------------------------------- #
#  Запуск Claude Code CLI
# --------------------------------------------------------------------------- #

class ClaudeRunner:
    """Запускает `claude -p` в режиме stream-json и стримит текст ответа.

    Чтобы не ждать старта CLI (~2 c) при каждом вопросе, держим заранее
    запущенные ("прогретые") процессы, которые ждут ввода. Процесс привязан
    к паре (модель, effort), поэтому их словарь: key -> Popen.
    """

    def __init__(self, cfg, events):
        self.cfg = cfg
        self.events = events  # очередь в GUI: ("delta", str) / ("done", None) / ("error", str)
        self.exe = find_claude()
        self.compat = False   # True, если версия CLI не знает "лишних" флагов
        self.warm = {}
        self.wanted = []      # какие пары (модель, effort) держать прогретыми
        self.current = None
        self.lock = threading.Lock()
        self.run_id = 0

    def _cmd(self, key):
        model, effort = key
        cmd = [self.exe, "-p",
               "--input-format", "stream-json",
               "--output-format", "stream-json",
               "--verbose",
               "--include-partial-messages",
               "--model", model,
               "--system-prompt", self.cfg["system_prompt"]]
        if not self.compat:
            cmd += ["--tools=", "--no-session-persistence", "--strict-mcp-config"]
            if effort and effort != "auto":
                cmd += ["--effort", effort]
        return cmd

    def _spawn(self, key):
        flags = NO_WINDOW  # без мигающей консоли
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)  # только вход через CLI, не API-ключ
        return subprocess.Popen(
            self._cmd(key),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=os.path.expanduser("~"), env=env, creationflags=flags,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )

    def prewarm(self, keys=None):
        if keys is not None:
            self.wanted = [tuple(k) for k in keys]
        if not self.exe or not self.cfg.get("prewarm", True):
            return
        def _do():
            with self.lock:
                for k in list(self.warm):          # лишние (старые настройки) — закрыть
                    p = self.warm[k]
                    if k not in self.wanted or p.poll() is not None:
                        if p.poll() is None:
                            p.kill()
                        del self.warm[k]
                for k in self.wanted:
                    if k not in self.warm:
                        try:
                            self.warm[k] = self._spawn(k)
                        except Exception:
                            pass
        threading.Thread(target=_do, daemon=True).start()

    def restart(self):
        """После установки CLI / входа: найти claude заново и перезапустить прогретые процессы."""
        self.exe = find_claude()
        self.compat = False
        with self.lock:
            for p in self.warm.values():
                if p.poll() is None:
                    p.kill()
            self.warm = {}
        self.prewarm()

    def kill_all(self):
        self.cancel()
        with self.lock:
            for p in self.warm.values():
                if p.poll() is None:
                    p.kill()
            self.warm = {}

    def cancel(self):
        p = self.current
        self.current = None
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def ask(self, png_bytes, question_text, key):
        """png_bytes=None — текстовый (голосовой) вопрос без картинки."""
        if not self.exe:
            self.events.put(("error", "Claude CLI не найден. Откройте Ctrl+Shift+M → «Установить CLI и войти»."))
            return
        self.cancel()
        self.run_id += 1
        rid = self.run_id
        threading.Thread(target=self._run, args=(rid, png_bytes, question_text, tuple(key), False), daemon=True).start()

    def _run(self, rid, png_bytes, question_text, key, is_retry):
        with self.lock:
            p = self.warm.pop(key, None)
            if p is not None and p.poll() is not None:
                p = None
        if p is None:
            try:
                p = self._spawn(key)
            except Exception as e:
                self.events.put(("error", f"Не удалось запустить claude: {e}"))
                return
        self.current = p

        content = []
        if png_bytes:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.b64encode(png_bytes).decode("ascii")}})
        content.append({"type": "text", "text": question_text})
        msg = {"type": "user", "message": {"role": "user", "content": content}}
        try:
            p.stdin.write(json.dumps(msg) + "\n")
            p.stdin.flush()
            p.stdin.close()
        except Exception:
            pass  # процесс мог упасть — разберёмся по stderr ниже

        got_text = False
        got_error = False
        try:
            for line in p.stdout:
                if rid != self.run_id:
                    break
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                t = o.get("type")
                if t == "stream_event":
                    ev = o.get("event", {})
                    if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                        got_text = True
                        self.events.put(("delta", ev["delta"]["text"]))
                elif t == "assistant" and o.get("message", {}).get("model") == "<synthetic>":
                    continue  # служебное сообщение CLI об ошибке — придёт в result
                elif t == "assistant" and not got_text:
                    # CLI без стриминга частичных сообщений — берём целиком
                    for c in o.get("message", {}).get("content", []):
                        if c.get("type") == "text":
                            got_text = True
                            self.events.put(("delta", c["text"]))
                elif t == "result":
                    if o.get("is_error") and not got_text:
                        msg = str(o.get("result") or "Ошибка Claude")
                        if "selected model" in msg or "model" in msg.lower() and "not exist" in msg.lower():
                            self.events.put(("model_rejected", key[0]))
                            msg = (f"Твой Claude CLI не принял модель {model_label(key[0])}. "
                                   "Выбери другую версию: Ctrl+Shift+M.\n\n" + msg)
                        self.events.put(("error", msg))
                        got_error = True
                    break
        finally:
            if rid == self.run_id:
                if p.poll() is None:
                    # ответ уже получен — служебный хвост не ждём
                    threading.Timer(5, lambda: p.poll() is None and p.kill()).start()
                if got_error:
                    pass
                elif not got_text:
                    err = ""
                    try:
                        p.wait(timeout=5)
                        err = (p.stderr.read() or "").strip()
                    except Exception:
                        pass
                    low = err.lower()
                    if not is_retry and not self.compat and ("unknown option" in low or "error: option" in low):
                        self.compat = True
                        self._run(rid, png_bytes, question_text, key, True)
                        return
                    if "login" in low or "auth" in low or "401" in low:
                        err = "Нужно войти: Ctrl+Shift+M → «Войти».\n\n" + err
                    self.events.put(("error", err[:800] or "Claude не ответил."))
                else:
                    self.events.put(("done", None))
                self.current = None
                self.prewarm()


# --------------------------------------------------------------------------- #
#  Окно ответа (правый верхний угол)
# --------------------------------------------------------------------------- #

class AnswerBox:
    def __init__(self, root, cfg):
        self.cfg = cfg
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", cfg["box_alpha"])
        self.win.configure(bg=cfg["box_bg"])
        font = tuple(cfg["font"])
        self.text = tk.Text(self.win, bg=cfg["box_bg"], fg=cfg["box_fg"], font=font,
                            wrap="word", bd=0, highlightthickness=0, padx=9, pady=7,
                            cursor="arrow", insertwidth=0)
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("dim", foreground="#8a8a8a")
        self.raw = ""
        self.header = ""
        self.hide_job = None
        self.line_h = tkfont.Font(font=font).metrics("linespace")
        self.win.geometry(f"{cfg['box_width']}x40+0+0")
        # ЛКМ — скрыть, ПКМ — скопировать ответ, колесо — прокрутка
        self.action = None  # если задано — клик по окну выполняет действие (например, обновление)
        self.text.bind("<Button-1>", lambda e: self._click())
        self.text.bind("<Button-3>", self._copy)
        self._no_activate()

    def _no_activate(self):
        """Окно не забирает фокус у активного приложения и не появляется в Alt+Tab."""
        try:
            self.win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x80, 0x08000000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        except Exception:
            pass

    def _copy(self, _e=None):
        self.win.clipboard_clear()
        self.win.clipboard_append(strip_markdown(self.raw).strip())

    def _place(self):
        c = self.cfg
        w = c["box_width"]
        wa = work_area()
        if wa:
            right, top = wa[2], wa[1]
        else:
            right, top = self.win.winfo_screenwidth(), 0
        x = right - w - c["box_margin"]
        y = top + c["box_margin"]
        # ширина постоянная, считаем строки после переноса и подгоняем высоту
        self.win.update_idletasks()
        try:
            cnt = self.text.count("1.0", "end", "displaylines")
            lines = int(cnt[0] if isinstance(cnt, tuple) else cnt or 1)
        except Exception:
            lines = 1
        h = min(c["box_max_height"], max(30, lines * self.line_h + 16))
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.text.see("end")

    def _click(self):
        fn, self.action = self.action, None
        if fn:
            fn()
        else:
            self.hide()

    def offer(self, text, fn):
        """Показать сообщение, клик по которому выполняет fn."""
        self.error(text)
        self.action = fn

    def show_status(self, status, header=""):
        self.action = None
        self.raw = ""
        self.header = header
        self._set(status, dim=True)
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self._place()

    def append(self, chunk):
        self.raw += chunk
        self._set(strip_markdown(self.raw))
        self._place()

    def error(self, msg):
        self.action = None
        self.raw = msg
        self.header = ""
        self._set(msg)
        self.win.deiconify()
        self._place()

    def finish(self):
        s = self.cfg.get("auto_hide_seconds", 0)
        if s:
            if self.hide_job:
                self.win.after_cancel(self.hide_job)
            self.hide_job = self.win.after(int(s * 1000), self.hide)

    def _set(self, txt, dim=False):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if self.header:
            self.text.insert("1.0", self.header + "\n\n", ("dim",))
        self.text.insert("end", txt, ("dim",) if dim else ())
        self.text.configure(state="disabled")

    def hide(self):
        self.win.withdraw()

    def visible(self):
        return self.win.state() == "normal"


# --------------------------------------------------------------------------- #
#  Выделение области
# --------------------------------------------------------------------------- #

class RegionSelector:
    def __init__(self, root, on_done):
        self.root = root
        self.on_done = on_done

    def start(self):
        with mss.mss() as sct:
            mon = sct.monitors[0]  # весь виртуальный экран (все мониторы)
            shot = sct.grab(mon)
        self.left, self.top = mon["left"], mon["top"]
        self.full = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        dim = ImageEnhance.Brightness(self.full).enhance(0.6)

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
        self.canvas = tk.Canvas(self.win, highlightthickness=0, cursor="crosshair",
                                width=mon["width"], height=mon["height"])
        self.canvas.pack(fill="both", expand=True)
        self.photo = ImageTk.PhotoImage(dim)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.rect = None
        self.start_xy = None
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", lambda e: self._cancel())
        self.win.bind("<Escape>", lambda e: self._cancel())
        self.win.focus_force()
        self.win.after(50, self.win.focus_force)

    def _press(self, e):
        self.start_xy = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#d0d0d0", width=1, dash=(4, 2))

    def _drag(self, e):
        if self.rect:
            x0, y0 = self.start_xy
            self.canvas.coords(self.rect, x0, y0, e.x, e.y)

    def _release(self, e):
        if not self.start_xy:
            return
        x0, y0 = self.start_xy
        x1, y1 = e.x, e.y
        l, t, r, b = min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
        self.win.destroy()
        if r - l < 8 or b - t < 8:
            self.on_done(None)
            return
        self.on_done(self.full.crop((l, t, r, b)))

    def _cancel(self):
        self.win.destroy()
        self.on_done(None)


# --------------------------------------------------------------------------- #
#  Голосовой ввод
# --------------------------------------------------------------------------- #

class MicIcon:
    """Крошечный значок микрофона в правом нижнем углу, пока идёт запись."""

    SIZE = 16

    def __init__(self, root, cfg):
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        key = "#010203"  # цвет фона делаем прозрачным — виден только значок
        self.win.configure(bg=key)
        try:
            self.win.attributes("-transparentcolor", key)
        except tk.TclError:
            pass
        n = self.SIZE
        cv = tk.Canvas(self.win, width=n, height=n, bg=key, highlightthickness=0)
        cv.pack()
        col = cfg["mic_icon_color"]
        cv.create_oval(5, 1, 11, 7, fill=col, outline=col)          # капсула
        cv.create_rectangle(5, 4, 11, 9, fill=col, outline=col)
        cv.create_oval(5, 6, 11, 11, fill=col, outline=col)
        cv.create_arc(3, 3, 13, 13, start=180, extent=180, style="arc", outline=col, width=1.5)
        cv.create_line(8, 13, 8, 15, fill=col, width=1.5)           # ножка
        cv.create_line(5, 15, 11, 15, fill=col, width=1.5)
        AnswerBox._no_activate(self)

    def show(self):
        wa = work_area()
        if wa:
            right, bottom = wa[2], wa[3]
        else:
            right, bottom = self.win.winfo_screenwidth(), self.win.winfo_screenheight() - 40
        x, y = right - self.SIZE - 6, bottom - self.SIZE - 6
        self.win.geometry(f"{self.SIZE}x{self.SIZE}+{x}+{y}")
        self.win.deiconify()
        self.win.attributes("-topmost", True)

    def hide(self):
        self.win.withdraw()


class VoiceInput:
    """Запись с микрофона (sounddevice) + локальное распознавание (faster-whisper)."""

    RATE = 16000

    def __init__(self, cfg):
        self.cfg = cfg
        self.stream = None
        self.chunks = []
        self.started = 0.0
        self.model = None
        self.model_error = None
        self.status = None  # текст для пользователя, пока модель скачивается
        threading.Thread(target=self._load_model, daemon=True).start()

    REPOS = {"tiny": "Systran/faster-whisper-tiny", "base": "Systran/faster-whisper-base",
             "small": "Systran/faster-whisper-small", "medium": "Systran/faster-whisper-medium"}
    FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]

    def _model_dir(self):
        """Скачать модель в %APPDATA%\\ClaudeGhost\\models\\<name> обычными файлами.

        Кэш Hugging Face на Windows держит файлы через симлинки, и собранный .exe
        иногда не может открыть model.bin оттуда — поэтому используем свою папку."""
        name = self.cfg["whisper_model"]
        if os.path.isdir(name):          # в настройках указан путь к своей модели
            return name
        path = os.path.join(DATA_DIR, "models", name)
        mb = os.path.join(path, "model.bin")
        if os.path.isfile(mb) and os.path.getsize(mb) > 1_000_000:
            return path
        from huggingface_hub import snapshot_download
        shutil.rmtree(path, ignore_errors=True)
        self.status = "Скачиваю модель распознавания речи (один раз, ~150 МБ)…"
        snapshot_download(self.REPOS.get(name, name), local_dir=path, allow_patterns=self.FILES)
        return path

    def _load_model(self):
        for attempt in (1, 2):
            try:
                from faster_whisper import WhisperModel
                path = self._model_dir()
                self.model = WhisperModel(path, device="cpu", compute_type="int8")
                self.model_error = None
                break
            except Exception as e:
                if attempt == 2:
                    self.model_error = str(e)
                print("whisper model:", e, file=sys.stderr)
                # битая/недокачанная модель — удаляем и качаем заново (один раз)
                shutil.rmtree(os.path.join(DATA_DIR, "models", self.cfg["whisper_model"]),
                              ignore_errors=True)
        self.status = None

    @property
    def recording(self):
        return self.stream is not None

    def start(self):
        import sounddevice as sd
        self.chunks = []
        self.started = time.time()
        self.stream = sd.InputStream(samplerate=self.RATE, channels=1, dtype="float32",
                                     callback=lambda data, *_: self.chunks.append(data.copy()))
        self.stream.start()

    def too_long(self):
        return self.recording and time.time() - self.started > self.cfg["voice_max_seconds"]

    def stop(self):
        import numpy as np
        s, self.stream = self.stream, None
        if s:
            s.stop()
            s.close()
        if not self.chunks:
            return None
        return np.concatenate(self.chunks)[:, 0]

    def transcribe(self, audio):
        """Блокирующий вызов — запускать в отдельном потоке."""
        t0 = time.time()
        while self.model is None and self.model_error is None and time.time() - t0 < 300:
            time.sleep(0.1)  # модель ещё грузится (первый раз — скачивается)
        if self.model is None:
            raise RuntimeError("Распознавание речи недоступно: " + (self.model_error or "модель не загрузилась"))
        segments, _ = self.model.transcribe(audio, language=self.cfg.get("voice_language") or None,
                                            beam_size=1, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip()


# --------------------------------------------------------------------------- #
#  Обновления через GitHub Releases
# --------------------------------------------------------------------------- #

def _ver(v):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


class Updater:
    """Проверяет последний релиз на GitHub; если версия новее — скачивает и
    запускает установщик поверх текущей версии (настройки сохраняются)."""

    API = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
    ASSET = "ClaudeGhost-Setup.exe"

    def __init__(self, events):
        self.events = events  # ("update", (version, url)) / ("update_progress", str) / ("update_error", str) / ("update_ready", path)

    def _get(self, url, timeout=15):
        req = urllib.request.Request(url, headers={"User-Agent": "ClaudeGhost-Updater",
                                                   "Accept": "application/vnd.github+json"})
        return urllib.request.urlopen(req, timeout=timeout)

    def check_async(self):
        def _do():
            try:
                with self._get(self.API) as r:
                    rel = json.load(r)
                tag = rel.get("tag_name", "")
                if rel.get("draft") or rel.get("prerelease") or _ver(tag) <= _ver(__version__):
                    return
                for a in rel.get("assets", []):
                    if a.get("name") == self.ASSET:
                        self.events.put(("update", (tag.lstrip("vV"), a["browser_download_url"])))
                        return
            except Exception as e:  # нет сети / репозиторий приватный / нет релизов — молча
                print("update check:", e, file=sys.stderr)
        threading.Thread(target=_do, daemon=True).start()

    def download_async(self, url):
        def _do():
            try:
                path = os.path.join(tempfile.gettempdir(), self.ASSET)
                with self._get(url, timeout=60) as r, open(path, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    done, last = 0, 0
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if total and done * 100 // total >= last + 5:
                            last = done * 100 // total
                            self.events.put(("update_progress", f"Скачиваю обновление… {last}%"))
                self.events.put(("update_ready", path))
            except Exception as e:
                self.events.put(("update_error", f"Не удалось скачать обновление: {e}"))
        threading.Thread(target=_do, daemon=True).start()

    @staticmethod
    def install(path):
        """Тихая установка поверх текущей версии; установщик сам запустит новую версию."""
        subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                         close_fds=True)


# --------------------------------------------------------------------------- #
#  Оверлей выбора модели и effort
# --------------------------------------------------------------------------- #

MODELS = [("auto", "Auto"), ("haiku", "Haiku"), ("sonnet", "Sonnet"), ("opus", "Opus"), ("fable", "Fable")]
# Версии внутри семейства. "latest" — алиас CLI (самая новая версия).
# Версию, которую CLI отклонит, программа запомнит и пометит ✕.
VERSIONS = {
    "opus": [("latest", "новейшая"), ("claude-opus-5-5", "5.5"), ("claude-opus-5", "5"),
             ("claude-opus-4-8", "4.8"), ("claude-opus-4-7", "4.7"), ("claude-opus-4-6", "4.6"),
             ("claude-opus-4-5", "4.5")],
    "sonnet": [("latest", "новейшая"), ("claude-sonnet-5-5", "5.5"), ("claude-sonnet-5", "5"),
               ("claude-sonnet-4-6", "4.6"), ("claude-sonnet-4-5", "4.5")],
    "haiku": [("latest", "новейшая"), ("claude-haiku-5-5", "5.5"), ("claude-haiku-4-5", "4.5")],
    "fable": [("latest", "новейшая"), ("claude-fable-5-2", "5.2"), ("claude-fable-5", "5")],
}


def model_label(model):
    """'claude-opus-4-7' -> 'Opus 4.7', 'sonnet' -> 'Sonnet'."""
    m = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d))?(?:-\d{8})?$", model)
    if m:
        return f"{m.group(1).capitalize()} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")
    return model.capitalize()
EFFORTS = [("auto", "Auto"), ("low", "low"), ("medium", "medium"), ("high", "high"),
           ("xhigh", "xhigh"), ("max", "max")]


class SettingsOverlay:
    """Маленькая панель в правом верхнем углу: модель и effort.

    Мышь: клик по варианту. Клавиатура: ←/→ — модель, ↑/↓ — effort,
    Enter / Esc / та же комбинация — закрыть. Выбор сохраняется сразу.
    """

    def __init__(self, root, cfg, on_change, account):
        self.root = root
        self.cfg = cfg
        self.on_change = on_change
        self.account = account
        self.win = None

    def is_open(self):
        return self.win is not None

    def toggle(self):
        self.close() if self.win else self.open()

    def open(self):
        c = self.cfg
        bg, fg = c["box_bg"], c["box_fg"]
        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", min(1.0, c["box_alpha"] + 0.07))
        self.win.configure(bg=bg)
        font = tuple(c["font"])
        small = (c["font"][0], max(8, int(c["font"][1]) - 1))
        frame = tk.Frame(self.win, bg=bg, padx=12, pady=10)
        frame.pack(fill="both", expand=True)
        self.buttons = {"model": {}, "effort": {}}
        for row, (title, field, items) in enumerate([("Модель", "model", MODELS),
                                                     ("Effort", "effort", EFFORTS)]):
            tk.Label(frame, text=title, bg=bg, fg="#8a8a8a", font=small).grid(
                row=row * 2, column=0, sticky="w", pady=(0 if row == 0 else 8, 3))
            line = tk.Frame(frame, bg=bg)
            line.grid(row=row * 2 + 1, column=0, sticky="w")
            for value, label in items:
                b = tk.Label(line, text=label, font=font, padx=8, pady=2, cursor="hand2")
                b.pack(side="left", padx=(0, 4))
                b.bind("<Button-1>", lambda e, f=field, v=value: self._set(f, v))
                self.buttons[field][value] = b
        self.font, self.small = font, small
        self.ver_title = tk.Label(frame, text="Версия", bg=bg, fg="#8a8a8a", font=small)
        self.ver_line = tk.Frame(frame, bg=bg)
        self.ver_family = None
        self.ver_buttons = {}
        self.hint = tk.Label(frame, text="", bg=bg, fg="#8a8a8a", font=small, justify="left")
        self.hint.grid(row=4, column=0, sticky="w", pady=(8, 0))
        # --- аккаунт Claude ---
        tk.Frame(frame, bg="#444444", height=1).grid(row=5, column=0, sticky="we", pady=(10, 8))
        acc = tk.Frame(frame, bg=bg)
        acc.grid(row=6, column=0, sticky="we")
        self.acc_label = tk.Label(acc, text="", bg=bg, fg="#b0b0b0", font=small, justify="left")
        self.acc_label.pack(side="left")
        self.acc_btn = tk.Label(acc, text="", font=small, padx=8, pady=2, cursor="hand2",
                                bg="#4a4a4a", fg="#ffffff")
        self.acc_btn.pack(side="right", padx=(10, 0))
        self.acc_btn.bind("<Button-1>", lambda e: self._account_action())
        self._acc_shown = None
        self._refresh()
        self._refresh_account()
        self.account.check_async()

        self.win.bind("<Escape>", lambda e: self.close())
        self.win.bind("<Return>", lambda e: self.close())
        self.win.bind("<Left>", lambda e: self._step("model", MODELS, -1))
        self.win.bind("<Right>", lambda e: self._step("model", MODELS, 1))
        self.win.bind("<Up>", lambda e: self._step("effort", EFFORTS, -1))
        self.win.bind("<Down>", lambda e: self._step("effort", EFFORTS, 1))
        self.win.bind("<Tab>", lambda e: (self._step_version(1), "break")[1])
        self.win.bind("<Shift-Tab>", lambda e: (self._step_version(-1), "break")[1])

        self._reposition()
        self.win.focus_force()
        self.win.after(50, self.win.focus_force)

    def close(self):
        if self.win:
            self.win.destroy()
            self.win = None

    def _account_action(self):
        _, fn = self.account.action()
        if fn:
            fn()
            self._refresh_account()

    def _refresh_account(self):
        """Перерисовать блок аккаунта; пока панель открыта — проверяем изменения раз в 300 мс."""
        if not self.win:
            return
        label, fn = self.account.action()
        state = (self.account.status_text(), label)
        if state != self._acc_shown:
            self._acc_shown = state
            self.acc_label.configure(text=state[0])
            if label:
                self.acc_btn.configure(text=label)
                self.acc_btn.pack(side="right", padx=(10, 0))
            else:
                self.acc_btn.pack_forget()
            self._reposition()
        self.win.after(300, self._refresh_account)

    def _reposition(self):
        c = self.cfg
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        wa = work_area()
        right, top = (wa[2], wa[1]) if wa else (self.win.winfo_screenwidth(), 0)
        self.win.geometry(f"{w}x{h}+{right - w - c['box_margin']}+{top + c['box_margin']}")

    def _step(self, field, items, d):
        values = [v for v, _ in items]
        i = values.index(self.cfg[field]) if self.cfg[field] in values else 0
        self._set(field, values[(i + d) % len(values)])

    def _set(self, field, value):
        self.cfg[field] = value
        save_settings({field: value})
        self._refresh()
        self._reposition()
        self.on_change()

    def _set_version(self, family, value):
        versions = dict(self.cfg.get("versions") or {})
        versions[family] = value
        self.cfg["versions"] = versions
        bad = [m for m in (self.cfg.get("unavailable_models") or []) if m != value]
        self.cfg["unavailable_models"] = bad   # выбрал снова — попробуем ещё раз
        save_settings({"versions": versions, "unavailable_models": bad})
        self._refresh()
        self._reposition()
        self.on_change()

    def _step_version(self, d):
        fam = self.cfg["model"]
        if fam not in VERSIONS:
            return
        values = [v for v, _ in VERSIONS[fam]]
        cur = (self.cfg.get("versions") or {}).get(fam, "latest")
        i = values.index(cur) if cur in values else 0
        self._set_version(fam, values[(i + d) % len(values)])

    def _build_versions(self, fam):
        """Строка версий для выбранного семейства (пересоздаётся при смене модели)."""
        for w in self.ver_line.winfo_children():
            w.destroy()
        self.ver_buttons = {}
        self.ver_family = fam
        if fam not in VERSIONS:
            self.ver_title.grid_remove()
            self.ver_line.grid_remove()
            return
        self.ver_title.grid(row=2, column=0, sticky="w", pady=(8, 3))
        self.ver_line.grid(row=3, column=0, sticky="w")
        for value, label in VERSIONS[fam]:
            b = tk.Label(self.ver_line, text=label, font=self.font, padx=6, pady=2, cursor="hand2")
            b.pack(side="left", padx=(0, 3))
            b.bind("<Button-1>", lambda e, f=fam, v=value: self._set_version(f, v))
            self.ver_buttons[value] = b

    def _refresh(self):
        c = self.cfg
        if c["model"] != self.ver_family:
            self._build_versions(c["model"])
        bad = set(c.get("unavailable_models") or [])
        cur = (c.get("versions") or {}).get(c["model"], "latest")
        for value, b in self.ver_buttons.items():
            on = value == cur
            label = dict(VERSIONS[c["model"]])[value]
            b.configure(text=label + (" ✕" if value in bad else ""),
                        bg="#4a4a4a" if on else c["box_bg"],
                        fg="#e07070" if value in bad else ("#ffffff" if on else "#b0b0b0"))
        for field, btns in self.buttons.items():
            for value, b in btns.items():
                on = c[field] == value
                b.configure(bg="#4a4a4a" if on else c["box_bg"],
                            fg="#ffffff" if on else "#b0b0b0")
        if c["model"] == "auto":
            f, s = c["auto_fast"], c["auto_strong"]
            hint = (f"Auto: простые вопросы → {f[0]} ({f[1]}),\n"
                    f"сложные → {s[0]} ({s[1]})")
            if c["effort"] != "auto":
                hint += f"\neffort для обеих: {c['effort']}"
        else:
            hint = "Effort Auto = по умолчанию для модели. Tab — версия."
            if cur in bad:
                hint = "✕ — твой Claude CLI не принял эту версию.\n" + hint
        self.hint.configure(text=hint)


# --------------------------------------------------------------------------- #
#  Приложение
# --------------------------------------------------------------------------- #

class App:
    def __init__(self):
        set_dpi_aware()
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.withdraw()
        self.ui_events = queue.Queue()
        self.claude_events = queue.Queue()
        self.box = AnswerBox(self.root, self.cfg)
        self.runner = ClaudeRunner(self.cfg, self.claude_events)
        self.selecting = False
        self.mic = MicIcon(self.root, self.cfg)
        self.voice = VoiceInput(self.cfg)

        self.account = ClaudeAccount()
        self.account.on_change = lambda: self.ui_events.put("account")
        self._last_login = None
        self.settings = SettingsOverlay(self.root, self.cfg, self._settings_changed, self.account)
        keyboard.add_hotkey(self.cfg["settings_hotkey"], lambda: self.ui_events.put("settings"))
        keyboard.add_hotkey(self.cfg["voice_hotkey"], lambda: self.ui_events.put("voice"))
        keyboard.add_hotkey(self.cfg["hotkey"], lambda: self.ui_events.put("select"))
        keyboard.add_hotkey(self.cfg["hide_hotkey"], lambda: self.ui_events.put("hide"))
        keyboard.add_hotkey(self.cfg["quit_hotkey"], lambda: self.ui_events.put("quit"))

        self.runner.prewarm(self._warm_keys())
        if not self.runner.exe:
            self.box.error("Claude Ghost: Claude CLI не установлен.\n"
                           "Нажмите Ctrl+Shift+M → «Установить CLI и войти».")
        self.account.check_async()
        self.updater = Updater(self.claude_events)
        if FROZEN and self.cfg.get("check_updates", True):
            self.root.after(8000, self.updater.check_async)  # не мешаем старту
        self.root.after(30, self._poll)

    def _offer_update(self, version, url):
        def install():
            self.box.show_status("Скачиваю обновление…")
            self.updater.download_async(url)
        self.box.offer(f"Доступна новая версия Claude Ghost {version} (у вас {__version__}).\n\n"
                       "Кликните сюда, чтобы обновить. Ctrl+Shift+H — позже.", install)

    def _poll(self):
        try:
            while True:
                ev = self.ui_events.get_nowait()
                if ev == "select" and not self.selecting:
                    self.selecting = True
                    self.box.hide()
                    self.root.after(60, self._start_select)  # дать окну ответа исчезнуть
                elif ev == "account":
                    # после установки CLI / входа — перезапустить прогретые процессы
                    if not self.account.busy and self.account.logged_in and self._last_login is False:
                        self.runner.restart()
                        self.box.hide()
                    if self.account.logged_in is False and self._last_login is None \
                            and not self.account.busy and self.runner.exe:
                        self.box.error("Claude Ghost: вход в Claude не выполнен.\n"
                                       "Нажмите Ctrl+Shift+M → «Войти».")
                    if self.account.logged_in is not None:
                        self._last_login = self.account.logged_in
                elif ev == "settings":
                    self.box.hide()
                    self.settings.toggle()
                elif ev == "voice":
                    self._toggle_voice()
                elif ev == "hide":
                    self.box.hide()
                elif ev == "quit":
                    self.quit()
                    return
        except queue.Empty:
            pass
        try:
            while True:
                kind, data = self.claude_events.get_nowait()
                if kind == "delta":
                    self.box.append(data)
                elif kind == "model_rejected":
                    bad = list(self.cfg.get("unavailable_models") or [])
                    if data not in bad:
                        bad.append(data)
                        self.cfg["unavailable_models"] = bad
                        save_settings({"unavailable_models": bad})
                    with self.runner.lock:  # прогретый процесс с этой моделью бесполезен
                        for k in [k for k in self.runner.warm if k[0] == data]:
                            p = self.runner.warm.pop(k)
                            if p.poll() is None:
                                p.kill()
                elif kind == "update":
                    self._offer_update(*data)
                elif kind == "update_progress":
                    self.box.show_status(data)
                elif kind == "update_error":
                    self.box.error(data)
                elif kind == "update_ready":
                    self.box.show_status("Устанавливаю обновление, программа перезапустится…")
                    Updater.install(data)
                    self.root.after(1500, self.quit)
                    return
                elif kind == "header":
                    self.box.show_status("…", header=data)
                elif kind == "done":
                    self.box.finish()
                elif kind == "error":
                    self.box.error(data)
        except queue.Empty:
            pass
        if self.voice.too_long():
            self._toggle_voice()
        self.root.after(30, self._poll)

    # ---- выбор модели ----------------------------------------------------

    def _settings_changed(self):
        self.runner.prewarm(self._warm_keys())

    def _warm_keys(self):
        c = self.cfg
        if c["model"] == "auto":
            keys = [self._key(c["auto_fast"]), self._key(c["auto_strong"])]
        else:
            keys = [(self._resolve(c["model"]), c["effort"])]
        return list(dict.fromkeys(keys))

    def _resolve(self, family):
        """Семейство -> конкретная версия из настроек ('latest' = алиас CLI)."""
        v = (self.cfg.get("versions") or {}).get(family, "latest")
        return family if v in ("latest", "", None) else v

    def _key(self, pair):
        """Пара из Auto-режима; effort из настроек важнее, если он не auto."""
        model, effort = pair
        if self.cfg["effort"] != "auto":
            effort = self.cfg["effort"]
        return (model, effort)

    def _pick(self, text=None, image_area=0):
        """Выбор (модель, effort). В режиме Auto — по сложности вопроса."""
        c = self.cfg
        if c["model"] != "auto":
            return (self._resolve(c["model"]), c["effort"])
        hard = False
        if image_area and image_area > c["auto_image_area"]:
            hard = True
        if text:
            low = text.lower()
            if len(text) > c["auto_text_chars"] or any(w in low for w in c["auto_hard_words"]):
                hard = True
        return self._key(c["auto_strong"] if hard else c["auto_fast"])

    @staticmethod
    def _tag(key):
        model, effort = key
        return model_label(model) + ("" if effort == "auto" else f" · {effort}")

    def _toggle_voice(self):
        if not self.voice.recording:
            try:
                self.voice.start()
            except Exception as e:
                self.box.error(f"Микрофон недоступен: {e}")
                return
            self.mic.show()
            return
        audio = self.voice.stop()
        self.mic.hide()
        if audio is None or len(audio) < VoiceInput.RATE * 0.3:
            return
        self.box.show_status("Распознаю речь…")

        def work():
            if self.voice.model is None and self.voice.status:
                self.claude_events.put(("update_progress", self.voice.status))
            try:
                text = self.voice.transcribe(audio)
            except Exception as e:
                self.claude_events.put(("error", str(e)))
                return
            if not text:
                self.claude_events.put(("error", "Не расслышал вопрос."))
                return
            key = self._pick(text=text)
            self.claude_events.put(("header", f"{self._tag(key)}\n🎤 {text}"))
            self.runner.ask(None, "Голосовой вопрос: " + text, key)
        threading.Thread(target=work, daemon=True).start()

    def _start_select(self):
        try:
            RegionSelector(self.root, self._on_region).start()
        except Exception as e:
            self.selecting = False
            self.box.error(f"Ошибка захвата экрана: {e}")

    def _on_region(self, img):
        self.selecting = False
        if img is None:
            return
        key = self._pick(image_area=img.size[0] * img.size[1])
        m = self.cfg["max_image_side"]
        if max(img.size) > m:
            img.thumbnail((m, m), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        self.box.show_status("…", header=self._tag(key))
        self.runner.ask(buf.getvalue(), "Ответь на вопрос на картинке.", key)

    def quit(self):
        if self.voice.recording:
            self.voice.stop()
        self.settings.close()
        self.runner.kill_all()
        keyboard.unhook_all()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def selftest():
    """Проверка сборки .exe в CI: все зависимости упакованы и импортируются."""
    try:
        import numpy, sounddevice, ctranslate2, faster_whisper  # noqa: F401
        from faster_whisper.vad import get_vad_model  # noqa: F401
        tk.Tk().destroy()
        msg, code = "OK " + __version__, 0
    except Exception as e:
        msg, code = f"FAIL {type(e).__name__}: {e}", 1
    with open(os.path.join(DATA_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write(msg)
    sys.exit(code)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    # один экземпляр программы
    if os.name == "nt":
        ctypes.windll.kernel32.CreateMutexW(None, False, "ClaudeGhostSingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            sys.exit(0)
    App().run()
