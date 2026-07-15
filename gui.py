"""
AITuber デスクトップアプリ（tkinter版）
起動: python gui.py
ブラウザ不要・追加インストール不要
"""
import asyncio
import threading
import queue
import json
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from config.settings import settings

# ---- 非同期ループを別スレッドで動かす ----
_loop = asyncio.new_event_loop()
_aituber = None
_log_queue: queue.Queue = queue.Queue()


def _patch_print():
    import builtins
    original = builtins.print

    def patched(*args, **kwargs):
        text = " ".join(str(a) for a in args)
        original(text, **{k: v for k, v in kwargs.items() if k != "end"})
        _log_queue.put(text)

    builtins.print = patched


def _run_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def _submit(coro):
    """GUIスレッドから非同期処理を投げる"""
    return asyncio.run_coroutine_threadsafe(coro, _loop)


async def _init_aituber():
    global _aituber
    from main import AITuber
    _aituber = AITuber()
    await _aituber.memory.initialize()
    await _aituber.obs.connect()
    _aituber._running = True
    asyncio.ensure_future(_aituber._run_loops(use_console=False))


# ---- GUI ----
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AITuber コントロールパネル")
        self.geometry("780x720")
        self.configure(bg="#1a1a2e")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background="#1a1a2e", borderwidth=0)
        style.configure("TNotebook.Tab", background="#2d2d4e", foreground="#e0e0e0", padding=[14, 7])
        style.map("TNotebook.Tab", background=[("selected", "#7c3aed")])

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_main = tk.Frame(notebook, bg="#1a1a2e")
        self.tab_script = tk.Frame(notebook, bg="#1a1a2e")
        self.tab_video = tk.Frame(notebook, bg="#1a1a2e")
        notebook.add(self.tab_main, text=" メイン ")
        notebook.add(self.tab_script, text=" 台本モード ")
        notebook.add(self.tab_video, text=" 動画実況 ")

        self._build_main_tab()
        self._build_script_tab()
        self._build_video_tab()
        self._build_log()

        self.after(200, self._poll_logs)

    # ---------- メインタブ ----------
    def _build_main_tab(self):
        f = self.tab_main

        # 配信コントロール
        sec1 = self._section(f, "配信コントロール")
        self._btn(sec1, "▶ 配信開始", "#059669", self.on_start).pack(side="left", padx=4)
        self._btn(sec1, "■ 配信停止", "#dc2626", self.on_stop).pack(side="left", padx=4)
        self.pause_btn = self._btn(sec1, "⏸ 一時停止", "#d97706", self.on_pause)
        self.pause_btn.pack(side="left", padx=4)
        self._paused = False

        # モード切替
        sec2 = self._section(f, "モード切替")
        self.mode_var = tk.StringVar(value=settings.MODE)
        for mode, label in [("chat", "💬 雑談"), ("game", "🎮 ゲーム実況"),
                            ("gamedev", "🛠 ゲーム制作"), ("video", "🎬 動画実況")]:
            tk.Radiobutton(
                sec2, text=label, value=mode, variable=self.mode_var,
                command=self.on_mode, bg="#1a1a2e", fg="#e0e0e0",
                selectcolor="#7c3aed", activebackground="#1a1a2e",
                activeforeground="#fff", font=("Meiryo UI", 10),
            ).pack(side="left", padx=6)

        # ゲーム知識
        sec3 = self._section(f, "ゲーム知識")
        self.game_var = tk.StringVar()
        self.game_combo = ttk.Combobox(sec3, textvariable=self.game_var, width=24, state="readonly")
        self.game_combo.pack(side="left", padx=4)
        self._btn(sec3, "読み込む", "#7c3aed", self.on_load_game).pack(side="left", padx=4)
        self._btn(sec3, "更新", "#374151", self._refresh_games).pack(side="left", padx=4)
        self._refresh_games()

        # 手動発言
        sec4 = self._section(f, "手動発言")
        self.say_entry = tk.Entry(sec4, bg="#0f0f1a", fg="#e0e0e0", insertbackground="#e0e0e0",
                                  font=("Meiryo UI", 11), width=45)
        self.say_entry.pack(side="left", padx=4, ipady=4)
        self.say_entry.bind("<Return>", lambda e: self.on_say())
        self._btn(sec4, "🗣 発言", "#2563eb", self.on_say).pack(side="left", padx=4)

    # ---------- 台本タブ ----------
    def _build_script_tab(self):
        f = self.tab_script

        info = tk.Label(
            f, text="1行に1つセリフを書いて「▶ 台本を再生」を押すと上から順番に喋ります。\n"
                    "# で始まる行はメモとして無視。音声は保存先フォルダに clip_0001.mp3... と保存されます。",
            bg="#12122a", fg="#9ca3af", font=("Meiryo UI", 9), justify="left", anchor="w", padx=10, pady=8,
        )
        info.pack(fill="x", padx=10, pady=(10, 4))

        self.script_text = tk.Text(f, bg="#0f0f1a", fg="#e0e0e0", insertbackground="#e0e0e0",
                                   font=("Meiryo UI", 10), height=14, padx=10, pady=8)
        self.script_text.pack(fill="both", expand=False, padx=10, pady=4)

        row = tk.Frame(f, bg="#1a1a2e")
        row.pack(fill="x", padx=10, pady=4)
        self.script_btn = self._btn(row, "▶ 台本を再生", "#7c3aed", self.on_run_script)
        self.script_btn.pack(side="left", padx=4)
        self._btn(row, "クリア", "#374151", lambda: self.script_text.delete("1.0", "end")).pack(side="left", padx=4)

        # 保存先
        row2 = tk.Frame(f, bg="#1a1a2e")
        row2.pack(fill="x", padx=10, pady=8)
        tk.Label(row2, text="音声の保存先:", bg="#1a1a2e", fg="#9ca3af",
                 font=("Meiryo UI", 9)).pack(side="left")
        self.save_dir_var = tk.StringVar(value=str(settings.AUDIO_SAVE_DIR))
        tk.Entry(row2, textvariable=self.save_dir_var, bg="#0f0f1a", fg="#e0e0e0",
                 font=("Meiryo UI", 9), width=42).pack(side="left", padx=6, ipady=3)
        self._btn(row2, "📁 選択", "#374151", self.on_pick_save_dir).pack(side="left", padx=2)

        self.script_status = tk.Label(f, text="", bg="#1a1a2e", fg="#6ee7b7", font=("Meiryo UI", 9))
        self.script_status.pack(anchor="w", padx=14)

    # ---------- 動画実況タブ ----------
    def _build_video_tab(self):
        f = self.tab_video

        info = tk.Label(
            f, text="録画済みの動画を選ぶと、AIが数秒ごとに画面を見てコメント＋音声を保存します。\n"
                    "完了後「🎵 音声を動画に合成」を押すと実況入り動画が完成します。",
            bg="#12122a", fg="#9ca3af", font=("Meiryo UI", 9), justify="left", anchor="w", padx=10, pady=8,
        )
        info.pack(fill="x", padx=10, pady=(10, 4))

        row = tk.Frame(f, bg="#1a1a2e")
        row.pack(fill="x", padx=10, pady=6)
        tk.Label(row, text="動画ファイル:", bg="#1a1a2e", fg="#9ca3af", font=("Meiryo UI", 9)).pack(side="left")
        self.video_path_var = tk.StringVar()
        tk.Entry(row, textvariable=self.video_path_var, bg="#0f0f1a", fg="#e0e0e0",
                 font=("Meiryo UI", 9), width=44).pack(side="left", padx=6, ipady=3)
        self._btn(row, "📁 選択", "#374151", self.on_pick_video).pack(side="left", padx=2)

        row2 = tk.Frame(f, bg="#1a1a2e")
        row2.pack(fill="x", padx=10, pady=6)
        tk.Label(row2, text="コメント間隔:", bg="#1a1a2e", fg="#9ca3af", font=("Meiryo UI", 9)).pack(side="left")
        self.interval_var = tk.StringVar(value="10")
        ttk.Combobox(row2, textvariable=self.interval_var, values=["5", "10", "15", "30"],
                     width=6, state="readonly").pack(side="left", padx=6)
        tk.Label(row2, text="秒ごと", bg="#1a1a2e", fg="#9ca3af", font=("Meiryo UI", 9)).pack(side="left")

        row3 = tk.Frame(f, bg="#1a1a2e")
        row3.pack(fill="x", padx=10, pady=6)
        self.video_btn = self._btn(row3, "🎬 実況開始", "#7c3aed", self.on_video_start)
        self.video_btn.pack(side="left", padx=4)
        self._btn(row3, "停止", "#374151", self.on_video_stop).pack(side="left", padx=4)
        self.mix_btn = self._btn(row3, "🎵 音声を動画に合成", "#059669", self.on_mix)
        self.mix_btn.pack(side="left", padx=12)

        self.video_status = tk.Label(f, text="", bg="#1a1a2e", fg="#93c5fd", font=("Meiryo UI", 9))
        self.video_status.pack(anchor="w", padx=14, pady=4)

        self._video_running = False

    # ---------- ログ ----------
    def _build_log(self):
        frame = tk.Frame(self, bg="#1a1a2e")
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tk.Label(frame, text="ログ", bg="#1a1a2e", fg="#7c3aed",
                 font=("Meiryo UI", 9, "bold")).pack(anchor="w")
        self.log_text = tk.Text(frame, bg="#070710", fg="#9ca3af", font=("Consolas", 9),
                                height=10, state="disabled", padx=8, pady=6)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("ai", foreground="#a78bfa")
        self.log_text.tag_config("chat", foreground="#34d399")
        self.log_text.tag_config("tts", foreground="#60a5fa")
        self.log_text.tag_config("error", foreground="#f87171")

    # ---------- 部品 ----------
    def _section(self, parent, title):
        tk.Label(parent, text=title, bg="#1a1a2e", fg="#7c3aed",
                 font=("Meiryo UI", 9, "bold")).pack(anchor="w", padx=12, pady=(14, 2))
        row = tk.Frame(parent, bg="#1a1a2e")
        row.pack(fill="x", padx=12, pady=2)
        return row

    def _btn(self, parent, text, color, command):
        return tk.Button(parent, text=text, bg=color, fg="#ffffff",
                         font=("Meiryo UI", 10, "bold"), relief="flat",
                         padx=14, pady=6, cursor="hand2", command=command,
                         activebackground=color, activeforeground="#ffffff")

    # ---------- イベント ----------
    def on_start(self):
        async def _do():
            await _aituber.obs.start_streaming()
            msg = f"はいはーい！{_aituber.character['name']}の配信スタートだよー！みんなよろしくね！"
            print(f"[配信開始] {msg}")
            await _aituber._say(msg)
        _submit(_do())

    def on_stop(self):
        async def _do():
            msg = "今日も来てくれてありがとー！またねー！"
            print(f"[配信終了] {msg}")
            await _aituber._say(msg)
            await asyncio.sleep(3)
            await _aituber.obs.stop_streaming()
        _submit(_do())

    def on_pause(self):
        self._paused = not self._paused
        _aituber._paused = self._paused
        self.pause_btn.config(text="▶ 再開" if self._paused else "⏸ 一時停止")
        print("[一時停止]" if self._paused else "[再開]")

    def on_mode(self):
        mode = self.mode_var.get()
        _aituber._mode = mode
        labels = {"chat": "雑談", "game": "ゲームプレイ実況", "gamedev": "ゲーム制作", "video": "動画実況"}
        async def _do():
            msg = f"モードを「{labels[mode]}」に切り替えました！"
            print(f"[モード] {msg}")
            await _aituber._say(msg)
        _submit(_do())

    def _refresh_games(self):
        games_dir = settings.GAMES_DIR
        games_dir.mkdir(parents=True, exist_ok=True)
        files = [f.stem for f in games_dir.glob("*.md") if not f.stem.startswith("example_")]
        self.game_combo["values"] = files

    def on_load_game(self):
        name = self.game_var.get()
        if not name:
            return
        (settings.GAMES_DIR / "_current.txt").write_text(name, encoding="utf-8")
        async def _do():
            print(f"[ゲーム] 「{name}」の知識を読み込みました")
            await _aituber._say(f"よし！{name}をやっていくよ！")
        _submit(_do())

    def on_say(self):
        text = self.say_entry.get().strip()
        if not text:
            return
        self.say_entry.delete(0, "end")
        async def _do():
            print(f"[手動発言] {text}")
            await _aituber._say(text)
        _submit(_do())

    def on_pick_save_dir(self):
        d = filedialog.askdirectory(title="音声の保存先を選択")
        if d:
            self.save_dir_var.set(d)
            path = Path(d)
            path.mkdir(parents=True, exist_ok=True)
            import config.settings as _s
            _s.settings.AUDIO_SAVE_DIR = path
            _aituber.tts._audio_save_dir = path
            print(f"[設定] 音声保存先: {path}")

    def on_run_script(self):
        raw = self.script_text.get("1.0", "end")
        lines = [l.strip() for l in raw.split("\n") if l.strip() and not l.strip().startswith("#")]
        if not lines:
            return
        self.script_btn.config(state="disabled")
        self.script_status.config(text=f"再生中... 0/{len(lines)}")

        async def _do():
            import config.settings as _s
            _s.settings.SAVE_AUDIO_FILES = True
            _s.settings.AUDIO_SAVE_DIR.mkdir(parents=True, exist_ok=True)
            for i, line in enumerate(lines):
                print(f"[台本] {line}")
                await _aituber.tts.speak(line, wait=True)
                self.after(0, lambda i=i: self.script_status.config(
                    text=f"再生中... {i+1}/{len(lines)}"))
                await asyncio.sleep(0.3)
            self.after(0, lambda: (
                self.script_status.config(text=f"完了！ {len(lines)}行を再生・保存しました"),
                self.script_btn.config(state="normal"),
            ))
        _submit(_do())

    def on_pick_video(self):
        f = filedialog.askopenfilename(
            title="動画ファイルを選択",
            filetypes=[("動画ファイル", "*.mp4 *.mkv *.avi *.mov"), ("すべて", "*.*")],
        )
        if f:
            self.video_path_var.set(f)

    def on_video_start(self):
        path = Path(self.video_path_var.get().strip().strip('"'))
        if not path.exists():
            messagebox.showerror("エラー", f"ファイルが見つかりません:\n{path}")
            return
        interval = float(self.interval_var.get())
        self._video_running = True
        self.video_btn.config(state="disabled")
        self.video_status.config(text="実況中...")

        async def _do():
            import subprocess, tempfile
            import config.settings as _s
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(path)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
                duration = float(result.stdout.strip())
            except Exception as e:
                print(f"[動画実況] FFmpegが必要です: {e}")
                self.after(0, lambda: (self.video_status.config(text="エラー: FFmpegが必要です"),
                                       self.video_btn.config(state="normal")))
                return

            timestamps = list(range(0, int(duration), int(interval)))
            print(f"[動画実況] 開始: {path.name} ({duration:.0f}秒, {len(timestamps)}フレーム)")

            _s.settings.SAVE_AUDIO_FILES = True
            _s.settings.AUDIO_SAVE_DIR.mkdir(parents=True, exist_ok=True)
            _aituber.tts._session_start = None
            _aituber.tts._timeline = []
            _aituber.tts._clip_counter = 0

            with tempfile.TemporaryDirectory() as tmpdir:
                for i, ts in enumerate(timestamps):
                    if not self._video_running:
                        break
                    frame = Path(tmpdir) / f"f_{i}.png"
                    subprocess.run(
                        ["ffmpeg", "-y", "-ss", str(ts), "-i", str(path),
                         "-vframes", "1", "-vf", "scale=640:-1", "-q:v", "5", str(frame)],
                        capture_output=True)
                    if not frame.exists():
                        continue
                    response = await _aituber.ai.commentary(frame.read_bytes())
                    if response:
                        mins, secs = divmod(ts, 60)
                        print(f"[動画実況 {mins:02d}:{secs:02d}] {response}")
                        await _aituber.tts.speak(response, wait=True)
                        if _aituber.tts._timeline:
                            _aituber.tts._timeline[-1]["offset_sec"] = float(ts)
                            tp = _s.settings.AUDIO_SAVE_DIR / "timeline.json"
                            tp.write_text(json.dumps(_aituber.tts._timeline,
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
                    self.after(0, lambda i=i: self.video_status.config(
                        text=f"実況中... {i+1}/{len(timestamps)} フレーム"))

            print("[動画実況] 完了！「🎵 音声を動画に合成」で仕上げられます")
            self.after(0, lambda: (self.video_status.config(text="完了！「🎵 音声を動画に合成」を押してください"),
                                   self.video_btn.config(state="normal")))
        _submit(_do())

    def on_video_stop(self):
        self._video_running = False
        self.video_btn.config(state="normal")

    def on_mix(self):
        path = self.video_path_var.get().strip().strip('"')
        if not path:
            messagebox.showerror("エラー", "動画ファイルを選択してください")
            return
        out = filedialog.asksaveasfilename(
            title="出力先を選択", defaultextension=".mp4",
            initialfile="output.mp4", filetypes=[("MP4動画", "*.mp4")])
        if not out:
            return
        self.video_status.config(text="合成中...")

        def _mix():
            import subprocess
            result = subprocess.run(
                ["python", "mix_video.py", path, "--output", out],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            ok = result.returncode == 0
            self.after(0, lambda: self.video_status.config(
                text=f"完成！ → {out}" if ok else "合成エラー（ログ参照）"))
            if not ok:
                print(result.stdout)
                print(result.stderr)

        threading.Thread(target=_mix, daemon=True).start()

    # ---------- ログ表示 ----------
    def _poll_logs(self):
        try:
            while True:
                text = _log_queue.get_nowait()
                tag = None
                if "[AI]" in text or "[Commentary]" in text or "[動画実況" in text:
                    tag = "ai"
                elif "[Chat]" in text:
                    tag = "chat"
                elif "[TTS]" in text or "[台本]" in text:
                    tag = "tts"
                elif "エラー" in text or "Error" in text:
                    tag = "error"
                self.log_text.config(state="normal")
                self.log_text.insert("end", text + "\n", tag)
                # 最大500行
                lines = int(self.log_text.index("end-1c").split(".")[0])
                if lines > 500:
                    self.log_text.delete("1.0", f"{lines-500}.0")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._poll_logs)


def main():
    _patch_print()
    threading.Thread(target=_run_loop, daemon=True).start()
    fut = _submit(_init_aituber())
    fut.result(timeout=30)  # 初期化完了を待つ

    app = App()
    try:
        app.mainloop()
    finally:
        _loop.call_soon_threadsafe(_loop.stop)


if __name__ == "__main__":
    main()
