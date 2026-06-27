import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

class Settings:
    # Groq
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    AI_MODEL: str = "llama-3.3-70b-versatile"

    # Character
    CHARACTER_FILE: Path = BASE_DIR / "config" / "character.json"

    # Memory
    MEMORY_DB_PATH: Path = BASE_DIR / "data" / "memory.db"
    MAX_SHORT_TERM_MESSAGES: int = 20
    MAX_MEMORY_SEARCH_RESULTS: int = 5

    # TTS
    TTS_OUTPUT_DIR: Path = BASE_DIR / "data" / "tts_output"
    TTS_ENABLED: bool = os.getenv("TTS_ENABLED", "true").lower() == "true"
    TTS_PAUSE_BETWEEN: float = float(os.getenv("TTS_PAUSE_BETWEEN", "0.5"))  # 発話間の空白（秒）

    # Screen Capture
    SCREEN_CAPTURE_ENABLED: bool = os.getenv("SCREEN_CAPTURE_ENABLED", "false").lower() == "true"
    SCREEN_CAPTURE_INTERVAL: float = float(os.getenv("SCREEN_CAPTURE_INTERVAL", "10.0"))
    GAME_WINDOW_TITLE: str = os.getenv("GAME_WINDOW_TITLE", "")

    # OBS
    OBS_ENABLED: bool = os.getenv("OBS_ENABLED", "false").lower() == "true"
    OBS_HOST: str = os.getenv("OBS_HOST", "localhost")
    OBS_PORT: int = int(os.getenv("OBS_PORT", "4455"))
    OBS_PASSWORD: str = os.getenv("OBS_PASSWORD", "")
    OBS_AUDIO_SOURCE: str = os.getenv("OBS_AUDIO_SOURCE", "")  # メディアソース名（YouTube音声用）

    # Auto talk
    AUTO_TALK_ENABLED: bool = os.getenv("AUTO_TALK_ENABLED", "true").lower() == "true"
    AUTO_TALK_INTERVAL: int = int(os.getenv("AUTO_TALK_INTERVAL", "120"))  # 秒

    # YouTube Chat
    YOUTUBE_ENABLED: bool = os.getenv("YOUTUBE_ENABLED", "false").lower() == "true"
    YOUTUBE_VIDEO_ID: str = os.getenv("YOUTUBE_VIDEO_ID", "")

    # Twitch Chat
    TWITCH_ENABLED: bool = os.getenv("TWITCH_ENABLED", "false").lower() == "true"
    TWITCH_TOKEN: str = os.getenv("TWITCH_TOKEN", "")
    TWITCH_CHANNEL: str = os.getenv("TWITCH_CHANNEL", "")
    TWITCH_CLIENT_ID: str = os.getenv("TWITCH_CLIENT_ID", "")

    # YouTube Controller
    YOUTUBE_CONTROLLER_ENABLED: bool = os.getenv("YOUTUBE_CONTROLLER_ENABLED", "false").lower() == "true"

    # Streaming mode
    MODE: str = os.getenv("AITUBER_MODE", "chat")  # chat | game | stream

    @classmethod
    def load_character(cls) -> dict:
        with open(cls.CHARACTER_FILE, encoding="utf-8") as f:
            return json.load(f)


settings = Settings()
