from config.settings import settings


class OBSController:
    def __init__(self):
        self._ws = None
        self.connected = False

    async def connect(self):
        if not settings.OBS_ENABLED:
            return
        try:
            import obsws_python as obs
            self._ws = obs.ReqClient(
                host=settings.OBS_HOST,
                port=settings.OBS_PORT,
                password=settings.OBS_PASSWORD,
            )
            self.connected = True
            print("[OBS] Connected")
        except Exception as e:
            print(f"[OBS] Connection failed: {e}")

    async def set_text_source(self, source_name: str, text: str):
        if not self.connected or not self._ws:
            return
        try:
            self._ws.set_input_settings(
                source_name,
                {"text": text},
                overlay=True
            )
        except Exception as e:
            print(f"[OBS] set_text_source error: {e}")

    async def start_streaming(self):
        if not self.connected or not self._ws:
            return
        try:
            self._ws.start_stream()
            print("[OBS] Streaming started")
        except Exception as e:
            print(f"[OBS] start_streaming error: {e}")

    async def stop_streaming(self):
        if not self.connected or not self._ws:
            return
        try:
            self._ws.stop_stream()
            print("[OBS] Streaming stopped")
        except Exception as e:
            print(f"[OBS] stop_streaming error: {e}")

    async def switch_scene(self, scene_name: str):
        if not self.connected or not self._ws:
            return
        try:
            self._ws.set_current_program_scene(scene_name)
        except Exception as e:
            print(f"[OBS] switch_scene error: {e}")
