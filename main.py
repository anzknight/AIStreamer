"""
AITuber - AIVTuber streaming bot

配信者コマンド:
  /start              OBS配信開始 + 挨拶
  /stop               OBS配信停止 + 締めの挨拶
  /pause              AI会話を一時停止
  /resume             AI会話を再開
  /scene <名前>       OBSシーン切り替え
  /say <テキスト>     藍花に喋らせる

  [YouTube]
  /yt private         配信を非公開に変更
  /yt public          配信を公開に変更
  /yt unlisted        配信を限定公開に変更

  [Twitch]
  /tw subonly         サブスクライバー限定モードON
  /tw subolyoff       サブスクライバー限定モードOFF
  /tw emoteonly       エモートのみモードON
  /tw emoteonlyoff    エモートのみモードOFF
  /tw slow <秒>       低速モードON
  /tw slowoff         低速モードOFF
  /tw title <タイトル>  配信タイトル変更
  /tw game <ゲーム名>   ゲームカテゴリ変更

  /quit               アプリ終了
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
from modules.youtube_controller import YouTubeController
from modules.twitch_controller import TwitchController


HELP_TEXT = """
[コマンド一覧]
  /start              配信開始（OBS配信スタート＋挨拶）
  /stop               配信停止（締めの挨拶＋OBS停止）
  /pause              AI会話を一時停止
  /resume             AI会話を再開
  /scene <名前>       OBSシーン切り替え
  /say <テキスト>     藍花に喋らせる

  [YouTube]
  /yt private         配信を非公開に変更
  /yt public          配信を公開に変更
  /yt unlisted        配信を限定公開に変更

  [Twitch]
  /tw subonly         サブスクライバー限定モードON
  /tw subolyoff       サブスクライバー限定モードOFF
  /tw emoteonly       エモートのみモードON
  /tw emoteonlyoff    エモートのみモードOFF
  /tw slow <秒>       低速モードON（例: /tw slow 30）
  /tw slowoff         低速モードOFF
  /tw title <タイトル>  配信タイトル変更
  /tw game <ゲーム名>   ゲームカテゴリ変更

  /quit               アプリ終了
  /help               このヘルプを表示
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
        self.youtube = YouTubeController() if settings.YOUTUBE_CONTROLLER_ENABLED else None
        self.twitch = TwitchController() if settings.TWITCH_ENABLED else None
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

        elif cmd == "/yt":
            await self._handle_youtube_command(arg)

        elif cmd == "/tw":
            await self._handle_twitch_command(arg)

        elif cmd == "/help":
            print(HELP_TEXT)

        else:
            print(f"[不明なコマンド] {cmd}  /help でコマンド一覧を表示")

    async def _handle_youtube_command(self, arg: str):
        if not self.youtube:
            print("[YouTube] YOUTUBE_CONTROLLER_ENABLED=true を.envに設定してください")
            return
        sub = arg.strip().lower()
        if sub in ("private", "public", "unlisted"):
            await self.youtube.set_privacy(sub)
        else:
            print("[YouTube] 使い方: /yt private | /yt public | /yt unlisted")

    async def _handle_twitch_command(self, arg: str):
        if not self.twitch:
            print("[Twitch] TWITCH_ENABLED=true を.envに設定してください")
            return
        parts = arg.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1] if len(parts) > 1 else ""

        if sub == "subonly":
            await self.twitch.set_subscribers_only(True)
        elif sub == "subolyoff":
            await self.twitch.set_subscribers_only(False)
        elif sub == "emoteonly":
            await self.twitch.set_emote_only(True)
        elif sub == "emoteonlyoff":
            await self.twitch.set_emote_only(False)
        elif sub == "slow":
            secs = int(sub_arg) if sub_arg.isdigit() else 30
            await self.twitch.set_slow_mode(secs)
        elif sub == "slowoff":
            await self.twitch.set_slow_mode(0)
        elif sub == "title":
            if sub_arg:
                await self.twitch.update_stream_info(title=sub_arg)
            else:
                print("[Twitch] 使い方: /tw title タイトル名")
        elif sub == "game":
            if sub_arg:
                await self.twitch.update_stream_info(game_name=sub_arg)
            else:
                print("[Twitch] 使い方: /tw game ゲーム名")
        else:
            print("[Twitch] /help でコマンド一覧を確認してください")

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
