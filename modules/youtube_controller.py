"""
YouTube Live配信設定コントローラー
- 配信プライバシー設定（公開/非公開/限定公開）
- OAuth2認証が必要（config/youtube_client_secret.jsonを配置）
"""
import os
import json
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube"]
TOKEN_FILE = Path(__file__).parent.parent / "config" / "youtube_token.json"
SECRET_FILE = Path(__file__).parent.parent / "config" / "youtube_client_secret.json"


class YouTubeController:
    def __init__(self):
        self._youtube = None
        self._broadcast_id: str | None = None

    def _authenticate(self):
        if self._youtube:
            return True
        if not SECRET_FILE.exists():
            print("[YouTube] youtube_client_secret.json が見つかりません")
            print("[YouTube] Google Cloud Console でOAuth2認証情報を作成して配置してください")
            print(f"[YouTube] 配置先: {SECRET_FILE}")
            return False
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            import googleapiclient.discovery

            creds = None
            if TOKEN_FILE.exists():
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(str(SECRET_FILE), SCOPES)
                    creds = flow.run_local_server(port=0)
                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())

            self._youtube = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
            return True
        except Exception as e:
            print(f"[YouTube] 認証エラー: {e}")
            return False

    def _get_active_broadcast_id(self) -> str | None:
        try:
            res = self._youtube.liveBroadcasts().list(
                part="id,status",
                broadcastStatus="active",
                maxResults=1
            ).execute()
            items = res.get("items", [])
            if items:
                return items[0]["id"]
            # アクティブがなければupcomingを検索
            res2 = self._youtube.liveBroadcasts().list(
                part="id,status",
                broadcastStatus="upcoming",
                maxResults=1
            ).execute()
            items2 = res2.get("items", [])
            return items2[0]["id"] if items2 else None
        except Exception as e:
            print(f"[YouTube] 配信ID取得エラー: {e}")
            return None

    async def set_privacy(self, privacy: str) -> bool:
        """
        privacy: "public" | "private" | "unlisted"
        """
        if not self._authenticate():
            return False
        try:
            broadcast_id = self._broadcast_id or self._get_active_broadcast_id()
            if not broadcast_id:
                print("[YouTube] アクティブな配信が見つかりません")
                return False
            self._youtube.liveBroadcasts().update(
                part="status",
                body={
                    "id": broadcast_id,
                    "status": {"privacyStatus": privacy}
                }
            ).execute()
            labels = {"public": "公開", "private": "非公開", "unlisted": "限定公開"}
            print(f"[YouTube] プライバシーを「{labels.get(privacy, privacy)}」に変更しました")
            return True
        except Exception as e:
            print(f"[YouTube] プライバシー変更エラー: {e}")
            return False

    def set_broadcast_id(self, broadcast_id: str):
        self._broadcast_id = broadcast_id
        print(f"[YouTube] 配信ID設定: {broadcast_id}")
