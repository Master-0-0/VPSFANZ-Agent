import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str = ""
    models: List[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key: str = ""
    providers: Dict[str, ProviderConfig] = Field(default_factory=dict)


class RuntimeConfig(BaseModel):
    interval: int = 3
    max_loops: int = 50
    prompt_group: str = "default"


class TaskConfig(BaseModel):
    timeout: int = 300
    max_intents: int = 3


class TasksConfig(BaseModel):
    bootstrap: TaskConfig = Field(default_factory=lambda: TaskConfig(timeout=300))
    reason: TaskConfig = Field(default_factory=lambda: TaskConfig(timeout=300, max_intents=3))
    explore: TaskConfig = Field(default_factory=lambda: TaskConfig(timeout=300))


class StoreConfig(BaseModel):
    db_path: str = "~/.osint-agent/projects.db"


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    tasks: TasksConfig = Field(default_factory=TasksConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)

    @classmethod
    def load(cls, path=None):
        if path is None:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            project_config = project_root / "config.yaml"
            if project_config.exists():
                path = project_config
            else:
                path = Path("~/.osint-agent/config.yaml").expanduser()
        path = Path(path).expanduser()

        cfg = cls()

        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            if data:
                merged = cls._merge_env(cfg.model_dump(), data)
                cfg = cls(**merged)

        cfg._resolve_env()
        return cfg

    @staticmethod
    def _merge_env(base, override):
        for k, v in override.items():
            if isinstance(v, dict) and k in base and isinstance(base[k], dict):
                base[k] = Config._merge_env(base[k], v)
            else:
                base[k] = v
        return base

    def _resolve_env(self):
        for pname, pc in self.llm.providers.items():
            if pc.api_key.startswith("${") and pc.api_key.endswith("}"):
                env_var = pc.api_key[2:-1]
                pc.api_key = os.environ.get(env_var, "")
        if self.llm.api_key.startswith("${") and self.llm.api_key.endswith("}"):
            env_var = self.llm.api_key[2:-1]
            self.llm.api_key = os.environ.get(env_var, "")

    def resolve_llm_config(self) -> Tuple[str, str, str]:
        provider_name = self.llm.provider
        model = self.llm.model
        api_key = self.llm.api_key

        if provider_name in self.llm.providers:
            pc = self.llm.providers[provider_name]
            if not api_key and pc.api_key:
                api_key = pc.api_key

        base_urls = {
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "ollama": "http://localhost:11434/v1",
        }

        base_url = base_urls.get(provider_name, "https://api.deepseek.com/v1")
        if provider_name in self.llm.providers and self.llm.providers[provider_name].base_url:
            base_url = self.llm.providers[provider_name].base_url

        return base_url, api_key, model
