#!/usr/bin/env python3
"""
Прямой тест analyze_build_errors — без MCP транспорта.
Импортируем и вызываем инструмент напрямую.
"""

import asyncio
import json
import sys
from pathlib import Path

# Настраиваем окружение до импорта server
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Загружаем конфиг
from server.config import load_config, set_config

cfg = load_config()
set_config(cfg)

# Инициализируем логгер
from server.logging_setup import setup_logging
_logger = setup_logging("INFO", "text")

# Импортируем tool-модули (чтобы зарегистрировались на mcp)
import server.tools_qdrant  # noqa: F401
import server.tools_rvtdocs  # noqa: F401
import server.tools_revitapidocs  # noqa: F401
import server.tools_analyze
from server.mcp_instance import mcp


async def main():
    report_path = Path(r"D:\DEV\ReviBE\build-reports\logs\20260708-110826\build-errors-report.md")
    report_content = report_path.read_text(encoding="utf-8")

    print("=" * 60)
    print("📄 Загружен build-errors-report.md")
    print(f"   Размер: {len(report_content)} символов")
    print("=" * 60)

    # Вызываем analyze_build_errors напрямую как функцию
    print("\n🔍 Анализируем ошибки сборки...\n")
    result = await server.tools_analyze.analyze_build_errors(
        report_content=report_content,
        research_apis=False,  # отключаем research API для скорости
    )

    # Парсим JSON результат
    try:
        data = json.loads(result)
        print("=" * 60)
        print("📊 РЕЗУЛЬТАТ АНАЛИЗА")
        print("=" * 60)

        ra = data.get("report_analyzed", {})
        print(f"\n📈 Всего ошибок найдено: {ra.get('total_errors_parsed', '?')}")
        print(f"📌 Затронутые версии: {', '.join(ra.get('versions_affected', []))}")
        print(f"🔤 Уникальные символы: {', '.join(ra.get('unique_symbols', []))}")
        print(f"📋 Категории: {json.dumps(ra.get('error_categories', {}), indent=2, ensure_ascii=False)}")
        print(f"\n🔬 API исследовано: {data.get('apis_researched', 0)}")

        fix_plan = data.get("fix_plan", "")
        if fix_plan:
            print("\n📋 PLAN FIX:")
            print(fix_plan[:3000])
            if len(fix_plan) > 3000:
                print("\n... (truncated)")
    except json.JSONDecodeError:
        print("Результат (не JSON):")
        print(result[:3000])


if __name__ == "__main__":
    asyncio.run(main())
