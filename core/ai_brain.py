import json
import asyncio
from groq import Groq
from config.settings import settings
from core.memory import MemoryManager


MODE_INSTRUCTIONS = {
    "chat": (
        "【モード: 雑談】\n"
        "視聴者と自由に雑談する場です。\n"
        "- 視聴者のコメントに自然に返答する\n"
        "- 話題は自由（ゲーム・アニメ・日常など）\n"
        "- ゲームプレイやゲーム制作の話題は軽く流す"
    ),
    "game": (
        "【モード: ゲームプレイ実況】\n"
        "ゲームをプレイしながら実況している場です。\n"
        "- 今やっているゲームの話題を中心にする\n"
        "- プレイの感想・攻略・リアクションを話す\n"
        "- 関係のない長話はしない\n"
        "- ゲームに集中した短めの返答を心がける"
    ),
    "gamedev": (
        "【モード: ゲーム制作】\n"
        "ゲームを制作している作業配信の場です。\n"
        "- 制作中のゲームについて話す\n"
        "- プログラミング・デザイン・アイデアの話題が中心\n"
        "- 視聴者の制作に関する質問や提案には積極的に反応する\n"
        "- 雑談やゲームプレイの話題は軽く受け流す"
    ),
}


def _build_system_prompt(character: dict, mode: str, memory_context: str = "") -> str:
    catchphrases = "、".join(character.get("catchphrases", []))
    mode_instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["chat"])

    prompt = f"""あなたはAIVTuberの「{character['name']}（{character['name_jp']}）」です。

【キャラクター設定】
{character['personality']}

【話し方】
{character['speech_style']}

【口癖・決め台詞】
{catchphrases}

{mode_instruction}

【重要ルール】
- 返答は日本語で60文字以内に収めてください
- 常にキャラクターを保ってください
- モードに合わない話題は短く流してください
- 自分から無関係な話題を振らないでください"""

    if memory_context:
        prompt += f"\n\n【記憶】\n{memory_context}"

    return prompt


class AIBrain:
    def __init__(self, memory: MemoryManager, character: dict):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.memory = memory
        self.character = character

    async def respond(
        self,
        user_input: str,
        mode: str = "chat",
        screen_image: bytes | None = None,
        username: str | None = None,
    ) -> str:
        history = await self.memory.get_recent_messages()

        memory_context = ""
        if username:
            viewer_data = await self.memory.recall_category("viewer")
            if viewer_data:
                memory_context = f"視聴者情報: {json.dumps(viewer_data, ensure_ascii=False)}"

        system = _build_system_prompt(self.character, mode, memory_context)

        user_text = f"[{username}]: {user_input}" if username else user_input
        messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_text}]

        response_text = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._run_with_tools(messages)
        )

        await self.memory.add_message("user", user_text)
        await self.memory.add_message("assistant", response_text)

        return response_text

    def _run_with_tools(self, messages: list) -> str:
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=settings.AI_MODEL,
                    messages=messages,
                    max_tokens=150,
                )
                return response.choices[0].message.content or ""
            except Exception as e:
                if attempt == 2:
                    print(f"[AI] 返答取得に失敗しました: {e}")
                    return ""
                import time as _time
                _time.sleep(1.5 * (attempt + 1))
        return ""

    async def commentary(self, screen_image: bytes, game_context: str = "") -> str:
        prompt = game_context or "今やっているゲームについて実況してください。"
        return await self.respond(prompt, mode="game")
