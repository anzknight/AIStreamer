"""
Twitch配信設定コントローラー
- チャットモード設定（サブスクライバー限定/エモート限定/低速モード等）
- Twitch APIでタイトル・カテゴリ変更
"""
import aiohttp
from config.settings import settings


class TwitchController:
    def __init__(self):
        self._token = settings.TWITCH_TOKEN.replace("oauth:", "")
        self._channel = settings.TWITCH_CHANNEL
        self._client_id = settings.TWITCH_CLIENT_ID
        self._broadcaster_id: str | None = None

    async def _get_broadcaster_id(self) -> str | None:
        if self._broadcaster_id:
            return self._broadcaster_id
        if not self._client_id:
            print("[Twitch] TWITCH_CLIENT_ID が設定されていません")
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.twitch.tv/helix/users?login={self._channel}",
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Client-Id": self._client_id,
                    }
                ) as resp:
                    data = await resp.json()
                    users = data.get("data", [])
                    if users:
                        self._broadcaster_id = users[0]["id"]
                        return self._broadcaster_id
        except Exception as e:
            print(f"[Twitch] broadcaster_id取得エラー: {e}")
        return None

    async def send_chat_command(self, command: str):
        """Twitchチャットにコマンドを送信（/subscribers等）"""
        try:
            import twitchio
            # twitchioのWebhook経由でチャットコマンド送信
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.twitch.tv/helix/chat/messages",
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Client-Id": self._client_id,
                        "Content-Type": "application/json",
                    },
                    json={
                        "broadcaster_id": await self._get_broadcaster_id(),
                        "sender_id": await self._get_broadcaster_id(),
                        "message": command,
                    }
                ) as resp:
                    if resp.status in (200, 204):
                        print(f"[Twitch] コマンド送信: {command}")
                        return True
                    else:
                        text = await resp.text()
                        print(f"[Twitch] コマンド送信エラー {resp.status}: {text}")
        except Exception as e:
            print(f"[Twitch] コマンド送信エラー: {e}")
        return False

    async def set_subscribers_only(self, enabled: bool):
        cmd = "/subscribers" if enabled else "/subscribersoff"
        result = await self.send_chat_command(cmd)
        if result:
            status = "有効" if enabled else "無効"
            print(f"[Twitch] サブスクライバー限定モード: {status}")
        return result

    async def set_emote_only(self, enabled: bool):
        cmd = "/emoteonly" if enabled else "/emoteonlyoff"
        result = await self.send_chat_command(cmd)
        if result:
            status = "有効" if enabled else "無効"
            print(f"[Twitch] エモートのみモード: {status}")
        return result

    async def set_slow_mode(self, seconds: int = 0):
        cmd = f"/slow {seconds}" if seconds > 0 else "/slowoff"
        result = await self.send_chat_command(cmd)
        if result:
            print(f"[Twitch] 低速モード: {seconds}秒" if seconds > 0 else "[Twitch] 低速モード: 無効")
        return result

    async def update_stream_info(self, title: str = None, game_name: str = None):
        broadcaster_id = await self._get_broadcaster_id()
        if not broadcaster_id or not self._client_id:
            print("[Twitch] TWITCH_CLIENT_ID が必要です")
            return False
        body = {}
        if title:
            body["title"] = title
        if game_name:
            # ゲームIDを検索
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"https://api.twitch.tv/helix/games?name={game_name}",
                        headers={
                            "Authorization": f"Bearer {self._token}",
                            "Client-Id": self._client_id,
                        }
                    ) as resp:
                        data = await resp.json()
                        games = data.get("data", [])
                        if games:
                            body["game_id"] = games[0]["id"]
            except Exception as e:
                print(f"[Twitch] ゲームID取得エラー: {e}")
        if not body:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    f"https://api.twitch.tv/helix/channels?broadcaster_id={broadcaster_id}",
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Client-Id": self._client_id,
                        "Content-Type": "application/json",
                    },
                    json=body
                ) as resp:
                    if resp.status == 204:
                        print(f"[Twitch] 配信情報を更新しました: {body}")
                        return True
        except Exception as e:
            print(f"[Twitch] 配信情報更新エラー: {e}")
        return False
