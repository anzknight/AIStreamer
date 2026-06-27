import asyncio
from dataclasses import dataclass
from config.settings import settings


@dataclass
class ChatMessage:
    platform: str
    username: str
    text: str


class YouTubeChatReader:
    def __init__(self, video_id: str):
        self.video_id = video_id

    async def read(self, callback):
        # video_idはYouTubeの視聴URL末尾のID（例: watch?v=XXXXXXXXXXX のXXX部分）
        # ストリームキーやRTMP URLは使えません
        if not self.video_id or "/" in self.video_id or "rtmp" in self.video_id:
            print("[YouTube Chat] 無効な動画IDです。")
            print("[YouTube Chat] YouTubeで配信中のURLを開き watch?v= の後の文字列を YOUTUBE_VIDEO_ID に設定してください")
            return
        try:
            import pytchat
            chat = pytchat.create(video_id=self.video_id)
            print(f"[YouTube Chat] Connected: {self.video_id}")
            while chat.is_alive():
                for item in chat.get().sync_items():
                    await callback(ChatMessage("youtube", item.author.name, item.message))
                await asyncio.sleep(1)
        except Exception as e:
            print(f"[YouTube Chat] Error: {e}")


class TwitchChatReader:
    def __init__(self, token: str, channel: str):
        self.token = token
        self.channel = channel

    async def read(self, callback):
        try:
            from twitchio.ext import commands

            cb = callback
            token = self.token.replace("oauth:", "")
            channel = self.channel

            class Bot(commands.Bot):
                def __init__(self):
                    super().__init__(
                        token=token,
                        prefix="!",
                        initial_channels=[channel],
                    )

                async def event_ready(self):
                    print(f"[Twitch Chat] Connected to #{channel}")

                async def event_message(self, message):
                    if message.echo:
                        return
                    await cb(ChatMessage("twitch", message.author.name, message.content))

            bot = Bot()
            await bot.start()
        except Exception as e:
            print(f"[Twitch Chat] Error: {e}")


class ConsoleChatReader:
    async def read(self, callback):
        print("[Console Chat] Type messages in format: username: message")
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


def create_chat_readers() -> list:
    readers = []
    if settings.YOUTUBE_ENABLED and settings.YOUTUBE_VIDEO_ID:
        readers.append(YouTubeChatReader(settings.YOUTUBE_VIDEO_ID))
    if settings.TWITCH_ENABLED and settings.TWITCH_TOKEN and settings.TWITCH_CHANNEL:
        readers.append(TwitchChatReader(settings.TWITCH_TOKEN, settings.TWITCH_CHANNEL))
    if not readers:
        readers.append(ConsoleChatReader())
    return readers
