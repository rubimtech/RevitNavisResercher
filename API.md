# RevitNavis Researcher — API Documentation

**Base URL:** `http://d9e0f9d73f7a.vps.myjino.ru`

---

## Health & Config

### `GET /health`

Проверка состояния сервиса.

```
GET http://d9e0f9d73f7a.vps.myjino.ru/health
```

**Response:**
```json
{"status": "ok", "app": "revitnavis-web"}
```

### `GET /api/config`

Конфигурация приложения: доступные Qdrant-коллекции, версии Revit, LLM-провайдер.

```
GET http://d9e0f9d73f7a.vps.myjino.ru/api/config
```

**Response:**
```json
{
  "collections": [
    {"name": "revit_api_knowledge", "label": "Revit API"},
    {"name": "Revit_SDK_Samples",   "label": "Revit SDK Samples"},
    {"name": "navisworks_api_bge",   "label": "Navisworks API"}
  ],
  "revit_versions": ["all (2022-2027)"],
  "llm_provider": "routerai",
  "llm_model": "deepseek/deepseek-v4-flash",
  "embedding_model": "baai/bge-m3",
  "has_api_key": true
}
```

---

## Tree Browser (PostgreSQL)

Эндпоинты для навигации по дереву классов/методов Revit API. Данные из PostgreSQL, сгруппированы по версиям Revit.

### `GET /api/tree/versions`

Список доступных версий Revit.

```
GET http://d9e0f9d73f7a.vps.myjino.ru/api/tree/versions
```

**Response:**
```json
{"versions": ["2022", "2023", "2024", "2025", "2026", "2027"]}
```

### `GET /api/tree/namespaces`

Список namespace'ов первого уровня для указанной версии.

**Parameters:**

| Параметр  | Тип    | По умолчанию | Описание              |
|-----------|--------|-------------|-----------------------|
| `version` | string | `2024`      | Версия Revit          |

```
GET /api/tree/namespaces?version=2024
```

**Response:**
```json
{
  "items": [
    {
      "href": "91957e18-2935-006c-83ab-3b5b9dbb5928.htm",
      "title": "Autodesk.Revit.ApplicationServices Namespace",
      "entry_type": "namespace"
    }
  ]
}
```

### `GET /api/tree/children`

Дочерние элементы узла (классы внутри namespace, методы внутри класса и т.д.).

**Parameters:**

| Параметр  | Тип    | По умолчанию | Описание                      |
|-----------|--------|-------------|-------------------------------|
| `version` | string | `2024`      | Версия Revit                  |
| `parent`  | string | —           | `href` родительского узла     |

```
GET /api/tree/children?version=2024&parent=91957e18-2935-006c-83ab-3b5b9dbb5928.htm
```

**Response:**
```json
{
  "items": [
    {
      "href": "94db8ea8-d2c3-5e71-8030-466bcb8e4426.htm",
      "title": "Application Class",
      "entry_type": "class",
      "child_count": 4,
      "has_content": false
    }
  ]
}
```

Поле `child_count` показывает количество дочерних узлов. `has_content` — наличие markdown-документации.

### `GET /api/tree/content`

Markdown-содержимое и метаданные API-сущности.

**Parameters:**

| Параметр | Тип    | Описание            |
|----------|--------|---------------------|
| `href`   | string | `href` из дерева    |

```
GET /api/tree/content?href=94db8ea8-d2c3-5e71-8030-466bcb8e4426.htm
```

**Response:**
```json
{
  "href": "94db8ea8-d2c3-5e71-8030-466bcb8e4426.htm",
  "title": "Application Class",
  "entry_type": "class",
  "namespace": "Autodesk.Revit.ApplicationServices",
  "description": "",
  "path": "Namespaces/Autodesk.Revit.ApplicationServices Namespace/Application Class",
  "member_of": "",
  "content_md": "# Application Class\n\nRepresents the Revit application..."
}
```

### `GET /api/tree/search`

Полнотекстовый поиск по заголовкам, short_title и path.

**Parameters:**

| Параметр  | Тип    | По умолчанию | Описание                    |
|-----------|--------|-------------|-----------------------------|
| `version` | string | `2024`      | Версия Revit                |
| `q`       | string | —           | Поисковый запрос            |
| `limit`   | int    | `20`        | Максимум результатов        |

