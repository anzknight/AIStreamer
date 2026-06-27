import asyncio
import edge_tts
from pathlib import Path
from config.settings import settings


class TTSEngine:
    def __init__(self, character: dict):
        voice_cfg = character.get("voice", {})
        self.voice = voice_cfg.get("tts_voice", "ja-JP-NanamiNeural")
        self.rate = voice_cfg.get("speed", "+10%")
        self.pitch = voice_cfg.get("pitch", "+5Hz")
        self.output_dir = settings.TTS_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.last_file: Path | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._playing = False
        self._obs = None
        self._on_speak_start = None  # 再生開始時のコールバック（字幕同期用）
        self._on_speak_end = None    # 再生終了時のコールバック（字幕クリア用）

    def set_obs(self, obs_controller):
        self._obs = obs_controller

    def set_subtitle_callbacks(self, on_start, on_end):
        """字幕をTTS再生と同期させるコールバックを設定"""
        self._on_speak_start = on_start
        self._on_speak_end = on_end

    async def speak(self, text: str, wait: bool = False):
        if not settings.TTS_ENABLED:
            print(f"[TTS] {text}")
            if self._on_speak_start:
                await self._on_speak_start(text)
            return
        await self._queue.put(text)
        if not self._playing:
            if wait:
                await self._process_queue()
            else:
                asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        self._playing = True
        while not self._queue.empty():
            text = await self._queue.get()
            await self._synthesize_and_play(text)
        self._playing = False

    async def _synthesize_and_play(self, text: str):
        output_file = self.output_dir / "speech.mp3"
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
        await communicate.save(str(output_file))
        self.last_file = output_file

        # 再生開始と同時に字幕を更新
        if self._on_speak_start:
            await self._on_speak_start(text)

        if self._obs and self._obs.connected and settings.OBS_AUDIO_SOURCE:
            await self._obs.play_audio_source(settings.OBS_AUDIO_SOURCE, output_file)
            estimated_secs = max(2.0, len(text) / 8.0)
            await asyncio.sleep(estimated_secs)
        else:
            await self._play_local(output_file)

        # 再生終了後に字幕クリア
        if self._on_speak_end:
            await self._on_speak_end()

    async def _play_local(self, file_path: Path):
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(file_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except FileNotFoundError:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "mpg123", "-q", str(file_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except FileNotFoundError:
                print(f"[TTS] Audio player not found. File: {file_path}")
