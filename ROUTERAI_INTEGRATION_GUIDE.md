# Интеграция RouterAI в ваш проект

**RouterAI** — это OpenAI-совместимый API-гейтвей, предоставляющий доступ к LLM (чат) и embedding-моделям.  
Поддерживает любой OpenAI-совместимый HTTP-клиент.

**Сайт:** https://routerai.ru  
**API-ключи:** https://routerai.ru/settings/keys  
**API Base URL:** `https://routerai.ru/api/v1`

---

## 1. Быстрый старт (Python, curl)

### 1.1. Получить API-ключ

Зарегистрируйтесь на https://routerai.ru и создайте ключ в настройках.

### 1.2. Проверка через curl

```bash
# Chat completion
curl https://routerai.ru/api/v1/chat/completions \
  -H "Authorization: Bearer sk-ваш-ключ" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek/deepseek-v4-flash",
    "messages": [{"role": "user", "content": "Привет!"}]
  }'

# Embedding
curl https://routerai.ru/api/v1/embeddings \
  -H "Authorization: Bearer sk-ваш-ключ" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "baai/bge-m3",
    "input": "текст для векторизации"
  }'
```

---

## 2. Доступные модели

| Назначение | Модель | Размерность |
|---|---|---|
| Chat | `deepseek/deepseek-v4-flash` | — |
| Embedding | `baai/bge-m3` | 1024 |

---

## 3. Интеграция в Python

### 3.1. Chat completion (синхронный, httpx)

```python
import os
import httpx

ROUTERAI_API_KEY = os.environ["ROUTERAI_API_KEY"]
ROUTERAI_BASE_URL = os.environ.get("ROUTERAI_BASE_URL", "https://routerai.ru/api/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek/deepseek-v4-flash")

def llm_chat(messages: list[dict], system: str = "") -> str:
    url = f"{ROUTERAI_BASE_URL.rstrip('/')}/chat/completions"
    msgs = [{"role": "system", "content": system}] if system else []
    msgs.extend(messages)

    resp = httpx.post(
        url,
        json={"model": LLM_MODEL, "messages": msgs, "temperature": 0.3, "max_tokens": 4096},
        headers={"Authorization": f"Bearer {ROUTERAI_API_KEY}"},
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

# Использование
answer = llm_chat([{"role": "user", "content": "Что такое Revit API?"}])
print(answer)
```

### 3.2. Chat completion (асинхронный, httpx)

```python
import os
import httpx

async def llm_chat_async(messages: list[dict], system: str = "") -> str:
    url = f"{ROUTERAI_BASE_URL.rstrip('/')}/chat/completions"
    msgs = [{"role": "system", "content": system}] if system else []
    msgs.extend(messages)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json={"model": LLM_MODEL, "messages": msgs, "temperature": 0.3, "max_tokens": 4096},
            headers={"Authorization": f"Bearer {ROUTERAI_API_KEY}"},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
```

### 3.3. Streaming chat (асинхронный)

```python
import json
import os
from typing import AsyncGenerator
import httpx

async def llm_chat_stream(messages: list[dict], system: str = "") -> AsyncGenerator[str, None]:
    url = f"{ROUTERAI_BASE_URL.rstrip('/')}/chat/completions"
    msgs = [{"role": "system", "content": system}] if system else []
    msgs.extend(messages)

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST", url,
            json={"model": LLM_MODEL, "messages": msgs, "temperature": 0.3, "stream": True},
            headers={"Authorization": f"Bearer {ROUTERAI_API_KEY}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except json.JSONDecodeError:
                        continue

# Использование
async def main():
    async for chunk in llm_chat_stream([{"role": "user", "content": "Расскажи про Navisworks API"}]):
        print(chunk, end="", flush=True)
```

### 3.4. Embedding (векторизация текста)

```python
import os
import httpx

async def get_embedding(text: str) -> list[float]:
    url = f"{ROUTERAI_BASE_URL.rstrip('/')}/embeddings"
    model = os.environ.get("EMBEDDING_MODEL", "baai/bge-m3")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json={"model": model, "input": text},
            headers={"Authorization": f"Bearer {ROUTERAI_API_KEY}"},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

# Использование
vector = await get_embedding("поисковый запрос")
print(f"Размерность вектора: {len(vector)}")
```

