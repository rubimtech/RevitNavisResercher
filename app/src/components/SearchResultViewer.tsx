import { useState } from "react";
import { SearchResult } from "../types";
import { extractDocumentFields, formatScore, getCollectionBadgeStyles, getCollectionFriendlyName } from "../utils";
import { X, Copy, Check, Code2, FileText, Sparkles, AlertCircle, Database } from "lucide-react";

interface SearchResultViewerProps {
  results: SearchResult[];
  onClose: () => void;
  isOpen: boolean;
}

export default function SearchResultViewer({
  results,
  onClose,
  isOpen
}: SearchResultViewerProps) {
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [copied, setCopied] = useState<boolean>(false);

  if (!isOpen) return null;

  const activeResult = results[selectedIndex] || results[0];
  const fields = activeResult ? extractDocumentFields(activeResult.payload) : null;

  const sqlCount = results.filter(r => r.collection?.startsWith("sql_revit_")).length;
  const qdrantCount = results.length - sqlCount;

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      id="search-results-panel"
      className="fixed inset-y-0 right-0 z-50 w-full sm:w-120 md:w-144 bg-[#15171F] border-l border-slate-800 shadow-2xl flex flex-col transition-all duration-300 ease-in-out"
    >
      {/* Panel Header */}
      <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-[#1C1F26]">
        <div className="flex items-center gap-2">
          <Sparkles className="text-cyan-400 animate-pulse" size={18} />
          <div>
            <h2 className="text-sm font-semibold text-white leading-none">RAG Retrieval Inspector</h2>
            <span className="text-[11px] text-slate-400 font-medium">
              Found {results.length} matches ({sqlCount} SQL DB via API, {qdrantCount} Qdrant)
            </span>
          </div>
        </div>
        <button
          id="close-results-panel"
          onClick={onClose}
          className="p-1.5 hover:bg-slate-800 text-slate-400 hover:text-slate-100 rounded-lg transition-colors cursor-pointer"
        >
          <X size={18} />
        </button>
      </div>

      {/* Main Split Layout */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        {/* Left column / Top row: List of Matches */}
        <div className="w-full md:w-56 border-b md:border-b-0 md:border-r border-slate-800 flex flex-col min-h-0 bg-[#0F1016]">
          <div className="p-2 bg-[#15171F] border-b border-slate-800 text-[10px] font-bold text-slate-400 uppercase tracking-wider px-3">
            Ranked Matches
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
            {results.map((res, index) => {
              const info = extractDocumentFields(res.payload);
              const isSelected = index === selectedIndex;
              return (
                <button
                  id={`match-btn-${index}`}
                  key={index}
                  onClick={() => {
                    setSelectedIndex(index);
                    setCopied(false);
                  }}
                  className={`w-full p-2.5 rounded-lg border text-left transition-all duration-150 cursor-pointer ${
                    isSelected
                      ? "border-cyan-500 bg-[#1C1F26] shadow-sm ring-1 ring-cyan-500/30"
                      : "border-slate-800 bg-[#15171F]/60 hover:bg-[#1C1F26]/70 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center justify-between gap-1 mb-1">
                    <span className="text-[9px] font-mono font-bold text-slate-400 bg-slate-800/80 px-1 rounded">
                      #{index + 1}
                    </span>
                    <span className="text-[10px] font-bold text-cyan-400 bg-cyan-950/40 border border-cyan-800/30 px-1 py-0.5 rounded font-mono">
                      {formatScore(res.score)}
                    </span>
                  </div>
                  <h4 className="text-xs font-semibold text-slate-200 line-clamp-1">
                    {info.title}
                  </h4>
                  <span className={`inline-block text-[9px] font-semibold border px-1 py-0.5 rounded mt-1.5 ${getCollectionBadgeStyles(res.collection)}`}>
                    {getCollectionFriendlyName(res.collection)}
                  </span>
                  {res.collection?.startsWith("sql_revit_") && (
                    <span className="ml-1 inline-flex items-center gap-0.5 text-[8px] font-bold text-emerald-400 bg-emerald-950/20 border border-emerald-800/20 px-1 py-0.5 rounded uppercase">
                      Live API
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Right column: Document Details */}
        <div className="flex-1 flex flex-col min-h-0 overflow-y-auto bg-[#15171F] p-4">
          {activeResult && fields ? (
            <div className="space-y-4">
              {/* Header Details */}
              <div className="space-y-1">
                <div className="flex flex-wrap gap-1.5 items-center">
                  <span className={`text-[10px] font-semibold border px-1.5 py-0.5 rounded ${getCollectionBadgeStyles(activeResult.collection)}`}>
                    {getCollectionFriendlyName(activeResult.collection)}
                  </span>
                  {activeResult.collection?.startsWith("sql_revit_") && (
                    <span className="text-[10px] font-semibold text-emerald-400 bg-emerald-950/40 border border-emerald-900/40 px-1.5 py-0.5 rounded flex items-center gap-1">
                      <Database size={11} />
                      Live SQL Tree API Node
                    </span>
                  )}
                  <span className="text-[10px] font-bold text-cyan-400 bg-cyan-950/40 border border-cyan-900/40 px-1.5 py-0.5 rounded font-mono">
                    Match Score: {formatScore(activeResult.score)}
                  </span>
                </div>
                <h3 className="text-base font-bold text-white tracking-tight mt-1">
                  {fields.title}
                </h3>
                {fields.source && (
                  <div className="flex items-center gap-1 text-[10px] text-slate-400 font-mono break-all bg-[#0D0E12] p-1.5 rounded border border-slate-800/60">
                    <FileText size={11} className="shrink-0 text-slate-500" />
                    <span>{fields.source}</span>
                  </div>
                )}
              </div>

              {/* Text Description/Content */}
              {fields.content && (
                <div className="space-y-1.5">
                  <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                    <span>Document Context</span>
                  </h4>
                  <div className="text-xs text-slate-300 bg-[#1C1F26]/50 p-3 rounded-lg border border-slate-800/80 leading-relaxed font-sans whitespace-pre-wrap">
                    {fields.content}
                  </div>
                </div>
              )}

              {/* Code Snippet Box */}
              {fields.code && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                      <Code2 size={12} className="text-slate-400" />
                      <span>Retrieved C# / .NET Code</span>
                    </h4>
                    <button
                      id="copy-snippet-code"
                      onClick={() => handleCopyCode(fields.code)}
                      className="text-[10px] text-slate-300 hover:text-white flex items-center gap-1.5 p-1 px-2 border border-slate-700 hover:border-slate-500 rounded bg-[#1C1F26] transition-colors cursor-pointer"
                    >
                      {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
                      <span>{copied ? "Copied!" : "Copy Code"}</span>
                    </button>
                  </div>
                  <div className="relative rounded-lg overflow-hidden border border-slate-800 shadow-sm">
                    <div className="bg-[#1C1F26] text-slate-400 px-3 py-1.5 text-[10px] font-mono border-b border-slate-800 flex items-center justify-between">
                      <span>C# Snippet</span>
                      <span className="text-slate-600">Revit SDK syntax</span>
                    </div>
                    <pre className="bg-[#0D0E12] p-4 overflow-x-auto text-[11px] font-mono text-slate-200 max-h-96">
                      <code>{fields.code}</code>
                    </pre>
                  </div>
                </div>
              )}

              {/* Raw JSON Debug Details */}
              <div className="pt-2 border-t border-slate-800">
                <details className="group">
                  <summary className="text-[10px] font-semibold text-slate-500 hover:text-slate-400 cursor-pointer list-none flex items-center gap-1">
                    <span className="transition-transform group-open:rotate-90 text-[8px]">▶</span>
                    <span>View Raw Payload Fields</span>
                  </summary>
                  <pre className="bg-[#0D0E12] p-3 rounded border border-slate-800 text-[10px] font-mono text-slate-400 overflow-x-auto mt-2 max-h-48">
                    {JSON.stringify(activeResult.payload, null, 2)}
                  </pre>
                </details>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-slate-500">
              <AlertCircle size={24} className="mb-2" />
              <p className="text-xs">Select a result to inspect its details.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
