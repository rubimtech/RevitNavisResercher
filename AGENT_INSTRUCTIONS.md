# Agent Instructions: RevitNavisResearcher MCP

> Инструкция для AI-агента (kilo, CUA, Copilot), использующего MCP-сервер `revit-navis-research`.

---

## 📋 Назначение

Ты используешь MCP-сервер **RevitNavisResearcher** для поиска информации по **Revit API**, **Revit SDK Samples** и **Navisworks API**. Сервер умеет:

1. Искать по векторной БД Qdrant (семантический поиск)
2. Искать на rvtdocs.com (классический поиск по документации)
3. Анализировать результаты через LLM (deepseek-v4-flash)
4. Выполнять полный пайплайн исследования

---

## 🛠 Доступные инструменты

### 1. `qdrant_search` — семантический поиск

```python
qdrant_search(
    query="<запрос>",
    collection="revit_api_knowledge",  # revit_api_knowledge | Revit_SDK_Samples | navisworks_api_bge
    limit=10,
    score_threshold=None,             # 0.0–1.0
    include_full_code=False           # подтянуть полный код из SQLite
)
```

**Когда использовать:** пользователь спрашивает про Revit API классы, методы, свойства. Запрос на естественном языке.  
Параметр `include_full_code=True` подгружает полный исходный код из локальной SQLite (`revit_codebase.db`) — полезно для SDK Samples.

### 2. `rvtdocs_search` — поиск по rvtdocs.com

```python
rvtdocs_search(
    query="Wall.Create",  # точное имя класса/метода
    version="2024",       # версия Revit
    limit=10
)
```

**Когда использовать:** нужно точное описание конкретного класса или метода, особенно с указанием версии Revit.

### 3. `rvtdocs_get_page` — полная страница документации

```python
rvtdocs_get_page(
    url="/2024/<guid>",  # полный URL или путь
    version="2024"
)
```

**Когда использовать:** нужно полное описание, синтаксис, примеры кода C#, remarks.  
URL автоматически проверяется на SSRF — только rvtdocs.com.

### 4. `rvtdocs_cross_version_search` — поиск по всем версиям Revit

```python
rvtdocs_cross_version_search(
    query="Wall.Create",
    limit=5,
    versions=["2021","2022","2023","2024","2025","2026","2027"]
)
```

**Когда использовать:** нужно проверить доступность API в разных версиях Revit, узнать когда API появился/изменился.

### 5. `qdrant_collection_info` / `qdrant_list_collections` / `qdrant_get_point`

- `qdrant_collection_info(collection="revit_api_knowledge")` — метаданные коллекции (размер, размерность вектора)
- `qdrant_list_collections()` — список всех коллекций с количеством точек
- `qdrant_get_point(collection="revit_api_knowledge", point_id=123)` — получить конкретный документ по ID

### 6. `analyze` — анализ результатов через LLM

```python
analyze(
    query="<вопрос пользователя>",
    context="<результаты поиска Qdrant/rvtdocs>",
    instructions="<доп. инструкции для LLM>"
)
```

### 7. `research` — полный пайплайн (Qdrant → rvtdocs все версии → LLM)

```python
research(
    query="how to create a wall with parameters",
    revit_version="2024"
)
```

Оптимальный выбор для большинства вопросов: сам ищет в Qdrant, rvtdocs (текущая версия + кросс-версионный поиск по 2021–2027), затем анализирует через LLM с учётом доступности API в разных версиях.

---

## 🧠 Стратегия использования

### 👑 Приоритет: `research`

Для большинства вопросов используй **один вызов `research`** — он делает всё сам.

### 🔍 Когда нужен детальный поиск

Если `research` вернул мало информации:

1. **`qdrant_search`** — семантический поиск (лучше для сложных запросов)
2. **`rvtdocs_search`** — точный поиск класса/метода
3. **`rvtdocs_get_page`** — если нужно полное описание со страницы
4. **`analyze`** — синтезировать всё в ответ пользователю

### 📐 Параметры

