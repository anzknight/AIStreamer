import asyncio
import io
from PIL import Image
import mss
from config.settings import settings


class ScreenCapture:
    def __init__(self):
        self.sct = mss.mss()
        self.monitor_index = 1  # primary monitor

    def capture(self, region: dict | None = None) -> bytes:
        monitor = region or self.sct.monitors[self.monitor_index]
        screenshot = self.sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        # Resize to reduce token usage while keeping readability
        img.thumbnail((1280, 720))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def capture_window(self, title: str) -> bytes | None:
        """Capture a specific window by title (Linux: uses xdotool)"""
        try:
            import subprocess
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "getwindowgeometry", "--shell"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode != 0:
                return None
            geo = {}
            for line in result.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    geo[k] = int(v)
            region = {
                "left": geo.get("X", 0),
                "top": geo.get("Y", 0),
                "width": geo.get("WIDTH", 1920),
                "height": geo.get("HEIGHT", 1080),
            }
            return self.capture(region)
        except Exception:
            return self.capture()

    async def capture_loop(self, callback, interval: float = None):
        secs = interval or settings.SCREEN_CAPTURE_INTERVAL
        while True:
            try:
                if settings.GAME_WINDOW_TITLE:
                    img = self.capture_window(settings.GAME_WINDOW_TITLE)
                else:
                    img = self.capture()
                if img:
                    await callback(img)
            except Exception as e:
                print(f"[ScreenCapture] Error: {e}")
            await asyncio.sleep(secs)
