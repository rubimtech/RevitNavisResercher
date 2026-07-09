"""
Configuration loading with YAML + env overrides.
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

from portable.paths import get_base_dir

load_dotenv(get_base_dir() / ".env")

DEFAULT_CONFIG_PATH = get_base_dir() / "mcp_config.yaml"


def load_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """Load YAML config, merge with env overrides (env has priority)."""
    cfg: dict[str, Any] = {
        "transport": {"mode": "stdio", "host": "0.0.0.0", "port": 7400},
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
        "qdrant": {
            "url": "http://localhost:6333",
            "include_full_code": False,
            "collections": [
                {"name": "revit_api_knowledge", "description": "Revit API documentation"},
                {"name": "Revit_SDK_Samples", "description": "Revit SDK samples"},
                {"name": "navisworks_api_bge", "description": "Navisworks API documentation"},
                {"name": "revit_api_whatsnew", "description": "Revit API What's New changelogs (2022-2026)"},
            ],
        },
        "constructio": {
            "autocomplete_key": "",
            "client_id": "",
        },
        "http_client": {
            "timeout_seconds": 30,
            "max_retries": 3,
            "retry_delay_seconds": 1.0,
            "retry_backoff_factor": 2.0,
            "verify_ssl": True,
            "max_keepalive": 5,
            "max_connections": 10,
        },
        "output": {
            "character_limit": 25000,
            "truncate_payload": 400,
            "truncate_syntax": 200,
        },
        "revit_versions": ["2021", "2022", "2023", "2024", "2025", "2026", "2027"],
        "prompts": {
            "analyze": (
                "You are a Revit API and Navisworks API research assistant. "
                "Analyze the provided search results and answer the user's question. "
                "Provide specific code examples, API references, and version compatibility notes.\n\n"
                "Для каждого упомянутого API обязательно укажите:\n"
                "1. В какой версии Revit произошли изменения (появился/изменён/удалён метод)\n"
                "2. Если метод изменён — с какой версии использовать новый подход, "
                "что остаётся для старых версий\n"
                "3. Если метод удалён/deprecated — предложите альтернативы/замену\n"
                "4. Если новый API есть только в новых версиях — покажите вариант для старых версий "
                "(старый API, workaround, #if-обёртку)"
            ),
            "research": (
                "You are a Revit API expert. Answer the question based on the provided search results. "
                "Target Revit version: {revit_version}. "
                "IMPORTANT: Check cross-version availability and note when APIs were introduced/changed/deprecated. "
                "Provide code examples relevant to the target version. "
                "If an API is deprecated or not available in {revit_version}, suggest alternatives.\n\n"
                "For EVERY API mentioned, ALWAYS specify:\n"
                "1. В какой версии Revit произошли изменения (появился/изменился/удалён метод)\n"
                "2. Если метод был изменён (появилась новая перегрузка/сигнатура) — укажите, "
                "с какой версии лучше начинать использовать новый подход, а для старых версий оставьте старый\n"
                "3. Если метод удалён/объявлен deprecated — предложите АЛЬТЕРНАТИВЫ: "
                "каким API/подходом можно заменить, как решить ту же задачу БЕЗ этого метода. "
                "Поищите в результатах What's New (changelogs) и Cross-Version подсказки о замене\n"
                "4. Если новый метод/класс есть только в новых версиях (2025+) — "
                "предложите вариант для старых версий: какой API использовался до этого, "
                "как написать #if-обёртку или какой workaround применить\n"
                "5. Если в новых версиях появился более удобный/правильный способ — "
                "покажите оба варианта: новый (с указанием минимальной версии) и старый (для обратной совместимости)"
            ),
        },
        "logging": {"level": "INFO", "format": "text"},
    }

    config_path = config_path or DEFAULT_CONFIG_PATH
    if config_path.exists():
        with open(config_path) as f:
            yaml_cfg = yaml.safe_load(f) or {}
            _deep_merge(cfg, yaml_cfg)

    env_overrides: dict[str, tuple[str, Optional[type]]] = {
        "transport.mode": ("MCP_TRANSPORT", None),
        "transport.host": ("MCP_HOST", None),
        "transport.port": ("MCP_PORT", int),
        "llm.provider": ("LLM_PROVIDER", None),
        "llm.base_url": ("ROUTERAI_BASE_URL", None),
        "llm.embedding_model": ("EMBEDDING_MODEL", None),
        "llm.chat_model": ("LLM_MODEL", None),
        "ollama.base_url": ("OLLAMA_BASE_URL", None),
        "ollama.embedding_model": ("OLLAMA_EMBEDDING_MODEL", None),
        "ollama.chat_model": ("OLLAMA_CHAT_MODEL", None),
        "qdrant.url": ("QDRANT_URL", None),
        "constructio.autocomplete_key": ("CONSTRUCTIO_AUTOCOMPLETE_KEY", None),
        "constructio.client_id": ("CONSTRUCTIO_CLIENT_ID", None),
        "http_client.timeout_seconds": ("HTTP_TIMEOUT", int),
        "output.character_limit": ("CHARACTER_LIMIT", int),
    }
    for key, (env_var, cast) in env_overrides.items():
        value = os.environ.get(env_var)
        if value is not None:
            _set_nested(cfg, key.split("."), cast(value) if cast else value)

    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        elif value is not None:
            base[key] = value


def _set_nested(d: dict, keys: list[str], value: Any) -> None:
    """Set a nested dict value by key path."""
    current = d
    for k in keys[:-1]:
        current = current.setdefault(k, {})
    current[keys[-1]] = value


_config_store: dict[str, Any] = {}


def set_config(cfg: dict[str, Any]) -> None:
    """Store loaded config globally."""
    global _config_store
    _config_store = cfg


def get_cfg(*keys: str, default: Any = None) -> Any:
    """Get nested config value."""
    current = _config_store
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current if current is not None else default
