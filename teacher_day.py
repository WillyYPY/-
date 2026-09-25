# -*- coding: utf-8 -*-
"""
教师节祝福程序 - Windows 后台静默运行
功能：
  1. 检测 U 盘插入，自动全屏显示教师节祝福网页
  2. 5 秒内按 3 下翻页笔下键（默认 Page Down）手动触发
  3. 显示指定秒数后自动关闭全屏，恢复静默运行
依赖：pywin32, pynput, pystray, Pillow
"""

import os
import sys
import json
import time
import shutil
import logging
import tempfile
import threading
import subprocess
import webbrowser
from pathlib import Path

# ====================== 依赖导入 ======================
try:
    import win32api
    import win32file
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ====================== 路径与配置 ======================
def app_dir():
    """获取程序所在目录（兼容 PyInstaller 打包）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR = app_dir()
CONFIG_PATH = BASE_DIR / "config.json"
HTML_PATH = BASE_DIR / "greeting.html"
LOG_PATH = BASE_DIR / "teacher_day.log"

DEFAULT_CONFIG = {
    "display_duration": 10,       # 全屏显示时长（秒）
    "hotkey": "page_down",        # 触发按键：page_down / down / right / space
    "hotkey_count": 3,            # 需要按的次数
    "hotkey_window": 5,           # 时间窗口（秒）
    "browser": "edge",            # edge / chrome / default
    "usb_detect": True,           # 是否启用 U 盘自动触发
    "manual_trigger": True,       # 是否启用手动热键触发
    "tray_icon": True,            # 是否显示系统托盘图标
    "poll_interval": 2,           # U 盘轮询间隔（秒）
    "usb_cooldown": 8,            # U 盘触发冷却时间（秒），避免重复触发
    "log_enabled": True
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            cfg.update(user_cfg)
        except Exception as e:
            print(f"[警告] 配置文件读取失败，使用默认配置: {e}")
    else:
        # 首次运行写入默认配置
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return cfg

# ====================== 日志 ======================
def setup_logging(enabled):
    if not enabled:
        logging.disable(logging.CRITICAL)
        return
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8"
    )

# ====================== 浏览器路径与命令 ======================
def get_browser_path(browser_name):
    """查找浏览器可执行文件路径"""
    if browser_name == "edge":
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    elif browser_name == "chrome":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    else:
        candidates = []
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def build_kiosk_cmd(browser_path, url, user_data_dir):
    """构建浏览器 kiosk 全屏命令"""
    name = os.path.basename(browser_path).lower()
    if "edge" in name:
        return [
            browser_path,
            "--kiosk", url,
            "--edge-kiosk-type=fullscreen",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            f"--user-data-dir={user_data_dir}",
        ]
    else:  # chrome / chromium
        return [
            browser_path,
            "--kiosk", url,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            f"--user-data-dir={user_data_dir}",
        ]

# ====================== 祝福显示管理 ======================
class GreetingManager:
    """管理全屏祝福的显示与关闭"""

    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()
        self._showing = False
        self._proc = None
        self._timer = None
        self._user_data_dir = None

    @property
    def is_showing(self):
        return self._showing

    def _get_url(self):
        path = str(HTML_PATH.resolve())
        # file:/// URL
        url = "file:///" + path.replace("\\", "/")
        return url

    def show(self):
        """显示全屏祝福"""
        with self._lock:
            if self._showing:
                logging.info("祝福正在显示中，忽略重复触发")
                return False
            self._showing = True

        try:
            url = self._get_url()
            browser = self.config.get("browser", "edge")
            browser_path = get_browser_path(browser)

            if browser_path is None:
                # 回退：用默认浏览器打开（可能无法真正全屏）
                logging.warning(f"未找到 {browser}，尝试用默认浏览器打开")
                webbrowser.open(url)
                self._schedule_close()
                return True

            # 创建临时用户数据目录，确保独立进程，便于关闭
            self._user_data_dir = tempfile.mkdtemp(prefix="td_kiosk_")
            cmd = build_kiosk_cmd(browser_path, url, self._user_data_dir)

            logging.info(f"启动全屏祝福: {' '.join(cmd)}")
            creationflags = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW

            self._proc = subprocess.Popen(cmd, creationflags=creationflags)
            self._schedule_close()
            return True
        except Exception as e:
            logging.error(f"显示祝福失败: {e}", exc_info=True)
            with self._lock:
                self._showing = False
            return False

    def _schedule_close(self):
        """定时关闭全屏"""
        duration = self.config.get("display_duration", 10)
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(duration, self.hide)
        self._timer.daemon = True
        self._timer.start()
        logging.info(f"将在 {duration} 秒后自动关闭全屏")

    def hide(self):
        """关闭全屏祝福"""
        with self._lock:
            if not self._showing:
                return
            self._showing = False

        if self._timer:
            self._timer.cancel()
            self._timer = None

        if self._proc is not None:
            pid = self._proc.pid
            logging.info(f"关闭全屏进程 PID={pid}")
            try:
                # 先尝试优雅终止进程树
                creationflags = 0
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creationflags = subprocess.CREATE_NO_WINDOW
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    creationflags=creationflags,
                    timeout=5
                )
            except Exception as e:
                logging.warning(f"taskkill 失败，尝试直接 terminate: {e}")
                try:
                    self._proc.terminate()
                except Exception:
                    pass
            self._proc = None

        # 清理临时用户数据目录
        if self._user_data_dir and os.path.exists(self._user_data_dir):
            try:
                # 稍等一下让进程完全退出
                time.sleep(0.5)
                shutil.rmtree(self._user_data_dir, ignore_errors=True)
            except Exception:
                pass
            self._user_data_dir = None

        logging.info("全屏已关闭，恢复静默运行")

# ====================== U 盘检测 ======================
class USBDetector(threading.Thread):
    """轮询检测可移动磁盘（U 盘）插入"""

    def __init__(self, config, on_insert):
        super().__init__(daemon=True)
        self.config = config
        self.on_insert = on_insert
        self._stop = threading.Event()
        self._last_drives = set()
        self._last_trigger_time = 0

    def get_removable_drives(self):
        drives = set()
        if not HAS_WIN32:
            return drives
        try:
            bitmask = win32api.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    drive = chr(65 + i) + ":\\"
                    try:
                        if win32file.GetDriveType(drive) == win32file.DRIVE_REMOVABLE:
                            drives.add(drive)
                    except Exception:
                        continue
        except Exception as e:
            logging.error(f"获取驱动器列表失败: {e}")
        return drives

    def run(self):
        if not HAS_WIN32:
            logging.warning("未安装 pywin32，U 盘检测功能不可用")
            return
        # 初始化当前已存在的可移动盘（不触发）
        self._last_drives = self.get_removable_drives()
        logging.info(f"U 盘检测已启动，当前可移动盘: {self._last_drives}")

        interval = self.config.get("poll_interval", 2)
        cooldown = self.config.get("usb_cooldown", 8)

        while not self._stop.is_set():
            try:
                current = self.get_removable_drives()
                new_drives = current - self._last_drives
                self._last_drives = current

                if new_drives:
                    now = time.time()
                    if now - self._last_trigger_time >= cooldown:
                        self._last_trigger_time = now
                        logging.info(f"检测到新 U 盘: {new_drives}")
                        self.on_insert(new_drives)
                    else:
                        logging.info(f"U 盘插入但处于冷却期，忽略")
            except Exception as e:
                logging.error(f"U 盘检测异常: {e}")
            self._stop.wait(interval)

    def stop(self):
        self._stop.set()

# ====================== 热键检测（翻页笔） ======================
class HotkeyDetector:
    """检测 5 秒内按 3 下翻页笔下键"""

    def __init__(self, config, on_trigger):
        self.config = config
        self.on_trigger = on_trigger
        self._press_times = []
        self._listener = None
        self._lock = threading.Lock()

    def _get_key_map(self):
        """构建按键映射（仅在 pynput 可用时调用）"""
        return {
            "page_down": keyboard.Key.page_down,
            "page_up": keyboard.Key.page_up,
            "down": keyboard.Key.down,
            "up": keyboard.Key.up,
            "right": keyboard.Key.right,
            "left": keyboard.Key.left,
            "space": keyboard.Key.space,
            "enter": keyboard.Key.enter,
        }

    def _get_target_key(self):
        name = self.config.get("hotkey", "page_down").lower()
        return self._get_key_map().get(name, keyboard.Key.page_down)

    def start(self):
        if not HAS_PYNPUT:
            logging.warning("未安装 pynput，手动热键功能不可用")
            return
        target = self._get_target_key()
        logging.info(f"手动热键已启动: {self.config.get('hotkey_window')}秒内按 "
                     f"{self.config.get('hotkey')} {self.config.get('hotkey_count')} 次触发")

        def on_press(key):
            try:
                if key == target:
                    with self._lock:
                        now = time.time()
                        window = self.config.get("hotkey_window", 5)
                        self._press_times.append(now)
                        # 清理过期按键
                        self._press_times = [
                            t for t in self._press_times if now - t <= window
                        ]
                        count = self.config.get("hotkey_count", 3)
                        if len(self._press_times) >= count:
                            self._press_times.clear()
                            logging.info("手动热键触发")
                            self.on_trigger()
            except Exception as e:
                logging.error(f"热键处理异常: {e}")

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()

# ====================== 系统托盘 ======================
class TrayIcon:
    """系统托盘图标（可选）"""

    def __init__(self, on_show, on_exit):
        self.on_show = on_show
        self.on_exit = on_exit
        self.icon = None

    def _create_image(self):
        # 绘制一个简单的红色心形/花图标
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # 红色圆形底
        draw.ellipse([4, 4, 60, 60], fill=(220, 50, 60, 255))
        # 白色文字 "师"
        draw.text((18, 10), "师", fill=(255, 255, 255, 255))
        return img

    def run(self):
        if not HAS_TRAY:
            logging.warning("未安装 pystray/Pillow，不显示托盘图标")
            return
        menu = pystray.Menu(
            pystray.MenuItem("显示祝福", self._on_show),
            pystray.MenuItem("退出程序", self._on_exit),
        )
        self.icon = pystray.Icon(
            "teacher_day",
            self._create_image(),
            "教师节祝福程序",
            menu,
        )
        self.icon.run()

    def _on_show(self, icon, item):
        self.on_show()

    def _on_exit(self, icon, item):
        icon.stop()
        self.on_exit()

# ====================== 主程序 ======================
class TeacherDayApp:
    def __init__(self):
        self.config = load_config()
        setup_logging(self.config.get("log_enabled", True))
        logging.info("=" * 50)
        logging.info("教师节祝福程序启动")
        logging.info(f"配置: {json.dumps(self.config, ensure_ascii=False)}")

        self.greeting = GreetingManager(self.config)
        self.usb_detector = None
        self.hotkey_detector = None
        self.tray = None

    def on_usb_insert(self, drives):
        if self.config.get("usb_detect", True):
            self.greeting.show()

    def on_hotkey(self):
        if self.config.get("manual_trigger", True):
            self.greeting.show()

    def on_exit(self):
        logging.info("程序退出")
        if self.usb_detector:
            self.usb_detector.stop()
        if self.hotkey_detector:
            self.hotkey_detector.stop()
        self.greeting.hide()
        # 强制退出
        os._exit(0)

    def run(self):
        # 检查 HTML 文件
        if not HTML_PATH.exists():
            logging.error(f"未找到祝福网页: {HTML_PATH}")
            print(f"错误: 未找到 {HTML_PATH}")

        # 启动 U 盘检测
        if self.config.get("usb_detect", True):
            self.usb_detector = USBDetector(self.config, self.on_usb_insert)
            self.usb_detector.start()

        # 启动热键检测
        if self.config.get("manual_trigger", True):
            self.hotkey_detector = HotkeyDetector(self.config, self.on_hotkey)
            self.hotkey_detector.start()

        # 启动系统托盘
        if self.config.get("tray_icon", True) and HAS_TRAY:
            self.tray = TrayIcon(self.greeting.show, self.on_exit)
            # 托盘在主线程运行，阻塞
            self.tray.run()
        else:
            # 无托盘时，主线程保持运行
            logging.info("程序已在后台静默运行（无托盘图标），按 Ctrl+C 退出")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.on_exit()

def main():
    app = TeacherDayApp()
    app.run()

if __name__ == "__main__":
    main()
