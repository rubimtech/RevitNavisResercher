# RevitNavisResearcher MCP Server

**MCP-сервер** для семантического поиска по документации **Revit API**, **Revit SDK Samples** и **Navisworks API** с использованием векторной БД Qdrant и LLM (RouterAI).

---

## 🚀 Быстрый старт

### 1️⃣ Предварительные требования

- Python 3.12+
- Docker (опционально, для запуска через Docker)
- API-ключ [RouterAI](https://routerai.ru/settings/keys)

### 2️⃣ Установка

```bash
# Клонировать репозиторий
git clone <repo-url>
cd RevitNavisResercher

# Создать и активировать виртуальное окружение
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Установить зависимости
pip install -r requirements.txt

# Настроить окружение
cp .env.example .env
# Отредактировать .env — указать ROUTERAI_API_KEY
```

### 3️⃣ Запуск

```bash
# Режим stdio (для интеграции с kilo / AI assistant)
python mcp_server.py

# Режим SSE (HTTP-сервер на порту 8000)
$env:MCP_TRANSPORT="sse"; python mcp_server.py
```

### 4️⃣ Docker

```bash
# Собрать и запустить полный стек (MCP + Qdrant)
docker compose up -d

# Или только MCP-сервер (если Qdrant уже запущен)
docker build -t revitnavis-mcp .
docker run -p 8000:8000 -e ROUTERAI_API_KEY=sk-xxx revitnavis-mcp

#через .env
docker compose --env-file .env up -d
```

---

## 📚 Инструменты MCP

| Инструмент | Описание |
|-----------|----------|
| `qdrant_search` | Семантический поиск по коллекциям Qdrant (Revit API, SDK Samples, Navisworks) |
| `qdrant_collection_info` | Метаданные коллекции: размер, статус, настройки векторов |
| `qdrant_list_collections` | Список всех доступных коллекций |
| `qdrant_get_point` | Получение конкретного документа из Qdrant по ID |
| `rvtdocs_search` | Поиск по Revit API документации на rvtdocs.com |
| `rvtdocs_get_page` | Полное содержимое страницы документации с примерами кода |
| `rvtdocs_cross_version_search` | Поиск по Revit API сразу во всех версиях (2021–2027) |
| `analyze` | Анализ результатов поиска через LLM (deepseek-v4-flash) |
| `research` | Полный пайплайн: Qdrant → rvtdocs (все версии) → LLM → ответ |

---

## ⚙️ Конфигурация

### Переменные окружения (`.env`)

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `ROUTERAI_API_KEY` | — | API-ключ RouterAI **(обязательно для routerai)** |
| `ROUTERAI_BASE_URL` | `https://routerai.ru/api/v1` | Базовый URL RouterAI |
| `EMBEDDING_MODEL` | `baai/bge-m3` | Модель эмбеддингов (RouterAI) |
| `LLM_MODEL` | `deepseek/deepseek-v4-flash` | Модель LLM для анализа (RouterAI) |
| `LLM_PROVIDER` | `routerai` | Провайдер LLM: `routerai` или `ollama` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL локальной Ollama |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Модель эмбеддингов Ollama |
| `OLLAMA_CHAT_MODEL` | `qwen2.5-coder:7b` | Модель LLM Ollama |
| `QDRANT_URL` | `http://localhost:6333` | URL Qdrant |
| `MCP_TRANSPORT` | `stdio` | Транспорт: `stdio` или `sse` |
| `MCP_HOST` | `0.0.0.0` | Хост для SSE-режима |
| `MCP_PORT` | `8000` | Порт для SSE-режима |

### YAML-конфиг (`mcp_config.yaml`)

Дополнительные настройки вынесены в `mcp_config.yaml`:
- Параметры HTTP-клиента (таймауты, retry)
- Настройки вывода (лимиты символов)
- Поддерживаемые версии Revit
- Настройки логирования

> Переменные окружения имеют приоритет над YAML-конфигом.

---

## 🦙 Локальный режим с Ollama

Для работы без API-ключа можно использовать локальную [Ollama](https://ollama.com):

```bash
# Установить Ollama (один раз)
winget install Ollama.Ollama  # Windows
# или скачать с https://ollama.com/download

# Запустить Ollama
ollama serve

# В другом терминале — скачать модели
ollama pull nomic-embed-text     # для эмбеддингов
ollama pull qwen2.5-coder:7b     # для LLM (~4.7 ГБ)
```

Настроить `.env`:

```
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_CHAT_MODEL=qwen2.5-coder:7b
# ROUTERAI_API_KEY можно не указывать
```

После этого `research`, `analyze` и Web App будут работать через локальную Ollama.

> **Важно:** Ollama должна быть запущена (`ollama serve`) до старта MCP-сервера или Web App.

Файл `docker-compose.yml` поднимает:
- **MCP-сервер** — на порту `8000` (SSE-режим)
- **Web App** — REST API + фронтенд на порту `8080`
- **Qdrant** — векторная БД на порту `6333` (REST) / `6334` (gRPC)

```bash
docker compose up -d
```

---

## 🌐 Web App (REST API + Frontend)

Кроме MCP-сервера, проект включает веб-приложение на FastAPI с современным тёмным UI:

### Запуск локально

```bash
python web_app.py
# или с авто-перезагрузкой:
python web_app.py --reload
```

Откройте `http://localhost:8080` в браузере.

### Возможности Web UI

- Поиск сразу по нескольким коллекциям Qdrant
- Параллельный поиск в Qdrant + rvtdocs.com
- **SSE-стриминг** ответа LLM (потоковая генерация)
- История поиска (сохраняется в localStorage)
- URL-параметры (шаринг результата через ссылку)
- Авто-определение версии Revit

### API Endpoints

| Endpoint | Описание |
|----------|----------|
| `GET /` | Главная страница (фронтенд) |
| `GET /api/config` | Конфигурация сервера (коллекции, версии, модели) |
| `POST /api/search/qdrant` | Семантический поиск по Qdrant |
| `POST /api/search/rvtdocs` | Поиск по документации rvtdocs.com |
| `POST /api/research` | Полный пайплайн: Qdrant + rvtdocs + LLM |
| `POST /api/research/stream` | Полный пайплайн с SSE-стримингом |

### Docker

```bash
# Запуск только веб-приложения:
docker compose up -d web-app
```

---

## 🧪 Примеры использования

```text
# Найти метод для создания стены в Revit API
qdrant_search(query="create wall with parameters", collection="revit_api_knowledge", limit=5)

# Поиск на rvtdocs.com
rvtdocs_search(query="Wall.Create", version="2024")

# Полный research-пайплайн
research(query="how to create a curtain wall in Revit API", revit_version="2025")
```

---

## 🏗 Архитектура

```mermaid
graph TB
    %% ── Стили ──
    classDef client fill:#1f2937,stroke:#6366f1,stroke-width:2px,color:#e2e8f0
    classDef server fill:#0f172a,stroke:#22d3ee,stroke-width:2px,color:#e2e8f0
    classDef storage fill:#0c1929,stroke:#38bdf8,stroke-width:2px,color:#e2e8f0
    classDef external fill:#1a0a2e,stroke:#c084fc,stroke-width:2px,color:#e2e8f0
    classDef router fill:#1a1a2e,stroke:#f59e0b,stroke-width:2px,color:#e2e8f0
    classDef ollama fill:#0f1a0f,stroke:#22c55e,stroke-width:2px,color:#e2e8f0
    classDef web fill:#0f172a,stroke:#f472b6,stroke-width:2px,color:#e2e8f0

    %% ── Клиенты ──
    AI["🤖 AI Assistant<br/>(kilo / CUA / Copilot)"]:::client
    Browser["🌐 Browser<br/>(Web UI)"]:::client

    %% ── MCP Server ──
    subgraph MCP["MCP Server (:8000)"]
        direction TB
        MCP_Tools["🧰 Tools<br/>qdrant_search · rvtdocs_search<br/>rvtdocs_get_page · analyze · research"]:::server
    end

    %% ── Web App ──
    subgraph Web["Web App (:8080)"]
        direction TB
        API["🌍 REST API<br/>/api/search/qdrant · /api/search/rvtdocs<br/>/api/research · /api/research/stream"]:::web
        FE["🎨 Frontend<br/>Dark UI · SSE streaming · History"]:::web
    end

    %% ── Backend Services ──
    subgraph Backend["Backend Services"]
        Qdrant["📊 Qdrant<br/>Vector Database<br/>· revit_api_knowledge<br/>· Revit_SDK_Samples<br/>· navisworks_api_bge"]:::storage
        SQLite["🗄️ SQLite<br/>revit_codebase.db<br/>(full_code по db_id)"]:::storage
    end

    %% ── LLM Providers ──
    subgraph LLM["LLM Providers"]
        RouterAI["☁️ RouterAI<br/>Embedding: bge-m3<br/>Chat: deepseek-v4-flash"]:::router
        Ollama["🦙 Ollama (локально)<br/>Embedding: nomic-embed-text<br/>Chat: qwen2.5-coder:7b"]:::ollama
    end

    %% ── External ──
    RvtDocs["📖 rvtdocs.com<br/>Revit API Docs<br/>(2021–2027)"]:::external

    %% ── Connections ──
    AI -- "stdio / SSE" --> MCP_Tools
    Browser -- "HTTP / SSE" --> API
    API --> FE

    MCP_Tools -- "REST :6333" --> Qdrant
    MCP_Tools --> SQLite
    MCP_Tools -- "HTTP" --> RvtDocs

    API -- "REST :6333" --> Qdrant
    API -- "HTTP" --> RvtDocs

    MCP_Tools -- "LLM_PROVIDER=routerai" --> RouterAI
    MCP_Tools -- "LLM_PROVIDER=ollama" --> Ollama
    API -- "LLM_PROVIDER=routerai" --> RouterAI
    API -- "LLM_PROVIDER=ollama" --> Ollama

    %% ── Links ──
    click Qdrant "http://localhost:6333/dashboard" _blank
    click RvtDocs "https://rvtdocs.com" _blank
```

---

## 🛠 Разработка

```bash
# Установить dev-зависимости
pip install pytest black ruff mypy

# Форматирование
black mcp_server.py

# Проверка типов
mypy mcp_server.py
```

---

## 📄 Лицензия

MIT
