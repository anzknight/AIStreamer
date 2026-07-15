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
    _apply_ui_settings()
    ui = _load_ui_settings()
    if ui.get("audio_save_dir"):
        _aituber.tts._audio_save_dir = Path(ui["audio_save_dir"])
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


@app.post("/api/script/say")
async def script_say(body: dict):
    """AviUtl2など外部ツールから1行喋らせる（音声ファイルも保存）"""
    text = body.get("text", "").strip()
    wait = body.get("wait", False)  # Trueにすると喋り終わるまで待つ
    if not text:
        return {"ok": False, "error": "テキストが空です"}
    # SAVE_AUDIO_FILES を一時的にONにして保存
    import config.settings as _s
    orig = _s.settings.SAVE_AUDIO_FILES
    _s.settings.SAVE_AUDIO_FILES = True
    _s.settings.AUDIO_SAVE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[台本] {text}")
    await _aituber.tts.speak(text, wait=wait)
    _s.settings.SAVE_AUDIO_FILES = orig
    clip_num = _aituber.tts._clip_counter
    clip_name = f"clip_{clip_num:04d}.mp3"
    return {"ok": True, "clip": clip_name}


@app.post("/api/script/run")
async def script_run(body: dict):
    """台本（複数行）を順番に喋らせる"""
    lines = body.get("lines", [])
    interval = body.get("interval", 0.5)  # 行間の待機秒数
    if not lines:
        return {"ok": False, "error": "linesが空です"}
    import config.settings as _s
    _s.settings.SAVE_AUDIO_FILES = True
    _s.settings.AUDIO_SAVE_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        print(f"[台本] {line}")
        await _aituber.tts.speak(line, wait=True)
        clip_name = f"clip_{_aituber.tts._clip_counter:04d}.mp3"
        results.append({"text": line, "clip": clip_name})
        if interval > 0:
            await asyncio.sleep(interval)
    return {"ok": True, "results": results}


# UI設定（保存場所など）
_UI_SETTINGS_FILE = Path("config/ui_settings.json")


def _load_ui_settings() -> dict:
    if _UI_SETTINGS_FILE.exists():
        try:
            return json.loads(_UI_SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _apply_ui_settings():
    """保存された設定をsettingsに反映"""
    ui = _load_ui_settings()
    import config.settings as _s
    if ui.get("audio_save_dir"):
        _s.settings.AUDIO_SAVE_DIR = Path(ui["audio_save_dir"])


@app.get("/api/settings")
async def get_settings():
    ui = _load_ui_settings()
    return {
        "audio_save_dir": ui.get("audio_save_dir", str(settings.AUDIO_SAVE_DIR)),
        "last_video_path": ui.get("last_video_path", ""),
    }


@app.post("/api/settings")
async def save_settings(body: dict):
    ui = _load_ui_settings()
    if "audio_save_dir" in body and body["audio_save_dir"].strip():
        path = Path(body["audio_save_dir"].strip().strip('"'))
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return {"ok": False, "error": f"フォルダを作成できません: {e}"}
        ui["audio_save_dir"] = str(path)
        import config.settings as _s
        _s.settings.AUDIO_SAVE_DIR = path
        _aituber.tts._audio_save_dir = path
        print(f"[設定] 音声保存先: {path}")
    if "last_video_path" in body:
        ui["last_video_path"] = body["last_video_path"]
    _UI_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _UI_SETTINGS_FILE.write_text(json.dumps(ui, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


# 動画実況の進行状態
_video_job = {"running": False, "progress": 0, "total": 0, "done": False, "results": []}


@app.post("/api/video/commentate")
async def video_commentate(body: dict):
    """録画済み動画を読み込んで、フレームごとにAIが実況コメントを生成"""
    video_path = Path(body.get("path", "").strip().strip('"'))
    interval = float(body.get("interval", 10.0))  # 何秒ごとに見るか

    if not video_path.exists():
        return {"ok": False, "error": f"ファイルが見つかりません: {video_path}"}
    if _video_job["running"]:
        return {"ok": False, "error": "すでに実行中です"}

    # 最後に使ったパスを記憶
    ui = _load_ui_settings()
    ui["last_video_path"] = str(video_path)
    _UI_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _UI_SETTINGS_FILE.write_text(json.dumps(ui, ensure_ascii=False, indent=2), encoding="utf-8")

    asyncio.create_task(_run_video_commentary(video_path, interval))
    return {"ok": True, "message": "動画実況を開始しました"}


@app.get("/api/video/status")
async def video_status():
    return _video_job


async def _run_video_commentary(video_path: Path, interval: float):
    """動画からフレームを抽出してAIに実況させる"""
    import subprocess
    import tempfile

    _video_job.update({"running": True, "progress": 0, "total": 0, "done": False, "results": []})

    # 動画の長さを取得
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        duration = float(result.stdout.strip())
    except Exception as e:
        print(f"[動画実況] ffprobeエラー: {e}（FFmpegをインストールしてください）")
        _video_job.update({"running": False, "done": True})
        return

    timestamps = [t for t in range(0, int(duration), int(interval))]
    _video_job["total"] = len(timestamps)
    print(f"[動画実況] 開始: {video_path.name} ({duration:.0f}秒, {len(timestamps)}フレーム)")

    # SAVE_AUDIO_FILES を強制ON + タイムラインリセット
    import config.settings as _s
    _s.settings.SAVE_AUDIO_FILES = True
    _s.settings.AUDIO_SAVE_DIR.mkdir(parents=True, exist_ok=True)
    _aituber.tts._session_start = None
    _aituber.tts._timeline = []
    _aituber.tts._clip_counter = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, ts in enumerate(timestamps):
            if not _video_job["running"]:
                break
            frame_path = Path(tmpdir) / f"frame_{i}.png"
            # フレーム抽出
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(ts), "-i", str(video_path),
                 "-vframes", "1", "-q:v", "2", str(frame_path)],
                capture_output=True
            )
            if not frame_path.exists():
                continue

            image_bytes = frame_path.read_bytes()
            response = await _aituber.ai.commentary(image_bytes)
            if response:
                mins, secs = divmod(ts, 60)
                print(f"[動画実況 {mins:02d}:{secs:02d}] {response}")
                # タイムラインのoffsetを動画時間に合わせる
                await _aituber.tts.speak(response, wait=True)
                # 保存されたclipのoffsetを動画のtsに上書き
                if _aituber.tts._timeline:
                    _aituber.tts._timeline[-1]["offset_sec"] = float(ts)
                    timeline_path = _s.settings.AUDIO_SAVE_DIR / "timeline.json"
                    timeline_path.write_text(
                        json.dumps(_aituber.tts._timeline, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                _video_job["results"].append({"time": ts, "text": response})
            _video_job["progress"] = i + 1

    _video_job.update({"running": False, "done": True})
    print(f"[動画実況] 完了！ python mix_video.py \"{video_path}\" で合成できます")


@app.post("/api/video/stop")
async def video_stop():
    _video_job["running"] = False
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
