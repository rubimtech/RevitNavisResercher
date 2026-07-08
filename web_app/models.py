from typing import Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="Ваш вопрос по Revit API / Navisworks API")
    collections: list[str] = Field(default=["revit_api_knowledge"], description="Коллекции Qdrant для поиска")
    limit: int = Field(default=8, ge=1, le=30)
    revit_version: str = Field(default="2024", description="Версия Revit (2021-2027)")


class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=2)
    context: str = Field(..., description="Результаты поиска для анализа")
    instructions: str = Field(default="")


class ResearchWithKeyRequest(SearchRequest):
    api_key: str = Field(..., min_length=8, description="RouterAI API ключ для этого запроса")


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, description="История чата")
    collections: list[str] = Field(default=["revit_api_knowledge"])
    revit_version: str = Field(default="2024")
    search_context: Optional[str] = Field(default=None, description="Контекст предыдущего поиска (results + analysis)")

    # Limit how many messages we accept to avoid abuse
    @property
    def trimmed_messages(self) -> list[ChatMessage]:
        keep = self.messages[-20:]
        return keep


class ChatResponse(BaseModel):
    reply: str
    new_search: Optional[str] = Field(default=None, description="Если AI запросил новый поиск")
    search_results: Optional[dict] = Field(default=None, description="Результаты нового поиска, если был")
