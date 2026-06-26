"""
AITuber - AIVTuber streaming bot

配信者コマンド:
  /start          OBS配信開始 + 挨拶
  /stop           OBS配信停止 + 締めの挨拶
  /pause          AI会話を一時停止
  /resume         AI会話を再開
  /scene <名前>   OBSシーン切り替え
  /say <テキスト> 藍花に喋らせる
  /quit           アプリ終了
"""
import asyncio
import signal
import sys
import time
from config.settings import settings
from core.memory import MemoryManager
from core.ai_brain import AIBrain
from core.rules import RuleEngine
from modules.tts import TTSEngine
from modules.screen_capture import ScreenCapture
from modules.chat_reader import create_chat_readers, ChatMessage
from modules.obs_controller import OBSController


HELP_TEXT = """
[コマンド一覧]
  /start          配信開始（OBS配信スタート＋挨拶）
  /stop           配信停止（締めの挨拶＋OBS停止）
  /pause          AI会話を一時停止
  /resume         AI会話を再開
  /scene <名前>   OBSシーン切り替え
  /say <テキスト> 藍花に喋らせる
  /quit           アプリ終了
  /help           このヘルプを表示
"""


class AITuber:
    def __init__(self):
        self.character = settings.load_character()
        self.memory = MemoryManager()
        self.ai = AIBrain(self.memory, self.character)
        self.rules = RuleEngine(self.character)
        self.tts = TTSEngine(self.character)
        self.screen = ScreenCapture() if settings.SCREEN_CAPTURE_ENABLED else None
        self.obs = OBSController()
        self._running = False
        self._paused = False
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        print(f"[AITuber] Starting as {self.character['name']}...")
        print(HELP_TEXT)
        await self.memory.initialize()
        await self.obs.connect()
        self._running = True
        await self._run_loops()

    async def _run_loops(self):
        readers = create_chat_readers()
        tasks = [asyncio.create_task(r.read(self._on_chat_message)) for r in readers]
        tasks.append(asyncio.create_task(self._command_loop()))

        if settings.SCREEN_CAPTURE_ENABLED and self.screen:
            tasks.append(asyncio.create_task(
                self.screen.capture_loop(self._on_screen_capture)
            ))

        self._tasks = tasks

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    async def _command_loop(self):
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, input)
                await self._handle_command(line.strip())
            except (EOFError, KeyboardInterrupt):
                await self.stop()
                break

    async def _handle_command(self, line: str):
        if not line.startswith("/"):
            return

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/start":
            await self.obs.start_streaming()
            greeting = self.rules.check_event("stream_start", time.time())
            msg = greeting or f"はいはーい！{self.character['name']}の配信スタートだよー！みんなよろしくね！"
            print(f"[配信開始] {msg}")
            await self._say(msg)

        elif cmd == "/stop":
            farewell = f"今日も来てくれてありがとー！またねー！"
            print(f"[配信終了] {farewell}")
            await self._say(farewell)
            await asyncio.sleep(3)
            await self.obs.stop_streaming()
            print("[配信停止] OBS配信を停止しました")

        elif cmd == "/pause":
            self._paused = True
            print("[一時停止] AI会話を一時停止しました。再開するには /resume")

        elif cmd == "/resume":
            self._paused = False
            print("[再開] AI会話を再開しました")

        elif cmd == "/scene":
            if arg:
                await self.obs.switch_scene(arg)
                print(f"[シーン切替] {arg}")
            else:
                print("[エラー] シーン名を指定してください: /scene シーン名")

        elif cmd == "/say":
            if arg:
                print(f"[手動発言] {arg}")
                await self._say(arg)
            else:
                print("[エラー] テキストを指定してください: /say こんにちは")

        elif cmd == "/quit":
            await self.stop()
            sys.exit(0)

        elif cmd == "/help":
            print(HELP_TEXT)

        else:
            print(f"[不明なコマンド] {cmd}  /help でコマンド一覧を表示")

    async def _on_chat_message(self, msg: ChatMessage):
        if not self._running or self._paused:
            return

        print(f"[Chat] {msg.platform} | {msg.username}: {msg.text}")

        current_time = time.time()
        rule_response = self.rules.check_keyword(msg.text, current_time)
        milestone = self.rules.increment_chat(current_time)

        if rule_response:
            await self._say(rule_response)

        response = await self.ai.respond(
            msg.text,
            mode=settings.MODE,
            username=msg.username,
        )
        print(f"[AI] {response}")
        await self._say(response)

        if milestone and not rule_response:
            await self._say(milestone)

    async def _on_screen_capture(self, image: bytes):
        if not self._running or self._paused:
            return
        response = await self.ai.commentary(image)
        if response:
            print(f"[Commentary] {response}")
            await self._say(response)

    async def _say(self, text: str):
        await self.tts.speak(text)
        if self.obs.connected:
            await self.obs.set_text_source("SubtitleText", text)

    async def stop(self):
        print("[AITuber] Stopping...")
        self._running = False
        for task in self._tasks:
            task.cancel()
        await self.memory.close()


async def main():
    bot = AITuber()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()

        def handle_shutdown(sig):
            print(f"\n[Signal] {sig.name} received, shutting down...")
            asyncio.create_task(bot.stop())

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: handle_shutdown(s))

    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
