import json
import asyncio
from groq import Groq
from config.settings import settings
from core.memory import MemoryManager


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "重要な情報を長期記憶に保存する。視聴者の名前、好み、ゲームの進捗など",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "カテゴリ (viewer/game/general)"},
                    "key": {"type": "string", "description": "記憶のキー"},
                    "value": {"type": "string", "description": "記憶する値"}
                },
                "required": ["category", "key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "長期記憶から情報を取り出す",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "カテゴリ"},
                    "key": {"type": "string", "description": "取り出すキー"}
                },
                "required": ["category", "key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_event",
            "description": "配信中の出来事を記録する",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "イベントタイプ"},
                    "description": {"type": "string", "description": "出来事の説明"}
                },
                "required": ["event_type", "description"]
            }
        }
    }
]


def _build_system_prompt(character: dict, mode: str, memory_context: str = "") -> str:
    rules_text = "\n".join(f"- {v}" for v in character.get("rules", {}).values())
    catchphrases = "、".join(character.get("catchphrases", []))

    prompt = f"""あなたはAIVTuberの「{character['name']}（{character['name_jp']}）」です。

【キャラクター設定】
{character['personality']}

【話し方】
{character['speech_style']}

【口癖・決め台詞】
{catchphrases}

【行動規則】
{rules_text}

【現在のモード】
{mode}

常にキャラクターを保ちながら、自然に返答してください。
返答は日本語で、200文字以内を目安にしてください。"""

    if memory_context:
        prompt += f"\n\n【記憶・コンテキスト】\n{memory_context}"

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
        response = self.client.chat.completions.create(
            model=settings.AI_MODEL,
            messages=messages,
            max_tokens=512,
        )
        return response.choices[0].message.content or ""

    def _execute_tool_sync(self, name: str, inputs: dict) -> str:
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._execute_tool(name, inputs))
        finally:
            loop.close()

    async def _execute_tool(self, name: str, inputs: dict) -> str:
        if name == "remember":
            await self.memory.remember(inputs["category"], inputs["key"], inputs["value"])
            return f"記憶しました: {inputs['key']} = {inputs['value']}"
        elif name == "recall":
            value = await self.memory.recall(inputs["category"], inputs["key"])
            return value or "見つかりませんでした"
        elif name == "log_event":
            await self.memory.log_event(inputs["event_type"], inputs["description"])
            return "記録しました"
        return "不明なツール"

    async def commentary(self, screen_image: bytes, game_context: str = "") -> str:
        prompt = game_context or "今やっているゲームについて実況してください。"
        return await self.respond(prompt, mode="game")
