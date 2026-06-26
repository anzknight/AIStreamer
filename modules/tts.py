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
        self._queue: asyncio.Queue = asyncio.Queue()
        self._playing = False

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
        await self._play_audio(output_file)

    async def _play_audio(self, file_path: Path):
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(file_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except FileNotFoundError:
            # ffplay not available, try aplay
            try:
                proc = await asyncio.create_subprocess_exec(
                    "mpg123", "-q", str(file_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except FileNotFoundError:
                print(f"[TTS] Audio player not found. Text: {file_path}")
