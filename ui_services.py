import os
import ctypes
import platform
import subprocess
import queue
import threading
import time
import logging
from datetime import datetime

import psutil
import numpy as np
import sounddevice as sd
from PySide6.QtCore import QThread, Signal

from settings_store import get_setting
from automation_engine import due
from jarvis_core.logging import redact

_LOGGER = logging.getLogger("jarvis")

class RuntimeSnapshotWorker(QThread):
    dati = Signal(dict)
    errore = Signal(str)
    def __init__(self,provider,parent=None,interval_ms=1000):
        super().__init__(parent);self.provider=provider;self.interval_ms=max(250,int(interval_ms));self._running=True
    def stop(self):self._running=False
    def run(self):
        while self._running:
            try:self.dati.emit(self.provider.snapshot())
            except Exception as exc:self.errore.emit(redact(f"Runtime HUD: {type(exc).__name__}: {exc}"))
            remaining=self.interval_ms
            while self._running and remaining>0:self.msleep(min(100,remaining));remaining-=100


class AutomationSchedulerWorker(QThread):
    notice = Signal(str)
    errore = Signal(str)

    def __init__(self, engine, parent=None, interval_ms=1000):
        super().__init__(parent)
        self.engine = engine
        self.interval_ms = max(250, int(interval_ms))
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                for result in self.engine.run_due():
                    self.notice.emit(f"Automazione {result.automation_id}: {result.status}")
            except Exception as exc:
                self.errore.emit(redact(f"Scheduler: {type(exc).__name__}: {exc}"))
            remaining = self.interval_ms
            while self._running and remaining > 0:
                self.msleep(min(100, remaining))
                remaining -= 100


class AudioLevelWorker(QThread):
    """Misura RMS non bloccante; si disattiva silenziosamente se il device e occupato."""

    livello = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._last_error_at = 0.0

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                device = get_setting("mic_device", None)
                with sd.InputStream(device=device, channels=1, samplerate=16000, blocksize=640) as stream:
                    while self._running:
                        data, overflowed = stream.read(640)
                        rms = float(np.sqrt(np.mean(np.square(data, dtype=np.float64))))
                        self.livello.emit(max(0.0, min(1.0, rms * 14.0)))
            except Exception:
                self.livello.emit(0.0)
                now = time.monotonic()
                if now - self._last_error_at >= 1800:
                    _LOGGER.warning(redact("Audio HUD non disponibile: errore del dispositivo audio"))
                    self._last_error_at = now
                for _ in range(20):
                    if not self._running:
                        return
                    self.msleep(100)


class RoutineMonitorWorker(QThread):
    comando = Signal(str)
    errore = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._last_error_at = 0.0

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            try:
                routines = due()
                for routine in routines:
                    command = str(routine.get("command") or "").strip()
                    if command:
                        self.comando.emit(command)
            except Exception as exc:
                now = time.monotonic()
                if now - self._last_error_at >= 1800:
                    message = redact(f"Routine HUD: {type(exc).__name__}: {exc}")
                    self.errore.emit(message)
                    _LOGGER.warning(message)
                    self._last_error_at = now
            for _ in range(20):
                if not self._running:
                    return
                self.msleep(500)


