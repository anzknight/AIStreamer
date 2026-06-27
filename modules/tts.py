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
        self._stop = False
        self._current_proc: asyncio.subprocess.Process | None = None
        self._worker_task: asyncio.Task | None = None
        self._obs = None
        self._on_speak_start = None
        self._on_speak_end = None

    def set_obs(self, obs_controller):
        self._obs = obs_controller

    def set_subtitle_callbacks(self, on_start, on_end):
        self._on_speak_start = on_start
        self._on_speak_end = on_end

    def _clear_queue(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break

    async def reset(self):
        """音声を完全リセット（再生中の音声も停止）"""
        self._stop = True
        self._clear_queue()

        # Cancel the worker task
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._worker_task), timeout=0.5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._worker_task = None

        # Kill any running audio process
        if self._current_proc and self._current_proc.returncode is None:
            try:
                self._current_proc.terminate()
                await asyncio.sleep(0.2)
            except Exception:
                pass
        self._current_proc = None

        self._stop = False
        print("[TTS] リセットしました")

    async def speak(self, text: str, wait: bool = False):
        if not settings.TTS_ENABLED:
            print(f"[TTS] {text}")
            if self._on_speak_start:
                await self._on_speak_start(text)
            return

        # Drop backlog if too many queued
        if self._queue.qsize() >= 2:
            self._clear_queue()

        await self._queue.put(text)

        # Start worker only if none is running
        if self._worker_task is None or self._worker_task.done():
            if wait:
                await self._worker()
            else:
                self._worker_task = asyncio.create_task(self._worker())

    async def _worker(self):
        while not self._queue.empty() and not self._stop:
            try:
                text = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if self._stop:
                break
            await self._synthesize_and_play(text)

    async def _synthesize_and_play(self, text: str):
        if self._stop:
            return
        output_file = self.output_dir / "speech.mp3"
        try:
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
            await communicate.save(str(output_file))
        except Exception as e:
            print(f"[TTS] 音声合成エラー: {e}")
            return
        self.last_file = output_file

        if self._stop:
            return

        # Subtitle on
        if self._on_speak_start:
            await self._on_speak_start(text)

        if self._obs and self._obs.connected and settings.OBS_AUDIO_SOURCE:
            await self._obs.play_audio_source(settings.OBS_AUDIO_SOURCE, output_file)
            estimated_secs = max(2.0, len(text) / 8.0)
            await asyncio.sleep(estimated_secs)
        else:
            await self._play_local(output_file)

        # Subtitle off
        if self._on_speak_end:
            await self._on_speak_end()

    async def _play_local(self, file_path: Path):
        for player, args in [
            ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
            ("mpg123", ["-q"]),
        ]:
            try:
                proc = await asyncio.create_subprocess_exec(
                    player, *args, str(file_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                self._current_proc = proc
                await proc.wait()
                self._current_proc = None
                return
            except FileNotFoundError:
                continue
        print(f"[TTS] Audio player not found. File: {file_path}")
