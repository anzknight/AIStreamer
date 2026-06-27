import asyncio
from pathlib import Path
from config.settings import settings

SUBTITLE_MAX_CHARS = 30  # 1行あたりの最大文字数


def _wrap_text(text: str, max_chars: int = SUBTITLE_MAX_CHARS) -> str:
    """長いテキストを改行で折り返す"""
    lines = []
    while len(text) > max_chars:
        lines.append(text[:max_chars])
        text = text[max_chars:]
    if text:
        lines.append(text)
    return "\n".join(lines)


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
            wrapped = _wrap_text(text)
            self._ws.set_input_settings(
                source_name,
                {"text": wrapped},
                overlay=True
            )
        except Exception as e:
            print(f"[OBS] set_text_source error: {e}")

    async def play_audio_source(self, source_name: str, file_path: Path):
        """OBSのメディアソースを使って音声を再生（YouTube配信に音声を乗せる）"""
        if not self.connected or not self._ws:
            return
        try:
            self._ws.set_input_settings(
                source_name,
                {
                    "local_file": str(file_path),
                    "is_local_file": True,
                    "looping": False,
                    "restart_on_activate": True,
                },
                overlay=True
            )
            # メディアソースを再起動して再生
            self._ws.trigger_media_input_action(source_name, "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART")
        except Exception as e:
            print(f"[OBS] play_audio_source error: {e}")

    async def clear_text_source(self, source_name: str):
        """字幕をクリア"""
        await self.set_text_source(source_name, "")

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

    def get_youtube_video_id(self) -> str | None:
        """OBSのストリーム設定からYouTube動画IDを取得"""
        if not self.connected or not self._ws:
            return None
        try:
            resp = self._ws.get_stream_service_settings()
            settings_data = resp.stream_service_settings
            # YouTube配信URLまたはキーからIDを抽出
            import re
            # stream_idフィールドがある場合
            stream_id = settings_data.get("stream_id", "")
            if stream_id:
                return stream_id
            # keyフィールドからYouTube動画IDを抽出試行
            key = settings_data.get("key", "")
            # YouTube broadcast IDはBase64っぽい文字列
            match = re.search(r"([A-Za-z0-9_-]{11})", key)
            if match:
                return match.group(1)
        except Exception as e:
            print(f"[OBS] get_youtube_video_id error: {e}")
        return None