```
GET /api/tree/search?version=2024&q=Application&limit=5
```

**Response:**
```json
{
  "items": [
    {
      "href": "94db8ea8-d2c3-5e71-8030-466bcb8e4426.htm",
      "title": "Application Class",
      "entry_type": "class",
      "path": "Namespaces/Autodesk.Revit.ApplicationServices/Application Class",
      "has_content": false
    }
  ]
}
```

Результаты сортируются: точное совпадение → начинается с запроса → содержит запрос.

### `GET /api/tree/code-files`

Список SDK-примеров кода.

**Parameters:**

| Параметр | Тип | По умолчанию | Описание         |
|----------|-----|-------------|------------------|
| `limit`  | int | `20`        | Сколько записей  |
| `offset` | int | `0`         | Смещение         |

```
GET /api/tree/code-files?limit=3
```

**Response:**
```json
{
  "items": [
    {
      "id": "f7f7ad77-0fb5-41a4-bdd3-9dabb490468c",
      "file_name": "IsolatedIndependentAddin.cs",
      "summary": "This code defines an independent Revit add-in..."
    }
  ]
}
```

### `GET /api/tree/code-file`

Полный код SDK-примера.

**Parameters:**

| Параметр | Тип     | Описание          |
|----------|---------|-------------------|
| `id`     | string  | `id` из code-files|

```
GET /api/tree/code-file?id=f7f7ad77-0fb5-41a4-bdd3-9dabb490468c
```

**Response:**
```json
{
  "id": "f7f7ad77-0fb5-41a4-bdd3-9dabb490468c",
  "file_name": "IsolatedIndependentAddin.cs",
  "file_path": "D:\\Revit 2027 SDK\\Samples\\...",
  "summary": "This code defines an independent Revit add-in...",
  "full_code": "using Autodesk.Revit.UI;\n..."
}
```

### `GET /api/tree/diffs`

Изменения API между двумя версиями Revit (added / removed / modified).

**Parameters:**

| Параметр      | Тип    | По умолчанию | Описание             |
|---------------|--------|-------------|----------------------|
| `version_from`| string | —           | Базовая версия       |
| `version_to`  | string | —           | Целевая версия       |
| `limit`       | int    | `100`       |                     |
| `offset`      | int    | `0`         |                     |

```
GET /api/tree/diffs?version_from=2026&version_to=2025&limit=3
```

**Response:**
```json
{
  "version_from": "2026",
  "version_to": "2025",
  "total": 683,
  "items": [
    {
      "version_from": "2026",
      "version_to": "2025",
      "href": "b9e62b52...",
      "diff_type": "added",
      "old_status": null,
      "new_status": null,
      "title": "AirViscosity Property",
      "entry_type": "property",
      "path": "Namespaces/Autodesk.Revit.DB.Mechanical Namespace/..."
    }
  ]
}
```

### `GET /api/tree/whatsnew`

What's New содержимое для указанной версии.

**Parameters:**

| Параметр  | Тип    | Описание        |
|-----------|--------|-----------------|
| `version` | string | Версия Revit    |

```
GET /api/tree/whatsnew?version=2022
```

