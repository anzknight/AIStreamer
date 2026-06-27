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
        self._obs = None  # OBSControllerを後から注入

    def set_obs(self, obs_controller):
        self._obs = obs_controller

    async def speak(self, text: str, wait: bool = False):
        if not settings.TTS_ENABLED:
            print(f"[TTS] {text}")
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

        # OBSメディアソース経由で再生（YouTube/Twitch配信に音声を乗せる）
        if self._obs and self._obs.connected and settings.OBS_AUDIO_SOURCE:
            await self._obs.play_audio_source(settings.OBS_AUDIO_SOURCE, output_file)
            # 音声長さを推定してウェイト（edge-ttsは約150文字/秒）
            estimated_secs = max(2.0, len(text) / 8.0)
            await asyncio.sleep(estimated_secs)
        else:
            await self._play_local(output_file)

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
