from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    data_dir: Path = Path('data')
    qdrant_url: str = ''
    qdrant_api_key: str | None = None
    qdrant_collection: str = 'knowledge_minilm_v1'
    embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2'
    generation_mode: Literal['ollama', 'extractive'] = 'ollama'
    ollama_url: str = 'http://localhost:11434'
    ollama_model: str = 'llama3.2:3b'
    max_file_mb: int = Field(25, ge=1, le=100)
    max_files: int = Field(10, ge=1, le=20)
    max_pages: int = Field(500, ge=1)
    chunk_tokens: int = Field(220, ge=32, le=220)
    semantic_threshold: float = Field(0.45, ge=-1, le=1)
    retrieval_threshold: float = Field(0.25, ge=-1, le=1)
    cors_origins: list[str] = ['http://localhost:5173', 'http://localhost:3000']
