import { SearchResult } from "./types";

export function extractDocumentFields(payload: any) {
  if (!payload) return { title: "Untitled", content: "", code: "", source: "" };

  // Prioritize typical Revit API properties
  const title = 
    payload.title || 
    payload.name || 
    payload.class_name || 
    payload.method_name || 
    payload.header || 
    payload.file_name || 
    "Untitled Document";
  
  // Combine potential content fields
  const content = 
    payload.text || 
    payload.body || 
    payload.content || 
    payload.description || 
    payload.context || 
    payload.chunk_text || 
    payload.chunk || 
    "";
  
  // Combine potential code snippet fields
  const code = 
    payload.code || 
    payload.snippet || 
    payload.example || 
    payload.source || 
    "";
  
  // Combine potential source metadata (files, URLs, years)
  const source = 
    payload.url || 
    payload.link || 
    payload.source_file || 
    payload.path || 
    payload.file || 
    (payload.year ? `Year: ${payload.year}` : "") ||
    "";
  
  return { title, content, code, source };
}

export function formatScore(score: number): string {
  return `${(score * 100).toFixed(1)}%`;
}

export function getCollectionBadgeStyles(collection: string) {
  if (collection.startsWith("sql_revit_")) {
    return "bg-blue-500/15 text-blue-300 border-blue-500/30";
  }
  switch (collection) {
    case "revit_api_knowledge":
      return "bg-cyan-500/10 text-cyan-400 border-cyan-500/30";
    case "Revit_SDK_Samples":
      return "bg-purple-500/10 text-purple-400 border-purple-500/30";
    case "navisworks_api_bge":
      return "bg-amber-500/10 text-amber-400 border-amber-500/30";
    case "revit_api_whatsnew":
      return "bg-green-500/10 text-green-400 border-green-500/30";
    default:
      return "bg-slate-500/10 text-slate-400 border-slate-500/30";
  }
}

export function getCollectionFriendlyName(collection: string) {
  if (collection.startsWith("sql_revit_")) {
    const version = collection.replace("sql_revit_", "");
    return `SQL DB Revit ${version}`;
  }
  switch (collection) {
    case "revit_api_knowledge":
      return "Revit API Knowledge";
    case "Revit_SDK_Samples":
      return "Revit SDK Samples";
    case "navisworks_api_bge":
      return "Navisworks API";
    case "revit_api_whatsnew":
      return "Revit What's New";
    default:
      return collection;
  }
}
