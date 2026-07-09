# Docker Setup & Test Instructions for RevitNavisResearcher

Этот файл содержит пошаговую инструкцию для AI-агента по установке, развертыванию в Docker и тестированию проекта **RevitNavisResearcher MCP Server**.

## 1. Проверка окружения

Перед началом убедись, что на машине установлены:

```bash
# Проверить Docker
docker --version
docker compose version

# Проверить Python (для локальных тестов)
python --version
```

Если Docker не установлен — **остановись и сообщи пользователю**.

## 2. Настройка .env

Файл `.env` должен существовать в корне проекта. Если его нет — скопируй из `.env.example`:

```bash
cp .env.example .env
```

**Обязательно:** попроси пользователя указать `ROUTERAI_API_KEY` в `.env` (ключ с https://routerai.ru/settings/keys). Если ключа нет — можно использовать Ollama (локально), установив `LLM_PROVIDER=ollama`.

Для Docker Compose важно:
```env
MCP_TRANSPORT=sse
MCP_HOST=0.0.0.0
MCP_PORT=7400
```

## 3. Проверка наличия файлов БД

Docker Compose монтирует `revit_api.db` и `revit_codebase.db` как volumes. Убедись что файлы существуют:

```bash
ls -la revit_api.db revit_codebase.db
```

Если файлов нет — запусти ингрестию перед Docker:
```bash
pip install -r requirements.txt
python ingest_api_content.py --recreate
```

## 4. Сборка Docker образов

```bash
docker compose build
```

Эта команда соберет два образа:
- `revitnavis-mcp` — MCP сервер (из Dockerfile)
- `revitnavis-web` — Web приложение (из Dockerfile.web)

Сборка может занять 2-5 минут (установка Python пакетов).

## 5. Запуск контейнеров

```bash
docker compose up -d
```

Проверь что оба контейнера запущены:

```bash
docker compose ps
```

Ожидаемый вывод:
```
NAME                IMAGE                COMMAND                  SERVICE      STATUS         PORTS
revitnavis-mcp      revitnavis-mcp       "python mcp_server.py"   mcp-server   Up 2 minutes   0.0.0.0:7400->7400/tcp
revitnavis-web      revitnavis-web       "python web_app.py"      web-app      Up 2 minutes   0.0.0.0:7401->7401/tcp
```

Также проверь логи на ошибки:

```bash
docker compose logs --tail=50
```

## 6. Тестирование

### 6.1. Проверка Web UI

Открой в браузере:
- **Web App**: http://localhost:7401
- Должна загрузиться темная тема с поисковой строкой.

Проверь консоль браузера и Network-запросы — не должно быть 5xx ошибок.

### 6.2. Проверка API Health

```bash
# Проверить что MCP Server отвечает (SSE endpoint)
curl -s -o /dev/null -w "%{http_code}" http://localhost:7400/health || echo "SSE endpoint"

# Проверить Web API
curl -s http://localhost:7401/api/config | python -m json.tool
```

### 6.3. Проверка поиска через Web API

```bash
curl -s -X POST http://localhost:7401/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Document", "limit": 5}' \
  | python -m json.tool
```

Ожидается: JSON с результатами поиска (поле `results`), без ошибок.

### 6.4. Проверка MCP через stdio (альтернатива)

Если `mcp_server.py` может работать в stdio режиме — протестируй локально:

```bash
# Временный тест (вне Docker)
python test_mcp_client.py
```

### 6.5. Проверка чата (Web)

```bash
curl -s -X POST http://localhost:7401/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Что такое Document API в Revit?", "search_results": []}' \
  | python -m json.tool
```

## 7. Остановка и очистка

```bash
# Остановить контейнеры
docker compose down

# Остановить и удалить volumes (осторожно — удалит данные)
docker compose down -v

# Пересобрать с нуля (без кэша)
docker compose build --no-cache
```

## 8. Типичные проблемы и решения

### 8.1. Контейнер не стартует (exit code 1)
```bash
docker compose logs mcp-server
```
Возможные причины:
- Нет `ROUTERAI_API_KEY` в `.env`
- Файлы БД не смонтированы (проверь пути в `volumes:`)
- Port 7400/7401 занят (смени порт в docker-compose.yml)

### 8.2. Web UI открывается но поиск не работает
```bash
docker compose logs web-app
```
Проверь что Qdrant URL в конфиге корректен (если используется внешний Qdrant).

### 8.3. "Connection refused" на localhost:7400/7401
```bash
# Проверь что порты опубликованы
docker compose ps
# Проверь что нет firewall блокировок
netstat -an | findstr 7400
netstat -an | findstr 7401
```

### 8.4. Ошибка "ModuleNotFoundError" при сборке
```bash
# Проверь requirements.txt и Dockerfile
# Возможно нужен pip install с дополнительными зависимостями
```

## 9. Что делать если всё работает

Сообщи пользователю, что:
- **MCP Server**: http://localhost:7400 (SSE transport)
- **Web App (UI)**: http://localhost:7401
- Оба сервиса запущены, поиск работает
- Если пользователь использует Kilo/другой AI-клиент — обнови `kilo.json` с `mcpTransport` и `mcpPort`