class SystemMonitorWorker(QThread):
    dati = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._last_net = psutil.net_io_counters()
        self._last_time = time.time()
        self._last_error_at = 0.0

    def stop(self):
        self._running = False

    def _gpu_info(self):
        result = {
            "name": "N/D",
            "usage": None,
            "temperature": None,
            "memory_used": None,
            "memory_total": None,
        }
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ]
            output = subprocess.check_output(
                cmd,
                text=True,
                timeout=1.2,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ).strip().splitlines()[0]
            name, usage, temp, used, total = [x.strip() for x in output.split(",", 4)]
            result.update(
                name=name,
                usage=float(usage),
                temperature=float(temp),
                memory_used=float(used),
                memory_total=float(total),
            )
        except Exception:
            pass
        return result

    def _collect(self):
        now = time.time()
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        disk_root = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
        disk = psutil.disk_usage(disk_root)

        current_net = psutil.net_io_counters()
        elapsed = max(now - self._last_time, 0.001)
        download = (current_net.bytes_recv - self._last_net.bytes_recv) * 8 / elapsed / 1_000_000
        upload = (current_net.bytes_sent - self._last_net.bytes_sent) * 8 / elapsed / 1_000_000
        self._last_net = current_net
        self._last_time = now

        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = proc.info
                memory_mb = (info.get("memory_info").rss / 1024 / 1024) if info.get("memory_info") else 0
                processes.append({
                    "pid": info.get("pid"),
                    "name": info.get("name") or "Processo",
                    "cpu": float(info.get("cpu_percent") or 0),
                    "ram_mb": memory_mb,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        processes.sort(key=lambda x: (x["cpu"], x["ram_mb"]), reverse=True)

        uptime_seconds = max(0, now - psutil.boot_time())
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        active_window = ""
        if os.name == "nt":
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                buffer = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
                active_window = buffer.value
            except Exception:
                active_window = ""

        return {
            "cpu": cpu,
            "cpu_freq": round((psutil.cpu_freq().current / 1000), 2) if psutil.cpu_freq() else None,
            "cpu_count": psutil.cpu_count(logical=True),
            "ram": ram.percent,
            "ram_used_gb": round((ram.total - ram.available) / 1024**3, 1),
            "ram_total_gb": round(ram.total / 1024**3, 1),
            "disk": disk.percent,
            "disk_used_gb": round(disk.used / 1024**3, 1),
            "disk_total_gb": round(disk.total / 1024**3, 1),
            "download_mbps": max(0, download),
            "upload_mbps": max(0, upload),
            "processes": processes[:8],
            "gpu": self._gpu_info(),
            "uptime": f"{days} giorni, {hours} ore, {minutes} min",
            "os": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "active_window": active_window,
        }

    def run(self):
        psutil.cpu_percent(interval=None)
        while self._running:
            try:
                self.dati.emit(self._collect())
            except Exception as exc:
                now = time.monotonic()
                if now - self._last_error_at >= 1800:
                    _LOGGER.warning(redact(f"Monitor sistema HUD: {type(exc).__name__}: {exc}"))
                    self._last_error_at = now
            for _ in range(10):
                if not self._running:
                    return
                self.msleep(100)


class MarketDataProvider:
    """Contratto sostituibile per feed di mercato non necessariamente real-time."""

    name = "provider"
    realtime = False

    def fetch(self, tickers):
        raise NotImplementedError


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"
    realtime = False

    def fetch(self, tickers):
        import yfinance as yf

        symbols = list(tickers.values())
        interval = str(get_setting("market_interval", "5m"))
        period = {
            "1m": "1d", "5m": "5d", "15m": "5d", "1h": "1mo",
            "4h": "3mo", "1d": "1y", "1wk": "5y", "1mo": "10y",
        }.get(interval, "5d")
        yf_interval = "1h" if interval == "4h" else interval
        data = yf.download(
            symbols,
            period=period,
            interval=yf_interval,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
            timeout=8,
        )
        quotes = []
        eur_series = []
        for label, symbol in tickers.items():
            try:
                frame = data[symbol].dropna() if len(symbols) > 1 else data.dropna()
                close = frame["Close"].dropna()
                if close.empty:
                    continue
                last = float(close.iloc[-1])
                base = float(close.iloc[0])
                change = ((last - base) / base * 100) if base else 0.0
                quotes.append({"label": label, "symbol": symbol, "price": last, "change": change})
                if label == "EUR/USD":
                    eur_series = [float(x) for x in close.tail(120).tolist()]
            except Exception:
                continue
        return {"quotes": quotes, "eur_series": eur_series}


class MarketWorker(QThread):
    dati = Signal(dict)
    errore = Signal(str)

    TICKERS = {
        "EUR/USD": "EURUSD=X",
        "GBP/USD": "GBPUSD=X",
        "USD/JPY": "JPY=X",
        "NAS100": "^NDX",
        "SP500": "^GSPC",
        "XAU/USD": "GC=F",
    }

    def __init__(self, parent=None, provider=None):
        super().__init__(parent)
        self._running = True
        self._force = True
        self.provider = provider or YFinanceProvider()

    def stop(self):
        self._running = False

    def refresh_now(self):
        self._force = True

    def _fetch(self):
        configured = get_setting("market_watchlist", None)
        tickers = configured if isinstance(configured, dict) and configured else self.TICKERS
        payload = self.provider.fetch(tickers)
        return {
            **payload,
            "updated": datetime.now().strftime("%H:%M:%S"),
            "provider": self.provider.name,
            "realtime": bool(self.provider.realtime),
        }

    def _fetch_interruptible(self, timeout=12.0):
        result_queue = queue.Queue(maxsize=1)

        def execute():
            try:
                result_queue.put((True, self._fetch()), block=False)
            except Exception as exc:
                result_queue.put((False, exc), block=False)

        threading.Thread(target=execute, daemon=True, name="jarvis-market-fetch").start()
        deadline = time.time() + timeout
        while self._running and time.time() < deadline:
            try:
                ok, payload = result_queue.get(timeout=.1)
                if ok:
                    return payload
                raise payload
            except queue.Empty:
                continue
        if not self._running:
            return None
        raise TimeoutError("Timeout aggiornamento mercati")

    def run(self):
        next_update = 0
        while self._running:
            now = time.time()
            if self._force or now >= next_update:
                self._force = False
                try:
                    payload = self._fetch_interruptible()
                    if payload is None:
                        return
                    self.dati.emit(payload)
                except ModuleNotFoundError:
                    self.errore.emit("Installa yfinance: python -m pip install yfinance")
                except Exception as exc:
                    self.errore.emit(redact(f"Mercati non aggiornati: {exc}"))
                try:
                    refresh = max(20, int(get_setting("market_refresh_seconds", 60)))
                except (TypeError, ValueError):
                    refresh = 60
                next_update = time.time() + refresh
            self.msleep(500)
