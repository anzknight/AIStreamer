import anthropic
import base64
import json
from pathlib import Path
from config.settings import settings
from core.memory import MemoryManager


TOOLS = [
    {
        "name": "remember",
        "description": "重要な情報を長期記憶に保存する。視聴者の名前、好み、ゲームの進捗など",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "カテゴリ (viewer/game/general)"},
                "key": {"type": "string", "description": "記憶のキー"},
                "value": {"type": "string", "description": "記憶する値"}
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "recall",
        "description": "長期記憶から情報を取り出す",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "カテゴリ"},
                "key": {"type": "string", "description": "取り出すキー"}
            },
            "required": ["category", "key"]
        }
    },
    {
        "name": "recall_category",
        "description": "あるカテゴリの全記憶を取り出す",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "カテゴリ"}
            },
            "required": ["category"]
        }
    },
    {
        "name": "log_event",
        "description": "配信中の出来事を記録する（ゲームクリア、面白いコメントなど）",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "description": "イベントタイプ"},
                "description": {"type": "string", "description": "出来事の説明"}
            },
            "required": ["event_type", "description"]
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

【ツールの使い方】
- 視聴者の名前や特徴を覚えたい時は remember ツールを使う
- 以前の情報を参照したい時は recall ツールを使う
- 配信中の重要な出来事は log_event ツールで記録する

常にキャラクターを保ちながら、自然に返答してください。
返答は日本語で、200文字以内を目安にしてください。"""

    if memory_context:
        prompt += f"\n\n【記憶・コンテキスト】\n{memory_context}"

    return prompt


class AIBrain:
    def __init__(self, memory: MemoryManager, character: dict):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
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

        content_parts: list = []
        if screen_image:
            b64 = base64.standard_b64encode(screen_image).decode("utf-8")
            content_parts.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64}
            })

        if username:
            content_parts.append({"type": "text", "text": f"[{username}]: {user_input}"})
        else:
            content_parts.append({"type": "text", "text": user_input})

        messages = history + [{"role": "user", "content": content_parts}]

        response_text = await self._run_with_tools(system, messages)

        await self.memory.add_message("user", f"[{username}]: {user_input}" if username else user_input)
        await self.memory.add_message("assistant", response_text)

        return response_text

    async def _run_with_tools(self, system: str, messages: list) -> str:
        while True:
            with self.client.messages.stream(
                model=settings.AI_MODEL,
                max_tokens=512,
                system=system,
                messages=messages,
                tools=TOOLS,
                thinking={"type": "adaptive"},
            ) as stream:
                response = stream.get_final_message()

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text_blocks = [b for b in response.content if b.type == "text"]
                return text_blocks[0].text if text_blocks else ""

            tool_results = []
            for tool_use in tool_uses:
                result = await self._execute_tool(tool_use.name, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": str(result)
                })

            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results}
            ]

    async def _execute_tool(self, name: str, inputs: dict) -> str:
        if name == "remember":
            await self.memory.remember(inputs["category"], inputs["key"], inputs["value"])
            return f"記憶しました: {inputs['key']} = {inputs['value']}"
        elif name == "recall":
            value = await self.memory.recall(inputs["category"], inputs["key"])
            return value or "見つかりませんでした"
        elif name == "recall_category":
            data = await self.memory.recall_category(inputs["category"])
            return json.dumps(data, ensure_ascii=False) if data else "データなし"
        elif name == "log_event":
            await self.memory.log_event(inputs["event_type"], inputs["description"])
            return "記録しました"
        return "不明なツール"

    async def commentary(self, screen_image: bytes, game_context: str = "") -> str:
        prompt = game_context or "今のゲーム画面について実況してください。"
        return await self.respond(prompt, mode="game", screen_image=screen_image)
