import { useState, useEffect, useRef } from "react";
import { 
  Send, Sparkles, Code, AlertTriangle, Menu, BookOpen, Terminal, 
  ArrowRight, Search, Cpu, Database, HelpCircle, Check, Copy, Maximize2,
  Settings, Sliders
} from "lucide-react";
import Sidebar from "./components/Sidebar";
import SearchResultViewer from "./components/SearchResultViewer";
import { Message, ChatSession, AppConfig, SearchResult, ClientSettings } from "./types";
import { extractDocumentFields, getCollectionBadgeStyles, getCollectionFriendlyName } from "./utils";
import Markdown from "react-markdown";

// Default template prompts to guide Revit/Navisworks developers
const SUGGESTED_PROMPTS = [
  {
    title: "Revit Transactions",
    prompt: "How do I open and commit a Transaction in Revit? Provide a C# sample showing the using block.",
    icon: Code,
    category: "Transactions"
  },
  {
    title: "Filter Elements",
    prompt: "Show me how to filter all Walls of a specific type using FilteredElementCollector in C#.",
    icon: Search,
    category: "Collectors"
  },
  {
    title: "What's New 2026",
    prompt: "What are the most important changes or new features in the Revit 2026 API?",
    icon: Cpu,
    category: "Changelogs"
  },
  {
    title: "Navisworks Automation",
    prompt: "How do I perform a search in Navisworks using the Search API and C#? Provide an SDK code pattern.",
    icon: Database,
    category: "Navisworks"
  }
];

