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
        try:
            import pytchat
            chat = pytchat.create(video_id=self.video_id)
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

            class Bot(commands.Bot):
                def __init__(self, cb):
                    super().__init__(token=self.token, prefix="!", initial_channels=[self.channel])
                    self.cb = cb

                async def event_message(self, message):
                    if message.echo:
                        return
                    await self.cb(ChatMessage("twitch", message.author.name, message.content))

            bot = Bot(callback)
            await bot.start()
        except Exception as e:
            print(f"[Twitch Chat] Error: {e}")


class ConsoleChatReader:
    """Reads chat input from console (for testing without live chat)"""

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


def create_chat_reader(callback):
    if settings.YOUTUBE_ENABLED and settings.YOUTUBE_VIDEO_ID:
        return YouTubeChatReader(settings.YOUTUBE_VIDEO_ID)
    elif settings.TWITCH_ENABLED and settings.TWITCH_TOKEN:
        return TwitchChatReader(settings.TWITCH_TOKEN, settings.TWITCH_CHANNEL)
    else:
        return ConsoleChatReader()