---

## 4. Переменные окружения (.env)

```env
ROUTERAI_API_KEY=sk-ваш-ключ-здесь
ROUTERAI_BASE_URL=https://routerai.ru/api/v1
LLM_MODEL=deepseek/deepseek-v4-flash
EMBEDDING_MODEL=baai/bge-m3
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=4096
```

Загрузка `.env` в Python:

```python
from dotenv import load_dotenv
load_dotenv()
```

---

## 5. Интеграция в Node.js / TypeScript

```typescript
const ROUTERAI_API_KEY = process.env.ROUTERAI_API_KEY!;
const ROUTERAI_BASE_URL = process.env.ROUTERAI_BASE_URL || "https://routerai.ru/api/v1";

// Chat completion
async function llmChat(messages: { role: string; content: string }[], system = "") {
  const msgs = system ? [{ role: "system", content: system }, ...messages] : messages;

  const resp = await fetch(`${ROUTERAI_BASE_URL}/chat/completions`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${ROUTERAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: process.env.LLM_MODEL || "deepseek/deepseek-v4-flash",
      messages: msgs,
      temperature: 0.3,
      max_tokens: 4096,
    }),
  });
  const data = await resp.json();
  return data.choices[0].message.content;
}

// Chat streaming
async function* llmChatStream(messages: { role: string; content: string }[], system = "") {
  const msgs = system ? [{ role: "system", content: system }, ...messages] : messages;

  const resp = await fetch(`${ROUTERAI_BASE_URL}/chat/completions`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${ROUTERAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: process.env.LLM_MODEL || "deepseek/deepseek-v4-flash",
      messages: msgs,
      temperature: 0.3,
      stream: true,
    }),
  });

  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const dataStr = line.slice(6).trim();
        if (dataStr === "[DONE]") return;
        try {
          const data = JSON.parse(dataStr);
          const delta = data.choices?.[0]?.delta?.content || "";
          if (delta) yield delta;
        } catch { /* skip */ }
      }
    }
  }
}

// Embedding
async function getEmbedding(text: string): Promise<number[]> {
  const resp = await fetch(`${ROUTERAI_BASE_URL}/embeddings`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${ROUTERAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: process.env.EMBEDDING_MODEL || "baai/bge-m3",
      input: text,
    }),
  });
  const data = await resp.json();
  return data.data[0].embedding;
}
```

---

## 6. Интеграция с Kilo (kilo.json)

```json
{
  "model": "openai/deepseek/deepseek-v4-flash",
  "provider": {
    "openai": {
      "options": {
        "apiKey": "${ROUTERAI_API_KEY}",
        "baseURL": "https://routerai.ru/api/v1"
      }
    }
  }
}
```

---

## 7. Абстракция провайдера (RouterAI / Ollama)

Если нужно переключаться между RouterAI (облачный) и Ollama (локальный):

```python
import os

PROVIDER = os.environ.get("LLM_PROVIDER", "routerai")  # или "ollama"

async def get_embedding(text: str) -> list[float]:
    if PROVIDER == "ollama":
        return await _ollama_embedding(text)
    return await _routerai_embedding(text)

async def llm_chat(messages: list[dict], system: str = "") -> str:
    if PROVIDER == "ollama":
        return await _ollama_chat(messages, system=system)
    return await _routerai_chat(messages, system=system)
```

---

## 8. Важные замечания

1. **OpenAI-совместимость** — RouterAI использует тот же формат запросов, что и OpenAI API. Любой OpenAI-клиент (openai Python SDK, LangChain, Vercel AI SDK и т.д.) может работать с RouterAI, просто сменив `base_url` и `api_key`.
2. **Bearer-аутентификация** — ключ передаётся в заголовке `Authorization: Bearer sk-...`.
3. **Per-request ключи** — можно передавать разный API-ключ для каждого запроса (полезно для мультитенантных приложений).
4. **Ретраи** — при сетевых ошибках рекомендуется делать повторные попытки с экспоненциальной задержкой.
5. **Кэширование** — для повторяющихся запросов (особенно embedding) используйте кэш, чтобы не тратить лимиты API.
