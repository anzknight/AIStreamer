import asyncio
import edge_tts
import json
import time
from pathlib import Path
from config.settings import settings

# Sentinel to signal the worker to stop
_STOP = object()


class TTSEngine:
    def __init__(self, character: dict):
        voice_cfg = character.get("voice", {})
        self.voice = voice_cfg.get("tts_voice", "ja-JP-NanamiNeural")
        self.rate = voice_cfg.get("speed", "+10%")
        self.pitch = voice_cfg.get("pitch", "+5Hz")
        self.output_dir = settings.TTS_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._audio_save_dir = settings.AUDIO_SAVE_DIR
        if settings.SAVE_AUDIO_FILES:
            self._audio_save_dir.mkdir(parents=True, exist_ok=True)
        self._clip_counter = 0
        self._session_start: float | None = None
        self._timeline: list = []  # [{clip, offset_sec, text}, ...]
        self.last_file: Path | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
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

    def _drain_queue(self):
        """キューに溜まっているアイテムをすべて捨てる"""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break

    async def reset(self):
        """音声を完全リセット（再生中の音声も停止）"""
        # Stop sentinel to break the worker loop
        await self._queue.put(_STOP)
        self._drain_queue()

        # Cancel the worker task and wait for it to finish
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
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

        print("[TTS] リセットしました")

    async def speak(self, text: str, wait: bool = False):
        if not settings.TTS_ENABLED:
            print(f"[TTS] {text}")
            if self._on_speak_start:
                await self._on_speak_start(text)
            return

        # キューが2件以上溜まっていたら古いものを捨てて最新だけ残す
        if self._queue.qsize() >= 2:
            self._drain_queue()

        await self._queue.put(text)

        # ワーカーが停止していれば（re）起動する
        if self._worker_task is None or self._worker_task.done():
            if wait:
                await self._run_worker()
            else:
                self._worker_task = asyncio.create_task(self._run_worker())

    async def _run_worker(self):
        """
        永続ワーカー。キューをブロッキングで待ち続け、
        キャンセルされるかSTOPセンチネルが来るまで動き続ける。
        """
        try:
            while True:
                item = await self._queue.get()
                if item is _STOP:
                    break
                await self._synthesize_and_play(item)
                if settings.TTS_PAUSE_BETWEEN > 0:
                    await asyncio.sleep(settings.TTS_PAUSE_BETWEEN)
        except asyncio.CancelledError:
            pass

    async def _synthesize_and_play(self, text: str):
        output_file = self.output_dir / "speech.mp3"
        try:
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
            await communicate.save(str(output_file))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[TTS] 音声合成エラー: {e}")
            return
        self.last_file = output_file

        # 連番保存 + タイムライン記録（動画制作用）
        if settings.SAVE_AUDIO_FILES:
            if self._session_start is None:
                self._session_start = time.time()
            self._clip_counter += 1
            import shutil
            save_path = self._audio_save_dir / f"clip_{self._clip_counter:04d}.mp3"
            shutil.copy2(str(output_file), str(save_path))
            offset = time.time() - self._session_start
            self._timeline.append({
                "clip": save_path.name,
                "offset_sec": round(offset, 2),
                "text": text,
            })
            # タイムラインをJSONで随時保存
            timeline_path = self._audio_save_dir / "timeline.json"
            timeline_path.write_text(
                json.dumps(self._timeline, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"[TTS] 保存: {save_path.name}  ({offset:.1f}秒)")

        # 字幕ON（音声再生直前）
        if self._on_speak_start:
            await self._on_speak_start(text)

        try:
            if self._obs and self._obs.connected and settings.OBS_AUDIO_SOURCE:
                await self._obs.play_audio_source(settings.OBS_AUDIO_SOURCE, output_file)
                estimated_secs = max(2.0, len(text) / 5.0)  # 日本語は約5文字/秒
                await asyncio.sleep(estimated_secs)
                # 再生完了後にOBSメディアソースを停止（次回の自動再生防止）
                await self._obs.stop_audio_source(settings.OBS_AUDIO_SOURCE)
            else:
                await self._play_local(output_file)
        except asyncio.CancelledError:
            raise
        finally:
            # 字幕OFF（再生終了後 or キャンセル時も必ずクリア）
            if self._on_speak_end:
                try:
                    await self._on_speak_end()
                except Exception:
                    pass

    async def _play_local(self, file_path: Path):
        """pygameでMP3を再生（外部ツール不要・Windows対応）"""
        try:
            import pygame
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._pygame_play, file_path)
            return
        except ImportError:
            pass

        # pygameがない場合はffplay/mpg123にフォールバック
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
                try:
                    await proc.wait()
                except asyncio.CancelledError:
                    proc.terminate()
                    raise
                finally:
                    self._current_proc = None
                return
            except FileNotFoundError:
                continue
        print(f"[TTS] Audio player not found. File: {file_path}")

    def _pygame_play(self, file_path: Path):
        """同期でpygame再生（executor内で実行）"""
        import pygame
        import time
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(file_path))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
