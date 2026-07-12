"""
AITuber Web UI サーバー
起動: python server.py
ブラウザで http://localhost:8080 を開く
"""
import asyncio
import sys
import time
import json
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config.settings import settings

# ログをWebSocketに流すためのキュー
_log_clients: list[WebSocket] = []
_log_buffer: list[str] = []


def _patch_print():
    """print をフックしてWebSocketクライアントにも流す"""
    import builtins
    original = builtins.print

    def patched(*args, **kwargs):
        text = " ".join(str(a) for a in args)
        original(text, **{k: v for k, v in kwargs.items() if k != "end"})
        _log_buffer.append(text)
        if len(_log_buffer) > 500:
            _log_buffer.pop(0)
        asyncio.get_event_loop().call_soon_threadsafe(
            asyncio.ensure_future, _broadcast_log(text)
        )

    builtins.print = patched


async def _broadcast_log(text: str):
    disconnected = []
    for ws in _log_clients:
        try:
            await ws.send_text(json.dumps({"type": "log", "text": text}))
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _log_clients.remove(ws)


# AITuberインスタンス（グローバル）
_aituber = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _aituber
    _patch_print()
    from main import AITuber
    _aituber = AITuber()
    await _aituber.memory.initialize()
    await _aituber.obs.connect()
    _aituber._running = True
    # バックグラウンドでループ開始
    asyncio.create_task(_aituber._run_loops())
    yield
    await _aituber.stop()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("static/index.html")


@app.get("/api/status")
async def status():
    games_dir = settings.GAMES_DIR
    current_file = games_dir / "_current.txt"
    current_game = current_file.read_text(encoding="utf-8").strip() if current_file.exists() else ""
    return {
        "running": _aituber._running if _aituber else False,
        "paused": _aituber._paused if _aituber else False,
        "mode": _aituber._mode if _aituber else settings.MODE,
        "current_game": current_game,
    }


@app.post("/api/start")
async def start_stream():
    await _aituber.obs.start_streaming()
    msg = f"はいはーい！{_aituber.character['name']}の配信スタートだよー！みんなよろしくね！"
    print(f"[配信開始] {msg}")
    await _aituber._say(msg)
    return {"ok": True}


@app.post("/api/stop")
async def stop_stream():
    msg = "今日も来てくれてありがとー！またねー！"
    print(f"[配信終了] {msg}")
    await _aituber._say(msg)
    await asyncio.sleep(3)
    await _aituber.obs.stop_streaming()
    return {"ok": True}


@app.post("/api/pause")
async def pause():
    _aituber._paused = True
    print("[一時停止] AI会話を一時停止しました")
    return {"ok": True}


@app.post("/api/resume")
async def resume():
    _aituber._paused = False
    print("[再開] AI会話を再開しました")
    return {"ok": True}


@app.post("/api/mode/{mode}")
async def set_mode(mode: str):
    modes = {"chat": "雑談", "game": "ゲームプレイ実況", "gamedev": "ゲーム制作", "video": "動画実況"}
    if mode not in modes:
        return {"ok": False, "error": "不明なモード"}
    _aituber._mode = mode
    msg = f"モードを「{modes[mode]}」に切り替えました！"
    print(f"[モード] {msg}")
    await _aituber._say(msg)
    return {"ok": True}


@app.post("/api/say")
async def say(body: dict):
    text = body.get("text", "").strip()
    if not text:
        return {"ok": False, "error": "テキストが空です"}
    print(f"[手動発言] {text}")
    await _aituber._say(text)
    return {"ok": True}


@app.get("/api/games")
async def list_games():
    games_dir = settings.GAMES_DIR
    games_dir.mkdir(parents=True, exist_ok=True)
    current_file = games_dir / "_current.txt"
    current = current_file.read_text(encoding="utf-8").strip() if current_file.exists() else ""
    files = [f.stem for f in games_dir.glob("*.md") if not f.stem.startswith("example_")]
    return {"games": files, "current": current}


@app.post("/api/game/{name}")
async def load_game(name: str):
    games_dir = settings.GAMES_DIR
    game_file = games_dir / f"{name}.md"
    if not game_file.exists():
        return {"ok": False, "error": f"{name}.md が見つかりません"}
    (games_dir / "_current.txt").write_text(name, encoding="utf-8")
    msg = f"よし！{name}をやっていくよ！"
    print(f"[ゲーム] 「{name}」の知識を読み込みました")
    await _aituber._say(msg)
    return {"ok": True}


@app.post("/api/game/clear")
async def clear_game():
    current_file = settings.GAMES_DIR / "_current.txt"
    if current_file.exists():
        current_file.unlink()
    print("[ゲーム] ゲーム知識をクリアしました")
    return {"ok": True}


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    _log_clients.append(websocket)
    # 過去ログを送る
    for line in _log_buffer[-100:]:
        await websocket.send_text(json.dumps({"type": "log", "text": line}))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _log_clients:
            _log_clients.remove(websocket)


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=False)
