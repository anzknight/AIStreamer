# AIStreamer - AITuber Bot

AIVTuberストリーミングボット。Claudeを使ったリアルタイム実況・雑談・チャット対応システム。

## 機能

- **ゲーム実況** - 画面キャプチャを解析してリアルタイム実況
- **チャット対応** - YouTube/Twitchのコメントを読み取り、AIが返答
- **音声合成** - edge-ttsによる日本語音声出力
- **長期記憶** - SQLiteで視聴者情報・ゲーム進捗を永続保存
- **ルールエンジン** - キーワード/イベントベースの決まり文句
- **OBS連携** - 字幕テキストソース更新・配信制御

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .envを編集してAPIキーなどを設定
```

## 起動

```bash
python main.py
```

コンソールモード（チャット入力）で起動します。`username: message` の形式で入力してください。

## 設定

`.env` ファイルで設定:

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `ANTHROPIC_API_KEY` | Anthropic APIキー | 必須 |
| `AITUBER_MODE` | モード (`chat`/`game`/`stream`) | `chat` |
| `TTS_ENABLED` | 音声合成の有効化 | `true` |
| `SCREEN_CAPTURE_ENABLED` | 画面キャプチャの有効化 | `false` |
| `SCREEN_CAPTURE_INTERVAL` | キャプチャ間隔（秒） | `10.0` |
| `YOUTUBE_ENABLED` | YouTube Liveチャット | `false` |
| `YOUTUBE_VIDEO_ID` | YouTube動画ID | - |
| `TWITCH_ENABLED` | Twitchチャット | `false` |
| `OBS_ENABLED` | OBS WebSocket連携 | `false` |

## キャラクター設定

`config/character.json` でキャラクターをカスタマイズ:

- `name` / `name_jp` - キャラクター名
- `personality` - 性格設定
- `speech_style` - 話し方
- `voice` - TTS音声設定
- `catchphrases` - 口癖
- `rules` - 行動ルール

## アーキテクチャ

```
main.py              # オーケストレーター
config/
  settings.py        # 設定管理
  character.json     # キャラクター定義
core/
  ai_brain.py        # Claude API統合・ツール使用
  memory.py          # SQLite長期/短期記憶
  rules.py           # ルールエンジン
modules/
  tts.py             # edge-tts音声合成
  screen_capture.py  # 画面キャプチャ (mss)
  chat_reader.py     # YouTube/Twitch/コンソールチャット
  obs_controller.py  # OBS WebSocket
data/                # 自動生成
  memory.db          # 記憶データベース
  tts_output/        # 音声ファイル
```
