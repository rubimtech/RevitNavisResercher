import os
from pathlib import Path
from typing import Any, Optional


def deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        elif value is not None:
            base[key] = value


def set_nested(d: dict, keys: list[str], value: Any) -> None:
    current = d
    for k in keys[:-1]:
        current = current.setdefault(k, {})
    current[keys[-1]] = value


def load_config() -> dict[str, Any]:
    cfg_path = Path(__file__).parent.parent / "mcp_config.yaml"
    cfg: dict[str, Any] = {
        "llm": {
            "provider": "routerai",
            "base_url": "https://routerai.ru/api/v1",
            "embedding_model": "baai/bge-m3",
            "chat_model": "deepseek/deepseek-v4-flash",
            "temperature": 0.3,
            "max_tokens": 4096,
        },
        "ollama": {
            "base_url": "http://localhost:11434",
            "embedding_model": "nomic-embed-text",
            "chat_model": "qwen2.5-coder:7b",
        },
        "qdrant": {"url": "https://d9e0f9d73f7a.vps.myjino.ru:6333"},
        "http_client": {"timeout_seconds": 60, "max_retries": 3, "retry_delay_seconds": 1.0, "retry_backoff_factor": 2.0},
        "output": {"character_limit": 25000, "truncate_payload": 400, "truncate_syntax": 200},
        "prompts": {
            "web_research": (
                "You are a Revit API, Revit SDK, and Navisworks API expert. "
                "Answer the question based on the search results. Target Revit version: {revit_version}. "
                "Provide code examples where relevant."
            ),
            "chat": (
                "You are a Revit API, Revit SDK, and Navisworks API expert assistant. "
                "You have search results context available. Answer based on the context. "
                "If you need more information, you can request a new search by outputting exactly:\n"
                "[SEARCH: your search query here]\n"
                "The system will perform a semantic search and provide you with additional results. "
                "Target Revit version: {revit_version}."
            ),
        },
    }
    if cfg_path.exists():
        import yaml
        with open(cfg_path) as f:
            yaml_cfg = yaml.safe_load(f) or {}
            deep_merge(cfg, yaml_cfg)

    env_overrides: dict[str, tuple[str, Optional[type]]] = {
        "llm.provider": ("LLM_PROVIDER", None),
        "llm.base_url": ("ROUTERAI_BASE_URL", None),
        "llm.embedding_model": ("EMBEDDING_MODEL", None),
        "llm.chat_model": ("LLM_MODEL", None),
        "ollama.base_url": ("OLLAMA_BASE_URL", None),
        "ollama.embedding_model": ("OLLAMA_EMBEDDING_MODEL", None),
        "ollama.chat_model": ("OLLAMA_CHAT_MODEL", None),
        "qdrant.url": ("QDRANT_URL", None),
        "http_client.timeout_seconds": ("HTTP_TIMEOUT", int),
        "output.character_limit": ("CHARACTER_LIMIT", int),
    }
    for key, (env_var, cast) in env_overrides.items():
        value = os.environ.get(env_var)
        if value is not None:
            set_nested(cfg, key.split("."), cast(value) if cast else value)
    return cfg


config: dict[str, Any] = {}


def get_cfg(*keys: str, default: Any = None) -> Any:
    current = config
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current if current is not None else default


def llm_provider() -> str:
    return get_cfg("llm", "provider", default="routerai")
