from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    youtube_stream_key: str = ""
    db_path: str = "database/news.db"
    fetch_interval_minutes: int = 15
    max_news_per_cycle: int = 50
    video_output_dir: str = "video/output"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    # AI provider: "anthropic" | "ollama" | "none"
    ai_provider: str = "none"

    # Ollama settings
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_api_key: str = ""

    # Batch pipeline settings
    batch_top_n_per_source: int = 5
    batch_min_videos_before_stream: int = 3
    batch_stream_after_generation: bool = False
    batch_cleanup_older_days: int = 1
    batch_max_parallel_generations: int = 2

    # Stream settings
    stream_rtmp_url: str = "rtmp://a.rtmp.youtube.com/live2"
    stream_ffmpeg_preset: str = "veryfast"
    stream_video_bitrate: str = "3000k"
    stream_audio_bitrate: str = "128k"

    @property
    def ai_available(self) -> bool:
        if self.ai_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.ai_provider == "ollama":
            return True
        return False

    @property
    def db_url(self) -> str:
        return f"sqlite:///{BASE_DIR / self.db_path}"

    @property
    def video_output_path(self) -> Path:
        return BASE_DIR / self.video_output_dir

    @property
    def sources_path(self) -> Path:
        return BASE_DIR / "config" / "sources.yaml"

    @property
    def personas_path(self) -> Path:
        return BASE_DIR / "config" / "personas.yaml"

    @property
    def schedule_path(self) -> Path:
        return BASE_DIR / "config" / "schedule.yaml"


settings = Settings()