**Response:**
```json
{
  "version": "2022",
  "items": [
    {
      "id": 1,
      "version": "2022",
      "section": "API Changes (Изменения API)",
      "subsection": "",
      "title": "Parameter API Changes — Migration to ForgeTypeId",
      "content": "...",
      "content_type": "markdown"
    }
  ]
}

---

## Semantic Search (Qdrant)

### `POST /api/search/qdrant`

Поиск по векторной базе Qdrant.

**Request body:**
```json
{
  "query": "create wall",
  "collections": ["revit_api_knowledge"],
  "limit": 8,
  "revit_version": "all"
}
```

| Поле           | Тип      | По умолчанию              | Описание                          |
|----------------|----------|--------------------------|-----------------------------------|
| `query`        | string   | —                        | Поисковый запрос (2–1000 симв.)   |
| `collections`  | string[] | `["revit_api_knowledge"]`| Коллекции Qdrant                  |
| `limit`        | int      | `8`                      | 1–30                              |
| `revit_version`| string   | `"all"`                  | Версия Revit                      |

### `POST /api/search/rvtdocs`

Поиск по локальной SQLite-базе (дублирующий эндпоинт).

**Request body:** тот же формат, что и `/api/search/qdrant`.

---

## Research (Qdrant + LLM)

### `POST /api/research`

Комбинированный поиск (Qdrant + SQLite) + анализ LLM.

**Request body:** тот же `SearchRequest`.

**Response:**
```json
{
  "query": "create wall",
  "revit_version": "all",
  "collections": ["revit_api_knowledge"],
  "qdrant_count": 8,
  "rvtdocs_count": 5,
  "qdrant_results": [...],
  "rvtdocs_results": [...],
  "analysis": "Для создания стены в Revit API используйте Wall.Create..."
}
```

### `POST /api/research/stream`

То же, что `/api/research`, но в формате SSE (Server-Sent Events).

**Events:**

| Event     | Data                                |
|-----------|-------------------------------------|
| `status`  | `{"msg":"Поиск в Qdrant..."}`       |
| `qdrant`  | результаты Qdrant                   |
| `rvtdocs` | результаты локальной БД             |
| `token`   | `{"token":"текст по токену"}`       |
| `done`    | `{}`                                |
| `error`   | `{"error":"сообщение"}`             |

### `POST /api/research/with-key`

Как `/api/research`, но с API-ключом в каждом запросе (не из `.env`).

**Request body:**
```json
{
  "query": "create wall",
  "api_key": "sk-...",
  "collections": ["revit_api_knowledge"],
  "revit_version": "all"
}
```

### `POST /api/research/with-key/stream`

SSE-версия `/api/research/with-key`.

---

## Chat

### `POST /api/chat`

Диалоговый чат: AI может запросить дополнительный поиск через `[SEARCH: ...]`.

**Request body:**
```json
{
  "messages": [
    {"role": "user", "content": "Как создать стену?"}
  ],
  "collections": ["revit_api_knowledge"],
  "revit_version": "all",
  "search_context": null
}
```

| Поле            | Тип        | Описание                    |
|-----------------|------------|-----------------------------|
| `messages`      | ChatMessage[] | История (до 20 сообщений) |
| `search_context`| string|null | Контекст предыдущего поиска |

**Response:**
```json
{
  "reply": "Используйте Wall.Create...",
  "new_search": null,
  "search_results": null
}
```

Если AI запросил новый поиск — `new_search` содержит запрос, `search_results` — результаты.

### `POST /api/chat/stream`

SSE-версия чата.

**Events:**

| Event           | Data                                      |
|-----------------|-------------------------------------------|
| `status`        | `{"msg":"Думаю..."}`                      |
| `token`         | `{"token":"текст по токену"}`             |
| `search_request`| `{"query":"поисковый запрос"}`            |
| `done`          | `{}`                                      |
| `error`         | `{"error":"сообщение"}`                   |

---

## Pages (HTML)

| Endpoint   | Описание                  |
|------------|---------------------------|
| `GET /`    | Главная страница поиска   |
| `GET /chat`| Чат-интерфейс             |
| `GET /tree`| Tree Browser (дерево API) |

---

## Qdrant (векторная БД)

| Endpoint             | Описание          |
|----------------------|-------------------|
| `http://d9e0f9d73f7a.vps.myjino.ru:6333` | Прямой доступ |
| `http://d9e0f9d73f7a.vps.myjino.ru/db/vector/` | Через Nginx  |

---

## MCP Tools (через API)

При установке переменной `RVTDOC_API_URL` MCP-сервер использует HTTP API вместо локальной SQLite.

| MCP Tool                    | HTTP Endpoint          |
|-----------------------------|------------------------|
| `rvtdocs_search`            | `/api/tree/search`     |
| `rvtdocs_get_page`          | `/api/tree/content`    |
| `rvtdocs_cross_version_search` | `/api/tree/search` (по всем версиям) |
| `sql_search_api`            | `/api/tree/search`     |
| `sql_get_api_content`       | `/api/tree/content`    |
| `sql_get_api_hierarchy`     | `/api/tree/namespaces` + `/api/tree/children` |
| `sql_search_api_content`    | `/api/tree/search` + `/api/tree/content` |
