"""
AITuber - AIVTuber streaming bot
"""
import asyncio
import signal
import time
from config.settings import settings
from core.memory import MemoryManager
from core.ai_brain import AIBrain
from core.rules import RuleEngine
from modules.tts import TTSEngine
from modules.screen_capture import ScreenCapture
from modules.chat_reader import create_chat_reader, ChatMessage
from modules.obs_controller import OBSController


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
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        print(f"[AITuber] Starting as {self.character['name']}...")
        await self.memory.initialize()
        await self.obs.connect()

        greeting = self.rules.check_event("stream_start", time.time())
        if greeting:
            await self._say(greeting)

        self._running = True
        await self._run_loops()

    async def _run_loops(self):
        tasks = [asyncio.create_task(self._chat_loop())]

        if settings.SCREEN_CAPTURE_ENABLED and self.screen:
            tasks.append(asyncio.create_task(
                self.screen.capture_loop(self._on_screen_capture)
            ))

        self._tasks = tasks

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    async def _chat_loop(self):
        reader = create_chat_reader(self._on_chat_message)
        await reader.read(self._on_chat_message)

    async def _on_chat_message(self, msg: ChatMessage):
        if not self._running:
            return

        print(f"[Chat] {msg.platform} | {msg.username}: {msg.text}")

        current_time = time.time()

        # Rule-based keyword check
        rule_response = self.rules.check_keyword(msg.text, current_time)
        milestone = self.rules.increment_chat(current_time)

        if rule_response:
            await self._say(rule_response)

        # AI response
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
        if not self._running:
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

    loop = asyncio.get_running_loop()

    def handle_shutdown(sig):
        print(f"\n[Signal] {sig.name} received, shutting down...")
        asyncio.create_task(bot.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: handle_shutdown(s))

    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