export default function App() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [selectedCollections, setSelectedCollections] = useState<string[]>([
    "revit_api_knowledge",
    "Revit_SDK_Samples",
    "revit_api_whatsnew",
    "navisworks_api_bge"
  ]);
  const [input, setInput] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  
  // Settings state
  const [settings, setSettings] = useState<ClientSettings>({
    routeraiKey: localStorage.getItem("setting_routerai_key") || "",
    routeraiBaseUrl: localStorage.getItem("setting_routerai_base_url") || "",
    qdrantUrl: localStorage.getItem("setting_qdrant_url") || "",
    llmModel: localStorage.getItem("setting_llm_model") || "",
    embeddingModel: localStorage.getItem("setting_embedding_model") || "",
    useOllama: localStorage.getItem("setting_use_ollama") === "true"
  });
  
  // UI states
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(false);
  const [inspectorOpen, setInspectorOpen] = useState<boolean>(false);
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);
  const [inspectorResults, setInspectorResults] = useState<SearchResult[]>([]);
  const [activeTab, setActiveTab] = useState<"chat" | "search">("chat");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [searchResultsDirect, setSearchResultsDirect] = useState<SearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState<boolean>(false);
  const [optimizedQuery, setOptimizedQuery] = useState<string>("");

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Helper to construct headers with custom config for all requests
  const getRequestHeaders = () => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json"
    };
    if (settings.routeraiKey) headers["x-routerai-key"] = settings.routeraiKey;
    if (settings.routeraiBaseUrl) headers["x-routerai-base-url"] = settings.routeraiBaseUrl;
    if (settings.qdrantUrl) headers["x-qdrant-url"] = settings.qdrantUrl;
    if (settings.llmModel) headers["x-llm-model"] = settings.llmModel;
    if (settings.embeddingModel) headers["x-embedding-model"] = settings.embeddingModel;
    headers["x-use-ollama"] = settings.useOllama ? "true" : "false";
    return headers;
  };

  // 1. Load config from API
  useEffect(() => {
    const headers: Record<string, string> = {};
    const savedKey = localStorage.getItem("setting_routerai_key");
    const savedBaseUrl = localStorage.getItem("setting_routerai_base_url");
    const savedQdrantUrl = localStorage.getItem("setting_qdrant_url");
    const savedLlmModel = localStorage.getItem("setting_llm_model");
    const savedEmbeddingModel = localStorage.getItem("setting_embedding_model");
    const savedUseOllama = localStorage.getItem("setting_use_ollama");

    if (savedKey) headers["x-routerai-key"] = savedKey;
    if (savedBaseUrl) headers["x-routerai-base-url"] = savedBaseUrl;
    if (savedQdrantUrl) headers["x-qdrant-url"] = savedQdrantUrl;
    if (savedLlmModel) headers["x-llm-model"] = savedLlmModel;
    if (savedEmbeddingModel) headers["x-embedding-model"] = savedEmbeddingModel;
    if (savedUseOllama) headers["x-use-ollama"] = savedUseOllama;

    fetch("/api/config", { headers })
      .then((res) => res.json())
      .then((data: AppConfig) => {
        setAppConfig(data);
        
        // Populate default values into settings if they were not already customized in localStorage
        setSettings({
          routeraiKey: savedKey || "",
          routeraiBaseUrl: savedBaseUrl || data.routeraiBaseUrl || "https://routerai.ru/api/v1",
          qdrantUrl: savedQdrantUrl || data.qdrantUrl || "http://d9e0f9d73f7a.vps.myjino.ru:6333",
          llmModel: savedLlmModel || data.defaultModel || "deepseek/deepseek-v4-flash",
          embeddingModel: savedEmbeddingModel || data.embeddingModel || "baai/bge-m3",
          useOllama: savedUseOllama === "true" || (savedUseOllama === null && !!data.useOllama)
        });
      })
      .catch((err) => {
        console.error("Failed to load app config from server:", err);
      });
  }, []);

  // 2. Load sessions from localStorage on init
  useEffect(() => {
    const saved = localStorage.getItem("revit_api_sessions");
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (parsed && Array.isArray(parsed) && parsed.length > 0) {
          setSessions(parsed);
          setActiveSessionId(parsed[0].id);
          return;
        }
      } catch (err) {
        console.error("Failed to parse localStorage sessions:", err);
      }
    }
    
    // Create an initial session if none exist
    const initialSession: ChatSession = {
      id: "session_" + Date.now(),
      title: "Welcome Thread",
      messages: [
        {
          id: "welcome_msg",
          role: "assistant",
          content: "Привет! Я эксперт-ассистент по **Revit API, Revit SDK Samples, Navisworks API** и изменениям версий Autodesk 2022–2026.\n\nЗадайте мне любой вопрос о написании плагинов, транзакциях, фильтрах элементов или о нововведениях. Я подключен к векторной базе данных **Qdrant RAG**, чтобы находить реальные документации и фрагменты кода!",
          timestamp: new Date().toISOString()
        }
      ],
      selectedCollections: [
        "revit_api_knowledge",
        "Revit_SDK_Samples",
        "revit_api_whatsnew",
        "navisworks_api_bge"
      ],
      createdAt: new Date().toISOString()
    };
    setSessions([initialSession]);
    setActiveSessionId(initialSession.id);
  }, []);

  // 3. Save sessions to localStorage whenever they change
  useEffect(() => {
    if (sessions.length > 0) {
      localStorage.setItem("revit_api_sessions", JSON.stringify(sessions));
    }
  }, [sessions]);

  // 4. Auto scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [sessions, activeSessionId, loading]);

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  // Manage sessions
  const handleSelectSession = (id: string) => {
    setActiveSessionId(id);
    setSidebarOpen(false);
  };

  const handleNewSession = () => {
    const newSession: ChatSession = {
      id: "session_" + Date.now(),
      title: "New Research " + (sessions.length + 1),
      messages: [
        {
          id: "welcome_msg_" + Date.now(),
          role: "assistant",
          content: "Привет! Начнем новое исследование. Задайте вопрос о Revit API или выберите одну из тем ниже.",
          timestamp: new Date().toISOString()
        }
      ],
      selectedCollections: [...selectedCollections],
      createdAt: new Date().toISOString()
    };
    setSessions([newSession, ...sessions]);
    setActiveSessionId(newSession.id);
    setSidebarOpen(false);
  };

  const handleDeleteSession = (id: string) => {
    const filtered = sessions.filter((s) => s.id !== id);
    setSessions(filtered);
    if (filtered.length > 0) {
      if (activeSessionId === id) {
        setActiveSessionId(filtered[0].id);
      }
    } else {
      // Re-create a default session if all deleted
      const initialSession: ChatSession = {
        id: "session_" + Date.now(),
        title: "Welcome Thread",
        messages: [
          {
            id: "welcome_msg",
            role: "assistant",
            content: "Привет! Я эксперт-ассистент по **Revit API, Revit SDK Samples, Navisworks API**.\n\nЗадайте вопрос, чтобы начать!",
            timestamp: new Date().toISOString()
          }
        ],
        selectedCollections: [...selectedCollections],
        createdAt: new Date().toISOString()
      };
      setSessions([initialSession]);
      setActiveSessionId(initialSession.id);
    }
  };

  const handleToggleCollection = (id: string) => {
    let updated;
    if (selectedCollections.includes(id)) {
      updated = selectedCollections.filter((c) => c !== id);
    } else {
      updated = [...selectedCollections, id];
    }
    setSelectedCollections(updated);
    
    // Also save in current session config
    if (activeSessionId) {
      setSessions(
        sessions.map((s) => {
          if (s.id === activeSessionId) {
            return { ...s, selectedCollections: updated };
          }
          return s;
        })
      );
    }
  };

  const handleSaveSettings = () => {
    localStorage.setItem("setting_routerai_key", settings.routeraiKey);
    localStorage.setItem("setting_routerai_base_url", settings.routeraiBaseUrl);
    localStorage.setItem("setting_qdrant_url", settings.qdrantUrl);
    localStorage.setItem("setting_llm_model", settings.llmModel);
    localStorage.setItem("setting_embedding_model", settings.embeddingModel);
    localStorage.setItem("setting_use_ollama", settings.useOllama ? "true" : "false");

    // Re-fetch config to refresh status on sidebar/UI
    const headers = {
      "Content-Type": "application/json",
      "x-routerai-key": settings.routeraiKey,
      "x-routerai-base-url": settings.routeraiBaseUrl,
      "x-qdrant-url": settings.qdrantUrl,
      "x-llm-model": settings.llmModel,
      "x-embedding-model": settings.embeddingModel,
      "x-use-ollama": settings.useOllama ? "true" : "false"
    };

    fetch("/api/config", { headers })
      .then((res) => res.json())
      .then((data: AppConfig) => {
        setAppConfig(data);
      })
      .catch((err) => {
        console.error("Failed to re-fetch config with custom settings:", err);
      });

    setSettingsOpen(false);
  };

  const handleResetSettings = () => {
    localStorage.removeItem("setting_routerai_key");
    localStorage.removeItem("setting_routerai_base_url");
    localStorage.removeItem("setting_qdrant_url");
    localStorage.removeItem("setting_llm_model");
    localStorage.removeItem("setting_embedding_model");
    localStorage.removeItem("setting_use_ollama");

    fetch("/api/config")
      .then((res) => res.json())
      .then((data: AppConfig) => {
        setAppConfig(data);
        setSettings({
          routeraiKey: "",
          routeraiBaseUrl: data.routeraiBaseUrl || "https://routerai.ru/api/v1",
          qdrantUrl: data.qdrantUrl || "http://d9e0f9d73f7a.vps.myjino.ru:6333",
          llmModel: data.defaultModel || "deepseek/deepseek-v4-flash",
          embeddingModel: data.embeddingModel || "baai/bge-m3",
          useOllama: !!data.useOllama
        });
      })
      .catch((err) => {
        console.error("Failed to reset config:", err);
      });

    setSettingsOpen(false);
  };

  // Submit search query directly to Qdrant (Search Tab)
  const handleDirectSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setSearchLoading(true);
    try {
      const resp = await fetch("/api/search", {
        method: "POST",
        headers: getRequestHeaders(),
        body: JSON.stringify({
          query: searchQuery,
          collections: selectedCollections,
          limit: 6
        })
      });

      if (!resp.ok) {
        throw new Error("Failed to search Qdrant DB. Status: " + resp.status);
      }

      const data = await resp.json();
      setSearchResultsDirect(data.results || []);
      setOptimizedQuery(data.optimizedQuery || "");
    } catch (err: any) {
      console.error("Direct search error:", err);
      alert("Error searching database: " + err.message);
    } finally {
      setSearchLoading(false);
    }
  };

  // Send message in the chat
  const handleSendMessage = async (textToSend: string) => {
    if (!textToSend.trim() || !activeSessionId) return;

    const userMessage: Message = {
      id: "msg_" + Date.now(),
      role: "user",
      content: textToSend,
      timestamp: new Date().toISOString()
    };

    // Update session state with user message
    let updatedMessages = [...(activeSession?.messages || []), userMessage];
    
    // Automatically set a smart title if this is the first real question in the session
    let updatedTitle = activeSession?.title || "Research Thread";
    if (activeSession && activeSession.messages.length <= 1) {
      updatedTitle = textToSend.length > 30 ? textToSend.substring(0, 30) + "..." : textToSend;
    }

    setSessions(
      sessions.map((s) => {
        if (s.id === activeSessionId) {
          return {
            ...s,
            title: updatedTitle,
            messages: updatedMessages
          };
        }
        return s;
      })
    );

    setInput("");
    setLoading(true);

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: getRequestHeaders(),
        body: JSON.stringify({
          messages: updatedMessages.map((m) => ({ role: m.role, content: m.content })),
          collections: selectedCollections
        })
      });

      if (!resp.ok) {
        const errText = await resp.text();
        throw new Error(errText || "Unknown network error");
      }

      const data = await resp.json();
      
      const assistantMessage: Message = {
        id: "msg_assistant_" + Date.now(),
        role: "assistant",
        content: data.answer,
        searchResults: data.searchResults || [],
        optimizedQuery: data.optimizedQuery || "",
        timestamp: new Date().toISOString()
      };

      setSessions(
        sessions.map((s) => {
          if (s.id === activeSessionId) {
            return {
              ...s,
              messages: [...updatedMessages, assistantMessage]
            };
          }
          return s;
        })
      );

      // If search results were found, auto-load them into the inspector results state
      if (data.searchResults && data.searchResults.length > 0) {
        setInspectorResults(data.searchResults);
      }

    } catch (err: any) {
      console.error("Chat error:", err);
      
      const errorMessage: Message = {
        id: "msg_error_" + Date.now(),
        role: "assistant",
        content: `❌ **Error sending query:** ${err.message || "Please make sure you have loaded the correct ROUTERAI_API_KEY inside the workspace env/secrets panels."}`,
        timestamp: new Date().toISOString()
      };

      setSessions(
        sessions.map((s) => {
          if (s.id === activeSessionId) {
            return {
              ...s,
              messages: [...updatedMessages, errorMessage]
            };
          }
          return s;
        })
      );
    } finally {
      setLoading(false);
    }
  };

  const handleOpenInspector = (results: SearchResult[]) => {
    setInspectorResults(results);
    setInspectorOpen(true);
  };

  return (
    <div id="app-root" className="h-screen max-h-screen overflow-hidden bg-[#0A0B10] text-slate-100 font-sans flex flex-col md:flex-row">
      
      {/* Sidebar (Session management and filter selectors) */}
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
        selectedCollections={selectedCollections}
        onToggleCollection={handleToggleCollection}
        appConfig={appConfig}
        sidebarOpen={sidebarOpen}
        onCloseSidebar={() => setSidebarOpen(false)}
      />

      {/* Main Work Area */}
      <main className="flex-1 flex flex-col min-h-0 bg-[#0A0B10] relative">
        {/* Top Navbar */}
        <header id="main-nav" className="h-16 border-b border-slate-800 px-4 flex items-center justify-between gap-4 bg-[#15171F] sticky top-0 z-30">
          <div className="flex items-center gap-3">
            <button
              id="sidebar-toggle"
              onClick={() => setSidebarOpen(true)}
              className="p-2 -ml-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg md:hidden"
            >
              <Menu size={20} />
            </button>
            <div className="hidden sm:block">
              <h2 className="text-sm font-semibold text-white leading-tight">
                {activeTab === "chat" ? (activeSession?.title || "Revit Chat") : "Direct Qdrant Search"}
              </h2>
              <p className="text-[10px] text-slate-400 font-medium tracking-wide">
                {selectedCollections.length} vector datasets selected
              </p>
            </div>
          </div>

          {/* Tab Switcher */}
          <div className="flex items-center bg-[#0D0E12] p-1 rounded-lg border border-slate-800">
            <button
              id="tab-chat"
              onClick={() => setActiveTab("chat")}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all cursor-pointer ${
                activeTab === "chat"
                  ? "bg-[#1C1F26] text-cyan-400 shadow-sm border border-slate-700/40"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Expert Chat
            </button>
            <button
              id="tab-search"
              onClick={() => setActiveTab("search")}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all cursor-pointer ${
                activeTab === "search"
                  ? "bg-[#1C1F26] text-cyan-400 shadow-sm border border-slate-700/40"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Qdrant Browser
            </button>
          </div>

          {/* Inspector quick trigger */}
          <div className="flex items-center gap-2">
            {inspectorResults.length > 0 && (
              <button
                id="btn-trigger-inspector"
                onClick={() => setInspectorOpen(true)}
                className="px-3 py-1.5 bg-cyan-950/40 hover:bg-cyan-900/40 border border-cyan-800/40 rounded-lg text-xs font-semibold text-cyan-400 flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <Sparkles size={13} className="animate-pulse" />
                <span>Matches ({inspectorResults.length})</span>
              </button>
            )}
            <button
              id="btn-open-settings"
              onClick={() => setSettingsOpen(true)}
              className="px-3 py-1.5 bg-[#1C1F26] hover:bg-[#252A36] border border-slate-700/60 rounded-lg text-xs font-semibold text-slate-300 flex items-center gap-1.5 transition-colors cursor-pointer"
            >
              <Settings size={13} />
              <span>Settings</span>
            </button>
          </div>
        </header>

        {/* Tab 1: Expert Chat */}
        {activeTab === "chat" && (
          <div className="flex-1 flex flex-col min-h-0 relative bg-[#0A0B10]">
            {/* Conversation Log */}
            <div className="flex-1 overflow-y-auto px-4 py-6 md:p-8 space-y-6">
              {activeSession?.messages.map((message) => {
                const isUser = message.role === "user";
                return (
                  <div
                    key={message.id}
                    className={`flex gap-4 max-w-3xl ${isUser ? "ml-auto flex-row-reverse" : "mr-auto"}`}
                  >
                    {/* Icon */}
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border ${
                      isUser 
                        ? "bg-[#1C1F26] border-slate-800 text-cyan-400" 
                        : "bg-cyan-500 border-cyan-600 text-black font-bold"
                    }`}>
                      {isUser ? <HelpCircle size={15} /> : <Terminal size={14} />}
                    </div>

                    {/* Speech Area */}
                    <div className="space-y-2">
                      <div className={`p-4 rounded-xl border leading-relaxed ${
                        isUser
                          ? "bg-[#1C1F26]/75 border-slate-800 text-slate-100 rounded-tr-none"
                          : "bg-[#15171F] border-slate-800 text-slate-200 rounded-tl-none shadow-sm"
                      }`}>
                        {isUser ? (
                          <p className="text-sm font-medium whitespace-pre-wrap">{message.content}</p>
                        ) : (
                          <div className="text-sm prose prose-invert max-w-none prose-sm font-sans">
                            <Markdown
                              components={{
                                code({ node, className, children, ...props }) {
                                  const match = /language-(\w+)/.exec(className || "");
                                  return match ? (
                                    <div className="relative my-3 rounded-lg overflow-hidden border border-slate-800">
                                      <div className="bg-[#1C1F26] px-3 py-1 text-[10px] text-slate-400 font-mono flex items-center justify-between border-b border-slate-800">
                                        <span>{match[1].toUpperCase()}</span>
                                        <button
                                          onClick={() => navigator.clipboard.writeText(String(children).replace(/\n$/, ""))}
                                          className="text-[10px] text-slate-400 hover:text-white flex items-center gap-1 transition-colors cursor-pointer"
                                        >
                                          Copy
                                        </button>
                                      </div>
                                      <pre className="bg-[#0D0E12] p-4 overflow-x-auto text-xs font-mono text-slate-200 max-h-96">
                                        <code>{children}</code>
                                      </pre>
                                    </div>
                                  ) : (
                                    <code className="bg-slate-800/80 text-rose-400 px-1 py-0.5 rounded text-xs font-mono" {...props}>
                                      {children}
                                    </code>
                                  );
                                }
                              }}
                            >
                              {message.content}
                            </Markdown>
                          </div>
                        )}
                        <span className="text-[10px] text-slate-500 font-mono block text-right mt-2">
                          {new Date(message.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      </div>

                      {/* Display Search Result Badge under Response */}
                      {!isUser && message.searchResults && message.searchResults.length > 0 && (
                        <div className="flex flex-col gap-1.5 mt-1.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">
                              RAG Sources:
                            </span>
                            {message.searchResults.slice(0, 3).map((res, i) => {
                              const info = extractDocumentFields(res.payload);
                              return (
                                <button
                                  id={`source-pill-${message.id}-${i}`}
                                  key={i}
                                  onClick={() => handleOpenInspector(message.searchResults || [])}
                                  className="text-[10px] font-semibold border border-slate-800 bg-[#15171F] text-slate-300 hover:bg-[#1C1F26] px-2 py-1 rounded-full flex items-center gap-1 transition-colors cursor-pointer"
                                >
                                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
                                  <span className="truncate max-w-44 font-medium">{info.title}</span>
                                </button>
                              );
                            })}
                            {message.searchResults.length > 3 && (
                              <button
                                id={`source-pill-more-${message.id}`}
                                onClick={() => handleOpenInspector(message.searchResults || [])}
                                className="text-[10px] font-bold text-slate-400 hover:text-white bg-[#1C1F26] px-2.5 py-1 rounded-full border border-slate-800 transition-colors cursor-pointer"
                              >
                                +{message.searchResults.length - 3} more
                              </button>
                            )}
                          </div>
                          {message.optimizedQuery && (
                            <div className="text-[10px] text-slate-400 font-mono flex items-center gap-1.5 mt-0.5 bg-slate-900/30 border border-slate-800/40 p-1.5 rounded-lg w-fit">
                              <span className="text-cyan-400 font-bold">🔍 Translated & optimized search:</span>
                              <span className="italic text-slate-300">"{message.optimizedQuery}"</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}

              {/* Suggestions Cards (only displayed on empty thread) */}
              {activeSession && activeSession.messages.length <= 1 && (
                <div className="max-w-2xl mx-auto py-8">
                  <div className="text-center space-y-2 mb-8">
                    <div className="inline-flex p-2 bg-cyan-950/50 border border-cyan-800/30 rounded-xl text-cyan-400 mb-2 shadow-[0_0_15px_rgba(6,182,212,0.15)]">
                      <Sparkles size={24} />
                    </div>
                    <h3 className="text-lg font-bold text-white tracking-tight">Revit API Search Templates</h3>
                    <p className="text-xs text-slate-400 max-w-md mx-auto">
                      Click any of the template cards below to auto-formulate research prompts with semantic code searches.
                    </p>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                    {SUGGESTED_PROMPTS.map((item, index) => {
                      const IconComponent = item.icon;
                      return (
                        <button
                          id={`suggested-prompt-${index}`}
                          key={index}
                          onClick={() => handleSendMessage(item.prompt)}
                          className="p-4 border border-slate-800 hover:border-cyan-500/50 rounded-xl bg-[#15171F] hover:bg-[#1C1F26] text-left transition-all group cursor-pointer hover:shadow-[0_0_20px_rgba(6,182,212,0.08)]"
                        >
                          <div className="flex items-center justify-between mb-2">
                            <div className="p-1.5 bg-[#0D0E12] rounded text-slate-400 group-hover:bg-cyan-500 group-hover:text-black transition-colors">
                              <IconComponent size={16} />
                            </div>
                            <span className="text-[9px] font-bold text-slate-500 font-mono uppercase bg-[#0D0E12] p-1 rounded border border-slate-800/80">
                              {item.category}
                            </span>
                          </div>
                          <h4 className="text-xs font-bold text-white mb-1 leading-snug">
                            {item.title}
                          </h4>
                          <p className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed">
                            {item.prompt}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Loading indicator */}
              {loading && (
                <div className="flex gap-4 max-w-3xl mr-auto">
                  <div className="w-8 h-8 rounded-lg bg-cyan-500 text-black flex items-center justify-center shrink-0">
                    <Terminal size={15} />
                  </div>
                  <div className="bg-[#15171F] p-4 border border-slate-800 rounded-xl rounded-tl-none shadow-sm w-full">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-bold text-cyan-400 font-mono uppercase">Retrieving and Generating</span>
                      <span className="flex gap-1">
                        <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-bounce delay-0" />
                        <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-bounce delay-150" />
                        <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-bounce delay-300" />
                      </span>
                    </div>
                    <div className="space-y-2.5 mt-3 animate-pulse">
                      <div className="h-3 bg-slate-800 rounded w-5/6" />
                      <div className="h-3 bg-slate-800 rounded w-11/12" />
                      <div className="h-3 bg-slate-800 rounded w-2/3" />
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input Form */}
            <div className="p-4 border-t border-slate-800 bg-[#0A0B10] sticky bottom-0 z-20">
              <div className="max-w-3xl mx-auto">
                <form
                  id="chat-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleSendMessage(input);
                  }}
                  className="relative bg-[#15171F] border border-slate-800 rounded-xl overflow-hidden focus-within:ring-1 focus-within:ring-cyan-500/30 focus-within:border-cyan-500 transition-all shadow-sm"
                >
                  <textarea
                    id="chat-input"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleSendMessage(input);
                      }
                    }}
                    placeholder="Ask about Revit API (e.g. Transactions, Collectors, SDK Samples)..."
                    rows={2}
                    className="w-full bg-transparent px-4 py-3 pb-12 text-sm text-slate-200 placeholder-slate-500 focus:outline-none resize-none"
                    disabled={loading}
                  />
                  
                  {/* Footer controls inside input block */}
                  <div className="absolute bottom-2 left-3 right-3 flex items-center justify-between pointer-events-none">
                    <span className="text-[10px] text-slate-500 font-mono">
                      Shift+Enter for newline
                    </span>
                    <button
                      id="btn-send-message"
                      type="submit"
                      disabled={loading || !input.trim()}
                      className="p-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:bg-slate-800 disabled:text-slate-600 text-black font-semibold rounded-lg transition-colors pointer-events-auto cursor-pointer flex items-center gap-1.5"
                    >
                      <span className="text-xs font-bold px-1.5 hidden sm:inline">Send</span>
                      <Send size={13} />
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Direct Search Database Browser */}
        {activeTab === "search" && (
          <div className="flex-1 flex flex-col min-h-0 bg-[#0A0B10]">
            {/* Search Input Bar */}
            <div className="p-6 bg-[#15171F] border-b border-slate-800">
              <div className="max-w-3xl mx-auto">
                <form id="direct-search-form" onSubmit={handleDirectSearch} className="flex gap-2.5">
                  <div className="relative flex-1">
                    <input
                      id="direct-search-input"
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search code samples and API documentation across vector collections..."
                      className="w-full bg-[#0D0E12] border border-slate-800 rounded-xl pl-10 pr-4 py-3 text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 text-slate-200 placeholder-slate-500"
                    />
                    <Search className="absolute left-3.5 top-3.5 text-slate-500" size={16} />
                  </div>
                  <button
                    id="btn-direct-search"
                    type="submit"
                    disabled={searchLoading || !searchQuery.trim()}
                    className="px-5 bg-cyan-500 hover:bg-cyan-400 text-black text-sm font-semibold rounded-xl flex items-center gap-2 transition-colors cursor-pointer"
                  >
                    <span>Search</span>
                    <ArrowRight size={15} />
                  </button>
                </form>
                <div className="flex flex-wrap gap-2 mt-3.5 items-center">
                  <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mr-1">Searching inside:</span>
                  {selectedCollections.map((col) => (
                    <span key={col} className={`text-[10px] font-semibold border px-2 py-0.5 rounded-full ${getCollectionBadgeStyles(col)}`}>
                      {getCollectionFriendlyName(col)}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Search Results Display Grid */}
            <div className="flex-1 overflow-y-auto p-4 md:p-8">
              <div className="max-w-4xl mx-auto">
                {searchLoading ? (
                  <div className="space-y-4">
                    <div className="h-4 bg-slate-800 rounded animate-pulse w-1/4 mb-6" />
                    {[1, 2, 3].map((n) => (
                      <div key={n} className="p-5 border border-slate-800 bg-[#15171F] rounded-xl space-y-3 animate-pulse">
                        <div className="flex justify-between">
                          <div className="h-4 bg-slate-800 rounded w-1/3" />
                          <div className="h-4 bg-slate-800 rounded w-12" />
                        </div>
                        <div className="h-3 bg-slate-800 rounded w-5/6" />
                        <div className="h-3 bg-slate-800 rounded w-1/2" />
                      </div>
                    ))}
                  </div>
                ) : searchResultsDirect.length > 0 ? (
                  <div className="space-y-4">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/60 pb-3 mb-2">
                      <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                        Semantically Ranked Matches ({searchResultsDirect.length} results)
                      </h3>
                      {optimizedQuery && optimizedQuery.toLowerCase() !== searchQuery.trim().toLowerCase() && (
                        <div className="text-[11px] font-mono text-cyan-400 bg-cyan-950/40 border border-cyan-800/30 px-2 py-1 rounded flex items-center gap-1.5 self-start sm:self-auto">
                          <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-ping shrink-0" />
                          <span>Translated & optimized: "{optimizedQuery}"</span>
                        </div>
                      )}
                    </div>
                    <div className="grid grid-cols-1 gap-4">
                      {searchResultsDirect.map((res, index) => {
                        const fields = extractDocumentFields(res.payload);
                        return (
                          <div key={index} className="border border-slate-800 bg-[#15171F] hover:border-cyan-500/30 hover:bg-[#1C1F26]/85 rounded-xl p-5 shadow-sm transition-all">
                            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-mono font-bold bg-[#0D0E12] text-slate-400 px-2 py-0.5 rounded border border-slate-800">
                                  #{index + 1}
                                </span>
                                <span className={`text-[10px] font-semibold border px-2 py-0.5 rounded ${getCollectionBadgeStyles(res.collection)}`}>
                                  {getCollectionFriendlyName(res.collection)}
                                </span>
                              </div>
                              <span className="text-xs font-bold text-cyan-400 bg-cyan-950/40 border border-cyan-900/40 px-2.5 py-0.5 rounded-full font-mono">
                                Match: {((res.score) * 100).toFixed(1)}%
                              </span>
                            </div>

                            <h4 className="text-sm font-bold text-white mb-2 leading-snug">
                              {fields.title}
                            </h4>

                            {fields.source && (
                              <p className="text-[10px] text-slate-400 font-mono mb-3 truncate bg-[#0D0E12] p-1 px-2 border border-slate-850 rounded inline-block">
                                {fields.source}
                              </p>
                            )}

                            {fields.content && (
                              <p className="text-xs text-slate-300 leading-relaxed line-clamp-3 mb-4 whitespace-pre-wrap">
                                {fields.content}
                              </p>
                            )}

                            {fields.code && (
                              <div className="mb-4">
                                <pre className="bg-[#0D0E12] p-3.5 rounded-lg overflow-x-auto text-[11px] font-mono text-slate-200 border border-slate-800/80 max-h-48">
                                  <code>{fields.code}</code>
                                </pre>
                              </div>
                            )}

                            <div className="flex justify-end">
                              <button
                                id={`inspect-btn-${index}`}
                                onClick={() => {
                                  // Open in our side-inspector
                                  setInspectorResults(searchResultsDirect);
                                  setInspectorOpen(true);
                                }}
                                className="text-xs text-slate-300 hover:text-white border border-slate-700 hover:border-slate-500 rounded-lg px-3 py-1.5 font-semibold bg-[#1C1F26] flex items-center gap-1.5 transition-all cursor-pointer"
                              >
                                <Maximize2 size={12} />
                                <span>Inspect Full Document</span>
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-16 border border-dashed border-slate-800 rounded-xl bg-[#15171F] max-w-xl mx-auto mt-8">
                    <Database size={32} className="mx-auto text-slate-600 mb-2" />
                    <h3 className="text-sm font-bold text-slate-400">No active searches yet</h3>
                    <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1">
                      Type your semantic Revit API / C# query in the search bar above to fetch direct references.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Search Results Detail Slider (RAG Inspector Drawer) */}
        <SearchResultViewer
          results={inspectorResults}
          onClose={() => setInspectorOpen(false)}
          isOpen={inspectorOpen}
        />

        {/* Dynamic Settings Modal */}
        {settingsOpen && (
          <div className="fixed inset-0 bg-[#06070a]/85 backdrop-blur-md flex items-center justify-center p-4 z-50">
            <div className="bg-[#15171F] border border-slate-800 rounded-2xl w-full max-w-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
              {/* Header */}
              <div className="p-6 border-b border-slate-800 flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <Sliders className="text-cyan-400 w-5 h-5" />
                  <div>
                    <h3 className="text-sm font-bold text-white">Параметры системы</h3>
                    <p className="text-[11px] text-slate-400 font-medium">Конфигурация нейросети, локальной Ollama и подключения к Qdrant</p>
                  </div>
                </div>
                <button 
                  onClick={() => setSettingsOpen(false)}
                  className="p-1 rounded-lg hover:bg-[#1C1F26] text-slate-400 hover:text-white transition-colors cursor-pointer text-sm"
                >
                  ✕
                </button>
              </div>

              {/* Body */}
              <div className="p-6 overflow-y-auto space-y-6 flex-1 text-slate-200">
                {/* Local Ollama Toggle */}
                <div className="p-4 rounded-xl border border-slate-800 bg-[#0E1015] flex items-center justify-between">
                  <div className="space-y-1 pr-4">
                    <label className="text-xs font-bold text-white flex items-center gap-1.5 uppercase tracking-wide">
                      <Cpu size={14} className="text-cyan-400 animate-pulse" />
                      <span>Использовать локальную Ollama</span>
                    </label>
                    <p className="text-[11px] text-slate-400 leading-relaxed font-medium">
                      Включите, чтобы делать запросы к вашей локальной Ollama (на localhost) без ключа RouterAI.
                    </p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input 
                      type="checkbox" 
                      checked={settings.useOllama}
                      onChange={(e) => setSettings({ ...settings, useOllama: e.target.checked })}
                      className="sr-only peer"
                    />
                    <div className="w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-500 peer-checked:after:bg-cyan-400 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-cyan-950 border border-slate-700"></div>
                  </label>
                </div>

                {/* Grid Inputs */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* API Key (Conditional) */}
                  {!settings.useOllama && (
                    <div className="space-y-1.5 col-span-1 md:col-span-2">
                      <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                        RouterAI API Key
                      </label>
                      <input 
                        type="password"
                        value={settings.routeraiKey}
                        onChange={(e) => setSettings({ ...settings, routeraiKey: e.target.value })}
                        placeholder="Введите ваш ROUTERAI_API_KEY..."
                        className="w-full px-3 py-2 bg-[#0D0E12] border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-650 focus:outline-none focus:border-cyan-500/40 transition-colors font-mono"
                      />
                      <p className="text-[9px] text-slate-500 font-medium">
                        Используется для удаленного перефразирования вопросов и формирования ответов.
                      </p>
                    </div>
                  )}

                  {/* API Base URL */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                      {settings.useOllama ? "Ollama Base URL" : "RouterAI Base URL"}
                    </label>
                    <input 
                      type="text"
                      value={settings.routeraiBaseUrl}
                      onChange={(e) => setSettings({ ...settings, routeraiBaseUrl: e.target.value })}
                      placeholder={settings.useOllama ? "http://localhost:11434" : "https://routerai.ru/api/v1"}
                      className="w-full px-3 py-2 bg-[#0D0E12] border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-650 focus:outline-none focus:border-cyan-500/40 transition-colors font-mono"
                    />
                  </div>

                  {/* Qdrant URL */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                      Qdrant URL
                    </label>
                    <input 
                      type="text"
                      value={settings.qdrantUrl}
                      onChange={(e) => setSettings({ ...settings, qdrantUrl: e.target.value })}
                      placeholder="http://d9e0f9d73f7a.vps.myjino.ru:6333"
                      className="w-full px-3 py-2 bg-[#0D0E12] border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-650 focus:outline-none focus:border-cyan-500/40 transition-colors font-mono"
                    />
                  </div>

                  {/* LLM Model */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                      Модель Чата (LLM Model)
                    </label>
                    <input 
                      type="text"
                      value={settings.llmModel}
                      onChange={(e) => setSettings({ ...settings, llmModel: e.target.value })}
                      placeholder={settings.useOllama ? "llama3" : "deepseek/deepseek-v4-flash"}
                      className="w-full px-3 py-2 bg-[#0D0E12] border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-650 focus:outline-none focus:border-cyan-500/40 transition-colors font-mono"
                    />
                  </div>

                  {/* Embedding Model */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                      Модель Векторизации (Embedding)
                    </label>
                    <input 
                      type="text"
                      value={settings.embeddingModel}
                      onChange={(e) => setSettings({ ...settings, embeddingModel: e.target.value })}
                      placeholder={settings.useOllama ? "nomic-embed-text" : "baai/bge-m3"}
                      className="w-full px-3 py-2 bg-[#0D0E12] border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-650 focus:outline-none focus:border-cyan-500/40 transition-colors font-mono"
                    />
                  </div>
                </div>

                {settings.useOllama && (
                  <div className="p-4 bg-cyan-950/20 border border-cyan-900/30 rounded-xl text-[11px] text-cyan-400 leading-relaxed font-medium">
                    <p className="font-bold mb-1 uppercase tracking-wide text-xs">💡 Локальные требования Ollama:</p>
                    <ul className="list-disc pl-4 space-y-1 text-slate-300">
                      <li>Ollama должна работать на хосте (по умолчанию: <code className="text-cyan-400 bg-black/40 px-1 rounded">http://localhost:11434</code>).</li>
                      <li>Загрузите модели: <code className="text-cyan-400 bg-black/40 px-1 rounded">ollama pull llama3</code> (или другую) и <code className="text-cyan-400 bg-black/40 px-1 rounded">ollama pull nomic-embed-text</code>.</li>
                      <li>Запустите Ollama с переменной <code className="text-cyan-400 bg-black/40 px-1 rounded">OLLAMA_ORIGINS="*"</code> для поддержки CORS.</li>
                    </ul>
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="p-4.5 border-t border-slate-800 flex items-center justify-between bg-[#0E1015]">
                <button
                  onClick={handleResetSettings}
                  className="px-3.5 py-1.5 border border-slate-800 hover:border-slate-700 hover:bg-[#1C1F26] text-slate-450 hover:text-white rounded-lg text-xs font-bold transition-colors cursor-pointer"
                >
                  Сбросить настройки
                </button>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setSettingsOpen(false)}
                    className="px-3.5 py-1.5 hover:bg-[#1C1F26] text-slate-400 hover:text-white rounded-lg text-xs font-semibold transition-colors cursor-pointer"
                  >
                    Отмена
                  </button>
                  <button
                    onClick={handleSaveSettings}
                    className="px-4.5 py-1.5 bg-cyan-500 hover:bg-cyan-400 text-black rounded-lg text-xs font-bold transition-colors cursor-pointer shadow-md"
                  >
                    Сохранить настройки
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
