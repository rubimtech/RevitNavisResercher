import { MessageSquare, Plus, Trash2, Database, AlertCircle, CheckCircle2, ChevronRight, BookOpen } from "lucide-react";
import { ChatSession, AppConfig } from "../types";

interface SidebarProps {
  sessions: ChatSession[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
  selectedCollections: string[];
  onToggleCollection: (id: string) => void;
  appConfig: AppConfig | null;
  sidebarOpen: boolean;
  onCloseSidebar: () => void;
}

const COLLECTIONS = [
  { 
    id: "revit_api_knowledge", 
    name: "Revit API Docs", 
    desc: "Classes, methods & structures", 
    pts: "4.2k pts", 
    barWidth: "w-2/3", 
    color: "bg-cyan-500", 
    textColor: "text-cyan-400" 
  },
  { 
    id: "Revit_SDK_Samples", 
    name: "SDK Samples", 
    desc: "Code examples & templates", 
    pts: "1.8k pts", 
    barWidth: "w-1/3", 
    color: "bg-purple-500", 
    textColor: "text-purple-400" 
  },
  { 
    id: "navisworks_api_bge", 
    name: "Navisworks API", 
    desc: "Navisworks automation reference", 
    pts: "940 pts", 
    barWidth: "w-1/4", 
    color: "bg-amber-500", 
    textColor: "text-amber-400" 
  },
  { 
    id: "revit_api_whatsnew", 
    name: "What's New", 
    desc: "Breaking changes 2022–2026", 
    pts: "2022-2026", 
    barWidth: "w-1/2", 
    color: "bg-green-500", 
    textColor: "text-green-400" 
  }
];

export default function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  selectedCollections,
  onToggleCollection,
  appConfig,
  sidebarOpen,
  onCloseSidebar
}: SidebarProps) {
  return (
    <aside
      id="sidebar-container"
      className={`fixed inset-y-0 left-0 z-40 w-80 bg-[#15171F] border-r border-slate-800 flex flex-col transition-transform duration-300 ease-in-out md:static md:translate-x-0 md:h-full md:max-h-screen overflow-hidden ${
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      }`}
    >
      {/* Sidebar Header */}
      <div id="sidebar-header" className="p-4 border-b border-slate-800 flex items-center justify-between bg-[#15171F]">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-cyan-500 rounded text-black font-bold text-sm">
            R
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white tracking-tight leading-none">
              Revit <span className="text-cyan-400">Researcher</span>
            </h1>
            <span className="text-[10px] text-slate-400 font-medium">Bento Semantic RAG</span>
          </div>
        </div>
        <button
          id="btn-close-sidebar"
          onClick={onCloseSidebar}
          className="p-1 text-slate-400 hover:text-slate-200 md:hidden"
        >
          <ChevronRight className="rotate-180" size={20} />
        </button>
      </div>

      {/* Action Area: New Chat */}
      <div className="p-4">
        <button
          id="btn-new-chat"
          onClick={onNewSession}
          className="w-full py-2 px-4 bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700 font-medium text-xs rounded-lg flex items-center justify-center gap-2 transition-colors duration-150 shadow-sm cursor-pointer"
        >
          <Plus size={14} />
          <span>New Research Thread</span>
        </button>
      </div>

      {/* Scrollable Middle: Sessions & Collections */}
      <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-6">
        {/* History Area */}
        <div className="space-y-2">
          <h3 className="text-[10px] uppercase tracking-widest text-slate-500 font-bold px-1">
            Research History
          </h3>
          <div className="space-y-1.5">
            {sessions.length === 0 ? (
              <div className="text-center p-6 border border-slate-800 bg-slate-900/20 rounded-lg">
                <p className="text-xs text-slate-500">No active threads.</p>
              </div>
            ) : (
              sessions.map((session) => {
                const isActive = session.id === activeSessionId;
                return (
                  <div
                    key={session.id}
                    className={`group relative flex items-center rounded-lg transition-all duration-150 ${
                      isActive
                        ? "bg-[#1C1F26] border border-slate-700 text-white"
                        : "text-slate-400 hover:bg-slate-800/50"
                    }`}
                  >
                    <button
                      id={`session-select-${session.id}`}
                      onClick={() => onSelectSession(session.id)}
                      className="flex-1 py-2 px-3 text-left min-w-0 flex items-center gap-2"
                    >
                      <MessageSquare
                        size={13}
                        className={isActive ? "text-cyan-400" : "text-slate-500 group-hover:text-slate-300"}
                      />
                      <div className="truncate flex-1">
                        <span className="text-xs font-medium block truncate">
                          {session.title || "Untitled Thread"}
                        </span>
                        <span className="text-[9px] text-slate-500 font-mono block mt-0.5">
                          {new Date(session.createdAt).toLocaleDateString()}
                        </span>
                      </div>
                    </button>
                    <button
                      id={`session-delete-${session.id}`}
                      onClick={() => onDeleteSession(session.id)}
                      className="p-1.5 mr-1 text-slate-500 hover:text-rose-400 hover:bg-rose-950/20 rounded opacity-0 group-hover:opacity-100 focus:opacity-100 transition-all duration-150 cursor-pointer"
                      title="Delete thread"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Knowledge Collections Filter */}
        <div className="space-y-2">
          <div className="flex items-center justify-between px-1">
            <h3 className="text-[10px] uppercase tracking-widest text-slate-500 font-bold flex items-center gap-1.5">
              <Database size={11} />
              <span>Active Collections</span>
            </h3>
            <span className="text-[9px] bg-slate-800 border border-slate-700 text-slate-400 px-1.5 py-0.5 rounded font-mono">
              Qdrant DB
            </span>
          </div>
          <div className="grid grid-cols-1 gap-2">
            {COLLECTIONS.map((col) => {
              const isChecked = selectedCollections.includes(col.id);
              const serverCol = appConfig?.collections?.find(c => c.id === col.id);
              const displayPts = serverCol && typeof serverCol.pointsCount === "number"
                ? `${serverCol.pointsCount.toLocaleString()} pts`
                : col.pts;

              return (
                <button
                  id={`collection-${col.id}`}
                  key={col.id}
                  onClick={() => onToggleCollection(col.id)}
                  className={`w-full p-2.5 text-left rounded-lg border transition-all duration-150 cursor-pointer ${
                    isChecked
                      ? "border-slate-700 bg-[#1C1F26] shadow-sm"
                      : "border-slate-800/40 bg-slate-900/40 hover:bg-[#1C1F26]/50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-1.5">
                    <span className={`text-xs font-semibold ${isChecked ? col.textColor : "text-slate-400"}`}>
                      {col.name}
                    </span>
                    <span className="text-[10px] text-slate-500 font-mono">
                      {displayPts}
                    </span>
                  </div>
                  
                  {/* Progress bar visual for Bento style */}
                  <div className="w-full bg-slate-800 h-1 rounded-full mt-2 overflow-hidden">
                    <div className={`h-1 rounded-full transition-all duration-300 ${col.color} ${isChecked ? col.barWidth : "w-0"}`} />
                  </div>

                  <p className="text-[10px] text-slate-500 mt-1.5 leading-normal line-clamp-1">
                    {col.desc}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Sidebar Footer - API Key Info */}
      <div id="sidebar-footer" className="p-3 border-t border-slate-800 bg-[#15171F]">
        <div className="p-2.5 bg-[#0D0E12] border border-slate-800 rounded-lg flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            {appConfig?.hasApiKey ? (
              <CheckCircle2 className="text-emerald-400 shrink-0" size={14} />
            ) : (
              <AlertCircle className="text-amber-400 shrink-0" size={14} />
            )}
            <div className="min-w-0">
              <span className="text-[10px] font-semibold text-slate-300 block truncate">
                RouterAI Status
              </span>
              <span className="text-[9px] text-slate-500 font-mono block truncate">
                {appConfig?.hasApiKey ? "Connected: bge-m3" : "Missing API Key"}
              </span>
            </div>
          </div>
          {!appConfig?.hasApiKey && (
            <div className="text-[9px] text-amber-400 font-medium px-1.5 py-0.5 bg-amber-950/30 border border-amber-900/50 rounded shrink-0">
              Setup Key
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
