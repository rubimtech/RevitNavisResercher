export interface SearchResult {
  id: string | number;
  score: number;
  collection: string;
  payload: {
    title?: string;
    name?: string;
    class_name?: string;
    method_name?: string;
    header?: string;
    file_name?: string;
    text?: string;
    body?: string;
    content?: string;
    description?: string;
    context?: string;
    chunk_text?: string;
    chunk?: string;
    code?: string;
    snippet?: string;
    example?: string;
    source?: string;
    url?: string;
    link?: string;
    source_file?: string;
    path?: string;
    file?: string;
    [key: string]: any;
  };
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  searchResults?: SearchResult[];
  optimizedQuery?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  selectedCollections: string[];
  createdAt: string;
}

export interface CollectionInfo {
  id: string;
  name: string;
  desc: string;
  pointsCount?: number | null;
}

export interface AppConfig {
  hasApiKey: boolean;
  collections: CollectionInfo[];
  defaultModel: string;
  embeddingModel: string;
  useOllama?: boolean;
  routeraiBaseUrl?: string;
  qdrantUrl?: string;
}

export interface ClientSettings {
  routeraiKey: string;
  routeraiBaseUrl: string;
  qdrantUrl: string;
  llmModel: string;
  embeddingModel: string;
  useOllama: boolean;
}
