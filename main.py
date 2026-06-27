"""
AITuber - AIVTuber streaming bot

配信者コマンド:
  /start              OBS配信開始 + 挨拶
  /stop               OBS配信停止 + 締めの挨拶
  /pause              AI会話を一時停止
  /resume             AI会話を再開
  /mode chat          モード切替: 雑談
  /mode game          モード切替: ゲームプレイ実況
  /mode gamedev       モード切替: ゲーム制作
  /scene <名前>       OBSシーン切り替え
  /say <テキスト>     藍花に喋らせる

  [記憶]
  /mem show           全カテゴリの記憶を表示
  /mem add <カテゴリ> <キー> <値>
  /mem del <カテゴリ> <キー>

  [YouTube] /yt setid <ID> | /yt private | /yt public | /yt unlisted
  [Twitch]  /tw subonly | /tw emoteonly | /tw slow 30 | /tw title タイトル

  /quit / /help
"""
import asyncio
import signal
import sys
import time
import json
from config.settings import settings
from core.memory import MemoryManager
from core.ai_brain import AIBrain
from core.rules import RuleEngine
from modules.tts import TTSEngine
from modules.screen_capture import ScreenCapture
from modules.chat_reader import create_chat_readers, ChatMessage, get_youtube_reader
from modules.obs_controller import OBSController
from modules.youtube_controller import YouTubeController
from modules.twitch_controller import TwitchController

HELP_TEXT = """
[コマンド一覧]
  /start              配信開始（OBS配信スタート＋挨拶）
  /stop               配信停止（締めの挨拶＋OBS停止）
  /pause              AI会話を一時停止
  /resume             AI会話を再開

  [モード切替]
  /mode chat          雑談モード
  /mode game          ゲームプレイ実況モード
  /mode gamedev       ゲーム制作モード

  /scene <名前>       OBSシーン切り替え
  /say <テキスト>     藍花に喋らせる

  [記憶管理]
  /mem show           全記憶を表示
  /mem add viewer 田中 常連さん
  /mem del viewer 田中

  [YouTube] /yt setid <ID> | /yt private | /yt public | /yt unlisted
  [Twitch]  /tw subonly | /tw emoteonly | /tw slow 30 | /tw title タイトル

  /quit / /help
"""