| Параметр | Рекомендация |
|----------|-------------|
| `limit` | 5–10 для быстрого ответа, 15–20 для глубокого исследования |
| `collection` | `revit_api_knowledge` — для Revit API, `navisworks_api_bge` — для Navisworks |
| `score_threshold` | Не используй без необходимости. Если качество плохое — попробуй 0.5+ |
| `version` | Всегда указывай версию Revit, если пользователь её назвал. По умолчанию — 2024 |
| `include_full_code` | `true` для SDK Samples — подгружает полный код из `revit_codebase.db` |

### 🌐 Сбор информации

Для максимально полного ответа:
1. Сначала `research(query, revit_version)` — ищет в Qdrant, rvtdocs (текущая версия) и **кросс-версионно** (2021–2027)
2. Если нужно уточнение — `qdrant_search` или `rvtdocs_search` с конкретным именем класса
3. Если нужен пример кода — `rvtdocs_get_page` с URL из результатов `rvtdocs_search`
4. Если нужно понять доступность в разных версиях — `rvtdocs_cross_version_search`

---

## 📝 Примеры

### Пример 1: Создание стены

```
User: Как создать стену в Revit API?

Agent: research(query="create wall with parameters", revit_version="2024")
```

### Пример 2: Поиск конкретного метода

```
User: Как использовать FilteredElementCollector?

Agent: rvtdocs_search(query="FilteredElementCollector", version="2025")
```

### Пример 3: Navisworks

```
User: Как открыть файл в Navisworks API?

Agent: 
1. qdrant_search(query="open file navisworks API", collection="navisworks_api_bge")
2. analyze(query="Как открыть файл?", context="<результаты>")
```

### Пример 4: Глубокое исследование с кросс-версионным поиском

```
User: Нужно получить все элементы стены в определённом bounding box

Agent:
1. research(query="get elements in bounding box filtered element collector", version="2024")
   → автоматически ищет в Qdrant, rvtdocs 2024 и по всем версиям 2021–2027
2. qdrant_search(query="BoundingBoxIntersectsFilter", collection="revit_api_knowledge")
3. rvtdocs_get_page(url="/2024/<guid>")
```

---

## ⚡ Ограничения

- **LLM лимит**: ответы обрезаются после ~25000 символов
- **Qdrant score**: значения ниже 0.5 обычно нерелевантны
- **rvtdocs.com**: доступны версии Revit 2021–2027
- **API-ключ**: если `ROUTERAI_API_KEY` не задан, `research` и `analyze` не работают, но Qdrant поиск доступен.
  Чтобы использовать локальный LLM без API-ключа — установите `LLM_PROVIDER=ollama` в `.env`.

---

## 🐳 Docker-режим

В Docker Compose поднимаются два сервиса:

```bash
docker compose up -d
```

- **MCP-сервер** — SSE endpoint на `http://localhost:8000/mcp`
- **Web App** — FastAPI + фронтенд на `http://localhost:8080`
- **Qdrant** — dashboard на `http://localhost:6333/dashboard`

Если Qdrant запущен на удалённом хосте, укажите `QDRANT_URL` в `.env`:

```
QDRANT_URL=http://remote-host:6333
```

---

## 🔧 Отладка

```
# Проверить коллекции
qdrant_list_collections()

# Информация о конкретной коллекции
qdrant_collection_info(collection="revit_api_knowledge")

# Получить конкретный документ
qdrant_get_point(collection="revit_api_knowledge", point_id=1)

# Поиск по всем версиям Revit
rvtdocs_cross_version_search(query="Wall.Create")
```

---

## 🦙 Локальный режим с Ollama

Для работы без API-ключа можно использовать локальную Ollama:

```bash
# Установить модели
ollama pull nomic-embed-text
ollama pull qwen2.5-coder:7b
```

Настроить `.env`:

```
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
```

После этого все инструменты (`research`, `analyze`) работают через локальную Ollama.
Ollama должна быть запущена (`ollama serve`) до старта сервера.

---

## 🌐 Web App

Проект включает веб-приложение (FastAPI + тёмный UI) для визуального поиска:

```bash
# Запуск локально
python web_app.py

# Открыть в браузере
http://localhost:8080
```

Возможности:
- Поиск по нескольким коллекциям Qdrant одновременно
- Параллельный поиск Qdrant + rvtdocs.com
- SSE-стриминг ответа LLM (токен за токеном)
- История поиска (localStorage)
- URL-параметры для шаринга
- Копирование кода из блоков
