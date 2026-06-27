import asyncio
from dataclasses import dataclass
from config.settings import settings


@dataclass
class ChatMessage:
    platform: str
    username: str
    text: str


class YouTubeChatReader:
    def __init__(self):
        self._video_id: str | None = settings.YOUTUBE_VIDEO_ID or None
        self._chat = None

    def set_video_id(self, video_id: str):
        self._video_id = video_id
        self._chat = None  # リセットして再接続

    async def _auto_detect_video_id(self) -> str | None:
        """YouTube APIでアクティブな配信IDを自動取得"""
        try:
            from modules.youtube_controller import YouTubeController
            yt = YouTubeController()
            if not yt._authenticate():
                return None
            bid = yt._get_active_broadcast_id()
            if bid:
                print(f"[YouTube Chat] 配信IDを自動取得しました: {bid}")
            return bid
        except Exception as e:
            print(f"[YouTube Chat] 自動取得失敗: {e}")
            return None

    async def read(self, callback):
        import pytchat

        # 動画IDが未設定またはURL/RTMPの場合は自動取得を試みる
        if not self._video_id or "/" in self._video_id or "rtmp" in self._video_id.lower():
            print("[YouTube Chat] 動画IDを自動取得中...")
            self._video_id = await self._auto_detect_video_id()

        if not self._video_id:
            print("[YouTube Chat] 動画IDが取得できませんでした。")
            print("[YouTube Chat] 配信開始後に /yt setid <動画ID> で設定するか、")
            print("[YouTube Chat] YouTube Studioの配信URLから watch?v= 以降を YOUTUBE_VIDEO_ID に設定してください")
            return

        print(f"[YouTube Chat] 接続中: {self._video_id}")
        while True:
            try:
                chat = pytchat.create(video_id=self._video_id)
                print(f"[YouTube Chat] Connected!")
                while chat.is_alive():
                    for item in chat.get().sync_items():
                        await callback(ChatMessage("youtube", item.author.name, item.message))
                    await asyncio.sleep(1)
                print("[YouTube Chat] 配信が終了しました")
                break
            except Exception as e:
                print(f"[YouTube Chat] Error: {e}")
                await asyncio.sleep(5)


class TwitchChatReader:
    def __init__(self, token: str, channel: str):
        self.token = token.replace("oauth:", "")
        self.channel = channel

    async def read(self, callback):
        # IRC直接接続（client_id不要）
        try:
            reader, writer = await asyncio.open_connection("irc.chat.twitch.tv", 6697, ssl=True)
        except Exception:
            try:
                reader, writer = await asyncio.open_connection("irc.chat.twitch.tv", 6667)
            except Exception as e:
                print(f"[Twitch Chat] 接続失敗: {e}")
                return

        async def send(msg: str):
            writer.write((msg + "\r\n").encode())
            await writer.drain()

        await send(f"PASS oauth:{self.token}")
        await send(f"NICK {self.channel}")
        await send(f"JOIN #{self.channel}")
        print(f"[Twitch Chat] Connected to #{self.channel}")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode(errors="ignore").strip()

                if text.startswith("PING"):
                    await send("PONG :tmi.twitch.tv")
                    continue

                # :username!username@username.tmi.twitch.tv PRIVMSG #channel :message
                if "PRIVMSG" in text:
                    try:
                        username = text.split("!")[0].lstrip(":")
                        message = text.split("PRIVMSG")[1].split(":", 1)[1]
                        await callback(ChatMessage("twitch", username, message))
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Twitch Chat] Error: {e}")
        finally:
            writer.close()


class ConsoleChatReader:
    async def read(self, callback):
        print("[Console Chat] username: message の形式で入力してください")
        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, input)
                if ":" in line:
                    username, _, text = line.partition(":")
                    await callback(ChatMessage("console", username.strip(), text.strip()))
                elif line.strip():
                    await callback(ChatMessage("console", "viewer", line.strip()))
            except (EOFError, KeyboardInterrupt):
                break


# グローバル参照（/yt setid で動的に変更するため）
_youtube_reader: YouTubeChatReader | None = None


def create_chat_readers() -> list:
    global _youtube_reader
    readers = []

    if settings.YOUTUBE_ENABLED:
        _youtube_reader = YouTubeChatReader()
        readers.append(_youtube_reader)

    if settings.TWITCH_ENABLED and settings.TWITCH_TOKEN and settings.TWITCH_CHANNEL:
        readers.append(TwitchChatReader(settings.TWITCH_TOKEN, settings.TWITCH_CHANNEL))

    if not readers:
        readers.append(ConsoleChatReader())

    return readers


def get_youtube_reader() -> "YouTubeChatReader | None":
    return _youtube_reader