AUTO_TALK_TOPICS = [
    "みんな今日はどんなゲームしてるのかな？気になる！",
    "最近ハマってるゲームある？教えてほしいな！",
    "ちょっと静かだね、みんな何してるのかな？",
    "突然だけど、みんなの推しキャラって誰？",
    "今日の配信楽しんでる？何かリクエストあったら言ってね！",
    "ゲームしながら思うんだけど、難しいステージって燃えるよね！",
    "みんなのゲーム歴どのくらい？私はずっとゲーム好きだよ！",
]


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
        self._mode = settings.MODE  # chat / game / gamedev
        self._last_chat_time = time.time()
        self._tasks: list[asyncio.Task] = []
        self.tts.set_obs(self.obs)
        self.tts.set_subtitle_callbacks(
            on_start=self._on_tts_start,
            on_end=self._on_tts_end,
        )

    async def start(self):
        print(f"[AITuber] Starting as {self.character['name']}...")
        print(HELP_TEXT)
        await self.memory.initialize()
        await self.obs.connect()
        self._running = True
        await self._run_loops()

    async def _run_loops(self):
        readers = create_chat_readers()
        # YouTubeリーダーにOBSコントローラーを渡して自動ID取得を有効化
        from modules.chat_reader import get_youtube_reader
        yt_reader = get_youtube_reader()
        if yt_reader:
            yt_reader.set_obs(self.obs)
            yt_reader.set_on_stream_end(self._on_stream_end)
        tasks = [asyncio.create_task(r.read(self._on_chat_message)) for r in readers]
        tasks.append(asyncio.create_task(self._command_loop()))

        if settings.AUTO_TALK_ENABLED:
            tasks.append(asyncio.create_task(self._auto_talk_loop()))

        if settings.SCREEN_CAPTURE_ENABLED and self.screen:
            tasks.append(asyncio.create_task(
                self.screen.capture_loop(self._on_screen_capture)
            ))

        self._tasks = tasks
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    async def _auto_talk_loop(self):
        """一定時間チャットがない時に自動で話題を作る"""
        import random
        await asyncio.sleep(settings.AUTO_TALK_INTERVAL)
        while self._running:
            await asyncio.sleep(10)
            if self._paused:
                continue
            elapsed = time.time() - self._last_chat_time
            if elapsed >= settings.AUTO_TALK_INTERVAL:
                topic = random.choice(AUTO_TALK_TOPICS)
                response = await self.ai.respond(topic, mode=settings.MODE)
                if response:
                    print(f"[自動発言] {response}")
                    await self._say(response)
                self._last_chat_time = time.time()

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
            farewell = "今日も来てくれてありがとー！またねー！"
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

        elif cmd == "/mode":
            modes = {"chat": "雑談", "game": "ゲームプレイ実況", "gamedev": "ゲーム制作", "video": "動画実況"}
            if arg in modes:
                self._mode = arg
                msg = f"モードを「{modes[arg]}」に切り替えました！"
                print(f"[モード] {msg}")
                await self._say(msg)
            else:
                print(f"[モード] 使い方: /mode chat | /mode game | /mode gamedev | /mode video")
                print(f"[モード] 現在: {self._mode} ({modes.get(self._mode, '不明')})")

        elif cmd == "/scene":
            if arg:
                await self.obs.switch_scene(arg)
                print(f"[シーン切替] {arg}")
            else:
                print("[エラー] /scene シーン名")

        elif cmd == "/say":
            if arg:
                print(f"[手動発言] {arg}")
                await self._say(arg)
            else:
                print("[エラー] /say テキスト")

        elif cmd == "/mem":
            await self._handle_memory_command(arg)

        elif cmd == "/yt":
            await self._handle_youtube_command(arg)

        elif cmd == "/tw":
            await self._handle_twitch_command(arg)

        elif cmd == "/quit":
            await self.stop()
            sys.exit(0)

        elif cmd == "/help":
            print(HELP_TEXT)

        else:
            print(f"[不明なコマンド] {cmd}  /help でコマンド一覧を表示")

    async def _handle_memory_command(self, arg: str):
        parts = arg.strip().split(maxsplit=3)
        sub = parts[0].lower() if parts else ""

        if sub == "show":
            category = parts[1] if len(parts) > 1 else None
            if category:
                data = await self.memory.recall_category(category)
                if data:
                    print(f"\n[記憶:{category}]")
                    for k, v in data.items():
                        print(f"  {k}: {v}")
                else:
                    print(f"[記憶] {category} に記憶はありません")
            else:
                for cat in ("viewer", "game", "general"):
                    data = await self.memory.recall_category(cat)
                    if data:
                        print(f"\n[記憶:{cat}]")
                        for k, v in data.items():
                            print(f"  {k}: {v}")
                print()

        elif sub == "add":
            if len(parts) >= 4:
                category, key, value = parts[1], parts[2], parts[3]
                await self.memory.remember(category, key, value)
                print(f"[記憶] 保存しました: [{category}] {key} = {value}")
            else:
                print("[エラー] /mem add <カテゴリ> <キー> <値>")

        elif sub == "del":
            if len(parts) >= 3:
                category, key = parts[1], parts[2]
                await self.memory._db.execute(
                    "DELETE FROM long_term WHERE category=? AND key=?", (category, key)
                )
                await self.memory._db.commit()
                print(f"[記憶] 削除しました: [{category}] {key}")
            else:
                print("[エラー] /mem del <カテゴリ> <キー>")

        else:
            print("[記憶] 使い方: /mem show | /mem add <カテゴリ> <キー> <値> | /mem del <カテゴリ> <キー>")

    async def _handle_youtube_command(self, arg: str):
        parts = arg.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1] if len(parts) > 1 else ""

        if sub == "setid":
            if sub_arg:
                reader = get_youtube_reader()
                if reader:
                    reader.set_video_id(sub_arg)
                    print(f"[YouTube] 動画IDを設定しました: {sub_arg}")
                    print("[YouTube] チャット読み取りを再接続するにはアプリを再起動してください")
                else:
                    print("[YouTube] YOUTUBE_ENABLED=true を.envに設定してください")
            else:
                print("[YouTube] 使い方: /yt setid <動画ID>")
        elif sub in ("private", "public", "unlisted"):
            if not self.youtube:
                print("[YouTube] YOUTUBE_CONTROLLER_ENABLED=true を.envに設定してください")
                return
            await self.youtube.set_privacy(sub)
        else:
            print("[YouTube] 使い方: /yt setid <動画ID> | /yt private | /yt public | /yt unlisted")

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

        self._last_chat_time = time.time()
        print(f"[Chat] {msg.platform} | {msg.username}: {msg.text}")

        current_time = time.time()
        rule_response = self.rules.check_keyword(msg.text, current_time)
        milestone = self.rules.increment_chat(current_time)

        if rule_response:
            await self._say(rule_response)

        response = await self.ai.respond(
            msg.text,
            mode=self._mode,
            username=msg.username,
        )
        if response:
            print(f"[AI] {response}")
            await self._say(response)
        else:
            print(f"[AI] 返答なし（スキップ）")

        if milestone and not rule_response:
            await self._say(milestone)

    async def _on_screen_capture(self, image: bytes):
        if not self._running or self._paused:
            return
        response = await self.ai.commentary(image)
        if response:
            print(f"[Commentary] {response}")
            await self._say(response)

    async def _on_stream_end(self):
        """YouTube配信終了時に音声・字幕を完全リセット"""
        await self.tts.reset()
        if self.obs.connected:
            await self.obs.clear_text_source("SubtitleText")
        print("[AITuber] 配信終了を検知 → 音声・字幕をリセットしました")

    async def _on_tts_start(self, text: str):
        """TTS再生開始と同時に字幕を更新"""
        if self.obs.connected:
            await self.obs.set_text_source("SubtitleText", text)

    async def _on_tts_end(self):
        """TTS再生終了後に字幕をクリア"""
        if self.obs.connected:
            await self.obs.clear_text_source("SubtitleText")

    async def _say(self, text: str):
        await self.tts.speak(text)

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
