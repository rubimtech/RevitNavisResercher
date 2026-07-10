import express from "express";
import path from "path";
import dotenv from "dotenv";
import { createServer as createViteServer } from "vite";
import dns from "dns";
import { URL } from "url";
import initSqlJs from "sql.js";
import fs from "fs";

// Load environment variables
dotenv.config();

// ── Local SQLite DB (Revit API data via sql.js) ──────────────────────────
const DB_PATH = path.resolve(process.cwd(), "..", "revit_api.db");
let sqlDb: any = null;
let SQL: any = null;

async function initSqlite() {
  try {
    SQL = await initSqlJs();
    const buffer = fs.readFileSync(DB_PATH);
    sqlDb = new SQL.Database(buffer);
    console.log(`Local SQLite DB opened: ${DB_PATH}`);
  } catch (err: any) {
    console.warn(`Could not open local SQLite DB at ${DB_PATH}: ${err.message}`);
  }
}

// Global dns.lookup override to fix DNS resolution issues in sandboxed Cloud Run environments
// Only targets myjino.ru (Qdrant/Tree API host), NOT routerai.ru (which resolves fine natively)
// Tries original (system) resolver first; public DNS is only a fallback.
const originalLookup = dns.lookup;
// @ts-ignore
dns.lookup = function (hostname: string, options: any, callback: any) {
  if (typeof options === "function") {
    callback = options;
    options = {};
  }

  const opts = typeof options === "number" ? { family: options } : (options || {});
  if (hostname.endsWith("myjino.ru")) {
    // Try original lookup first (fast path on systems with working DNS)
    originalLookup(hostname, opts, (err, address, family) => {
      if (err) {
        // Fallback to public DNS resolvers
        const resolver = new dns.Resolver();
        resolver.setServers(["1.1.1.1", "8.8.8.8"]);
        resolver.resolve4(hostname, (err2, addresses) => {
          if (err2 || !addresses || addresses.length === 0) {
            callback(err, address, family);
          } else {
            if (opts.all) {
              callback(null, addresses.map(addr => ({ address: addr, family: 4 })));
            } else {
              callback(null, addresses[0], 4);
            }
          }
        });
      } else {
        if (opts.all && typeof address === "string") {
          callback(null, [{ address, family }]);
        } else {
          callback(null, address, family);
        }
      }
    });
  } else {
    originalLookup(hostname, options, callback);
  }
};

const app = express();
const PORT = 3000;

app.use(express.json());

// Helper to resolve Qdrant URL using public DNS if local resolver fails or returns EAI_AGAIN
async function resolveQdrantUrl(rawUrl: string): Promise<string> {
  try {
    const parsed = new URL(rawUrl);
    const hostname = parsed.hostname;
    
    // If it is already an IP address, return early
    if (/^[0-9.]+$/.test(hostname)) {
      return rawUrl;
    }
    
    let resolvedIp = hostname;
    try {
      const resolver = new dns.promises.Resolver();
      resolver.setServers(["1.1.1.1", "8.8.8.8"]);
      const ips = await resolver.resolve4(hostname);
      if (ips && ips.length > 0) {
        resolvedIp = ips[0];
      }
    } catch (dnsErr: any) {
      console.warn(`Public DNS resolution failed for hostname ${hostname}: ${dnsErr.message}`);
      // Fallback if public DNS also fails or times out
      if (hostname === "d9e0f9d73f7a.vps.myjino.ru") {
        resolvedIp = "5.42.104.164";
      }
    }
    
    parsed.hostname = resolvedIp;
    return parsed.toString().replace(/\/$/, "");
  } catch (err: any) {
    console.error("Failed to parse/resolve Qdrant URL, returning raw:", err.message);
    return rawUrl;
  }
}

interface ActiveConfig {
  routeraiKey: string;
  routeraiBaseUrl: string;
  qdrantUrl: string;
  llmModel: string;
  embeddingModel: string;
  useOllama: boolean;
}

function getRequestConfig(req: express.Request): ActiveConfig {
  const routeraiKey = (req.headers["x-routerai-key"] as string) || process.env.ROUTERAI_API_KEY || "";
  const routeraiBaseUrl = (req.headers["x-routerai-base-url"] as string) || process.env.ROUTERAI_BASE_URL || "https://routerai.ru/api/v1";
  const qdrantUrl = (req.headers["x-qdrant-url"] as string) || process.env.QDRANT_URL || "http://d9e0f9d73f7a.vps.myjino.ru:6333";
  const llmModel = (req.headers["x-llm-model"] as string) || process.env.LLM_MODEL || "deepseek/deepseek-v4-flash";
  const embeddingModel = (req.headers["x-embedding-model"] as string) || process.env.EMBEDDING_MODEL || "baai/bge-m3";
  const useOllama = (req.headers["x-use-ollama"] as string) === "true";

  return {
    routeraiKey,
    routeraiBaseUrl,
    qdrantUrl,
    llmModel,
    embeddingModel,
    useOllama
  };
}

async function getOllamaEmbedding(baseUrl: string, model: string, input: string): Promise<number[]> {
  const cleanedUrl = baseUrl.replace(/\/v1$/, "").replace(/\/$/, "");
  
  // Try /api/embeddings first
  try {
    const resp = await fetch(`${cleanedUrl}/api/embeddings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, prompt: input }),
    });
    if (resp.ok) {
      const data = await resp.json();
      if (data.embedding && Array.isArray(data.embedding)) {
        return data.embedding;
      }
    }
  } catch (err: any) {
    console.warn("Ollama /api/embeddings failed, trying /api/embed...", err.message);
  }

  // Try /api/embed next
  try {
    const resp = await fetch(`${cleanedUrl}/api/embed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, input }),
    });
    if (resp.ok) {
      const data = await resp.json();
      if (data.embeddings && Array.isArray(data.embeddings) && data.embeddings[0]) {
        return data.embeddings[0];
      }
    }
  } catch (err: any) {
    console.error("Ollama /api/embed also failed:", err.message);
  }

  throw new Error(`Failed to generate embeddings using Ollama model ${model} at ${cleanedUrl}`);
}

async function callLlmChat(config: ActiveConfig, systemPrompt: string, recentMessages: any[]): Promise<string> {
  const msgs = [
    { role: "system", content: systemPrompt },
    ...recentMessages
  ];

  if (config.useOllama) {
    const cleanedUrl = config.routeraiBaseUrl.replace(/\/$/, "");
    const model = config.llmModel === "deepseek/deepseek-v4-flash" ? "llama3" : config.llmModel;
    
    const urlsToTry = [
      `${cleanedUrl}/v1/chat/completions`,
      `${cleanedUrl}/chat/completions`,
      `${cleanedUrl}/api/chat`
    ];

    for (const url of urlsToTry) {
      try {
        const isNativeApi = url.endsWith("/api/chat");
        const body = isNativeApi 
          ? { model, messages: msgs, stream: false }
          : { model, messages: msgs, temperature: 0.3 };

        const resp = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (resp.ok) {
          const data = await resp.json();
          if (isNativeApi) {
            if (data.message && data.message.content) {
              return data.message.content;
            }
          } else {
            if (data.choices?.[0]?.message?.content) {
              return data.choices[0].message.content;
            }
          }
        }
      } catch (err: any) {
        console.warn(`Ollama call failed on ${url}:`, err.message);
      }
    }
    throw new Error(`Failed to call Ollama model ${model} at ${cleanedUrl}`);
  } else {
    if (!config.routeraiKey) {
      throw new Error("ROUTERAI_API_KEY is not defined. Please configure it in Settings.");
    }
    const resp = await fetch(`${config.routeraiBaseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${config.routeraiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: config.llmModel,
        messages: msgs,
        temperature: 0.3,
        max_tokens: 4096,
      }),
      signal: AbortSignal.timeout(30000),
    });

    if (!resp.ok) {
      const errorText = await resp.text();
      throw new Error(`RouterAI chat completion failed: ${resp.statusText} - ${errorText}`);
    }

    const data = await resp.json();
    return data.choices?.[0]?.message?.content || "No response received from model.";
  }
}

// Translate non-English queries to English and reformulate for optimal semantic vector search
async function translateAndReformulateQuery(userQuery: string, config: ActiveConfig): Promise<string> {
  const systemPrompt = `You are a professional software engineer translator and search query optimizer specializing in Autodesk Revit API, C#, .NET, Navisworks API, and BIM development.
Your ONLY task is to translate any user query into English (if it is not already in English) and reformulate/optimize it to be a perfect semantic search query for a vector database containing Revit/Navisworks C# API documentation and SDK samples.

Rules:
1. Translate non-English queries (e.g. Russian, Spanish) into English.
2. Identify core Revit/Navisworks classes, methods, or namespaces if mentioned (e.g. "коллектор" -> "FilteredElementCollector", "транзакция" -> "Transaction", "выбрать элементы" -> "Selection", "поиск стен" -> "FilteredElementCollector of class Wall").
3. Make the query precise, technical, and developer-oriented in English.
4. Output ONLY the translated, optimized search query. Do not add any conversational text, explanations, greetings, quotes, or markdown backticks around it. Keep it concise (typically 5 to 12 words).

Example 1:
User: "как получить все стены в ревите"
Output: FilteredElementCollector retrieve all Wall elements in Revit API

Example 2:
User: "создать транзакцию в C#"
Output: Transaction Start Commit Revit API C# code sample

Example 3:
User: "how to get element by id"
Output: Document GetElement ElementId Revit API

Now, translate and optimize this query:
"${userQuery}"`;

  try {
    const response = await callLlmChat(config, systemPrompt, []);
    if (response) {
      let cleaned = response.replace(/^["'`]|["'`]$/g, "").trim();
      console.log(`Original search query: "${userQuery}" -> Translated & Reformulated: "${cleaned}"`);
      return cleaned;
    }
  } catch (err: any) {
    console.error("Failed to translate/reformulate search query:", err.message);
  }

  return userQuery;
}

// Decompose a user query into multiple precise English vector search queries if it is complex/multi-topic
async function decomposeUserQuery(userQuery: string, config: ActiveConfig): Promise<string[]> {
  const systemPrompt = `You are an expert search planner and query decomposer for Autodesk Revit API, C#, .NET, Navisworks API, and BIM development.
Your task is to analyze the user's input (which can be in Russian, English, or another language) and plan semantic vector search queries for a RAG database.

If the user is asking about:
1. Multiple different API classes or methods (e.g., FilteredElementCollector AND Transactions).
2. Multiple distinct tasks (e.g., how to retrieve walls, and how to change parameters).
3. Contrasting or comparing multiple Revit versions (e.g., changes between Revit 2023 and Revit 2025).

Decompose the user's request into 1 to 3 distinct, precise, and highly technical English search queries. Each query should be focused on one technical concept, class name, or version change.
If the query is already simple and focused on a single topic, return a single-item array with the translated/reformulated query.

Your output MUST be a valid JSON array of strings. Do NOT include markdown code blocks, backticks, or any explanations. Just the JSON array.

Example 1 (Complex Multi-Topic):
User: "как получить стены в Revit и поменять их параметры"
Output: ["FilteredElementCollector Wall", "Parameter Set value Revit API"]

Example 2 (Version Comparison):
User: "какие изменения в транзакциях в ревите 2024 и 2025"
Output: ["Transaction changes Revit 2024 API", "Transaction changes Revit 2025 API"]

Example 3 (Simple Query):
User: "создать транзакцию C#"
Output: ["Transaction Start Commit Revit API"]

Now decompose this query:
"${userQuery}"`;

  try {
    const response = await callLlmChat(config, systemPrompt, []);
    if (response) {
      let cleaned = response.trim();
      // Remove possible markdown JSON code blocks
      cleaned = cleaned.replace(/^```json/i, "").replace(/^```/, "").replace(/```$/, "").trim();
      
      const parsed = JSON.parse(cleaned);
      if (Array.isArray(parsed) && parsed.length > 0) {
        console.log(`Decomposed query: "${userQuery}" into:`, parsed);
        return parsed.map(q => q.trim()).filter(Boolean);
      }
    }
  } catch (err: any) {
    console.error("Failed to decompose user query, falling back to single translation:", err.message);
  }

  // Fallback: translate as a single query
  const single = await translateAndReformulateQuery(userQuery, config);
  return [single];
}

// List of available collections and their descriptions
const COLLECTIONS_INFO = [
  { id: "revit_api_knowledge", name: "Revit API Knowledge", desc: "Revit API classes, methods, and properties" },
  { id: "Revit_SDK_Samples", name: "Revit SDK Samples", desc: "Official Revit SDK sample code & patterns" },
  { id: "navisworks_api_bge", name: "Navisworks API", desc: "Navisworks automation API docs" },
  { id: "revit_api_whatsnew", name: "Revit What's New", desc: "Breaking changes, deprecations & features (2022–2026)" }
];

// Helper to extract clean document fields from any Qdrant payload variation
function extractDocumentFields(payload: any) {
  if (!payload) return { title: "Untitled", content: "", code: "", source: "" };

  const title = payload.title || payload.name || payload.class_name || payload.method_name || payload.header || payload.file_name || "Untitled";
  
  // Find content
  const content = payload.text || payload.body || payload.content || payload.description || payload.context || payload.chunk_text || payload.chunk || "";
  
  // Find code
  const code = payload.code || payload.snippet || payload.example || payload.source || "";
  
  // Find extra fields like source file, version, year
  const source = payload.url || payload.link || payload.source_file || payload.path || payload.file || "";
  
  return { title, content, code, source, raw: payload };
}

// Function to call RouterAI or Ollama embedding API and search Qdrant collections
async function searchQdrant(queryText: string, collections: string[], config: ActiveConfig, limitPerCollection: number = 4) {
  let vector: number[];

  if (config.useOllama) {
    const embModel = config.embeddingModel === "baai/bge-m3" ? "nomic-embed-text" : config.embeddingModel;
    vector = await getOllamaEmbedding(config.routeraiBaseUrl, embModel, queryText);
  } else {
    if (!config.routeraiKey) {
      throw new Error("ROUTERAI_API_KEY is not defined in the environment. Please add it to your secrets/variables.");
    }

    const embeddingResp = await fetch(`${config.routeraiBaseUrl}/embeddings`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${config.routeraiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: config.embeddingModel,
        input: queryText,
      }),
      signal: AbortSignal.timeout(30000),
    });

    if (!embeddingResp.ok) {
      const errorText = await embeddingResp.text();
      throw new Error(`RouterAI embedding failed: ${embeddingResp.statusText} - ${errorText}`);
    }

    const embeddingData = await embeddingResp.json();
    vector = embeddingData.data?.[0]?.embedding;
  }

  if (!vector) {
    throw new Error("Failed to get embedding vector from response.");
  }

  // 2. Query Qdrant for each requested collection
  const rawQdrantUrl = (config.qdrantUrl || "http://d9e0f9d73f7a.vps.myjino.ru:6333").replace(/\/$/, "");
  const qdrantUrl = await resolveQdrantUrl(rawQdrantUrl);
  const allResults: any[] = [];

  for (const collection of collections) {
    try {
      const qdrantResp = await fetch(`${qdrantUrl}/collections/${collection}/points/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          vector: vector,
          limit: limitPerCollection,
          with_payload: true,
          with_vector: false,
        }),
        signal: AbortSignal.timeout(15000),
      });

      if (!qdrantResp.ok) {
        console.error(`Qdrant search failed for collection ${collection}: ${qdrantResp.statusText}`);
        continue;
      }

      const qdrantData = await qdrantResp.json();
      if (qdrantData.result && Array.isArray(qdrantData.result)) {
        for (const point of qdrantData.result) {
          allResults.push({
            id: point.id,
            score: point.score,
            payload: point.payload,
            collection: collection,
          });
        }
      }
    } catch (err: any) {
      console.error(`Error querying Qdrant for collection ${collection}:`, err.message);
    }
  }

  // Sort by score descending
  allResults.sort((a, b) => b.score - a.score);
  return allResults;
}

// ── Local SQLite DB search (replaces remote Tree API) ─────────────────────

// ── Tree API base URL (SSH tunnel: localhost:7402 → remote:7401) ────────
const TREE_API_BASE = process.env.TREE_API_URL || "http://localhost:7402";
const TREE_API_VERSIONS = ["2022", "2023", "2024", "2025", "2026", "2027"];

// Fetch full markdown content for a class or member from remote Tree API
async function fetchRemoteSqlContent(href: string): Promise<string> {
  try {
    const resp = await fetch(`${TREE_API_BASE}/api/tree/content?href=${encodeURIComponent(href)}`, {
      signal: AbortSignal.timeout(10000),
    });
    if (resp.ok) {
      const data = await resp.json();
      return data.content_md || data.description || "";
    }
  } catch (err: any) {
    // silently ignore — fallback to local SQLite
  }
  return "";
}

// Fetch full markdown content from local SQLite (fallback)
function fetchLocalSqlContent(href: string): string | null {
  if (!sqlDb) return null;
  try {
    const stmt = sqlDb.prepare("SELECT content_md FROM api_content WHERE href = $href");
    stmt.bind({ $href: href });
    if (stmt.step()) {
      const row = stmt.getAsObject() as any;
      stmt.free();
      return row.content_md || null;
    }
    stmt.free();
    return null;
  } catch {
    return null;
  }
}

// Search via remote Tree API (through SSH tunnel)
async function searchRemoteTreeApi(queryText: string, limitPerVersion: number): Promise<any[]> {
  const searchPromises = TREE_API_VERSIONS.map(async (version) => {
    try {
      const resp = await fetch(`${TREE_API_BASE}/api/tree/search?version=${version}&q=${encodeURIComponent(queryText)}&limit=${limitPerVersion}`, {
        signal: AbortSignal.timeout(15000),
      });
      if (!resp.ok) return [];
      const data = await resp.json();
      if (data && Array.isArray(data.items)) {
        return data.items.map((item: any) => ({ ...item, version }));
      }
    } catch (e: any) {
      return [];
    }
    return [];
  });

  const allResults = (await Promise.all(searchPromises)).flat();
  if (allResults.length === 0) return [];

  const topResults = allResults.slice(0, 6);
  return await Promise.all(topResults.map(async (item) => {
    let contentMd = "";
    if (item.has_content !== false) {
      contentMd = await fetchRemoteSqlContent(item.href);
    }
    if (!contentMd) {
      contentMd = `### Revit API Class/Member: ${item.title}\n**Namespace / Path:** \`${item.path}\`\n**Revit Version:** ${item.version}\n**Type:** ${item.entry_type}\n\n*This element exists in the database.*`;
    }
    return {
      id: `sql_${item.version}_${item.href}`,
      score: 0.95,
      collection: `sql_revit_${item.version}`,
      payload: {
        title: `${item.title} (Revit ${item.version})`,
        text: item.path || "",
        content: contentMd,
        source_file: item.path || "",
        version: item.version,
        entry_type: item.entry_type,
        href: item.href,
      },
    };
  }));
}

// Search classes/members via remote Tree API OR local SQLite fallback
async function searchSqlAndBuildResults(queryText: string, config: ActiveConfig, limitPerVersion: number = 2) {
  // Try remote Tree API (SSH tunnel) first
  const remoteResults = await searchRemoteTreeApi(queryText, limitPerVersion);
  if (remoteResults.length > 0) {
    console.log(`Remote Tree API: ${remoteResults.length} results for "${queryText}"`);
    return remoteResults;
  }

  // Fallback: local SQLite
  console.warn(`Remote Tree API unavailable, falling back to local SQLite for "${queryText}"`);
  if (!sqlDb) return [];

  const localRows: any[] = [];
  const likeQuery = `%${queryText}%`;
  const startsWithQuery = `${queryText}%`;

  for (const version of TREE_API_VERSIONS) {
    try {
      const stmt = sqlDb.prepare(`
        SELECT ae.href, ae.title, ae.entry_type, ae.path,
               CASE WHEN c.content_md IS NOT NULL THEN 1 ELSE 0 END AS has_content
        FROM api_entry_versions ev
        JOIN api_entries ae ON ev.href = ae.href
        LEFT JOIN api_content c ON ae.href = c.href
        WHERE ev.version = $version
          AND (ae.title LIKE $like OR ae.short_title LIKE $like OR ae.path LIKE $like OR c.content_md LIKE $like)
        ORDER BY
          CASE WHEN ae.title LIKE $startsWith THEN 0
               WHEN ae.short_title LIKE $startsWith THEN 1
               ELSE 2 END,
          ae.title
        LIMIT $limit
      `);
      stmt.bind({ $version: version, $like: likeQuery, $startsWith: startsWithQuery, $limit: limitPerVersion });
      while (stmt.step()) {
        localRows.push({ ...stmt.getAsObject(), version });
      }
      stmt.free();
    } catch {
      // skip version on error
    }
  }

  if (localRows.length === 0) return [];
  const topResults = localRows.slice(0, 6);

  return topResults.map((item) => {
    let contentMd = "";
    if (item.has_content) {
      contentMd = fetchLocalSqlContent(item.href) || "";
    }
    if (!contentMd) {
      contentMd = `### Revit API Class/Member: ${item.title}\n**Namespace / Path:** \`${item.path}\`\n**Revit Version:** ${item.version}\n**Type:** ${item.entry_type}\n\n*This element exists in the database.*`;
    }
    return {
      id: `sql_${item.version}_${item.href}`,
      score: 0.95,
      collection: `sql_revit_${item.version}`,
      payload: {
        title: `${item.title} (Revit ${item.version})`,
        text: item.path || "",
        content: contentMd,
        source_file: item.path || "",
        version: item.version,
        entry_type: item.entry_type,
        href: item.href,
      },
    };
  });
}

// API: Get app configurations (to verify status in UI and fetch real Qdrant collection stats)
app.get("/api/config", async (req, res) => {
  const config = getRequestConfig(req);
  const rawQdrantUrl = (config.qdrantUrl || "http://d9e0f9d73f7a.vps.myjino.ru:6333").replace(/\/$/, "");
  const qdrantUrl = await resolveQdrantUrl(rawQdrantUrl);
  
  const updatedCollections = await Promise.all(
    COLLECTIONS_INFO.map(async (col) => {
      try {
        const resp = await fetch(`${qdrantUrl}/collections/${col.id}`, { signal: AbortSignal.timeout(10000) });
        if (resp.ok) {
          const data = await resp.json();
          if (data && data.result) {
            // Qdrant returns points_count
            const count = data.result.points_count !== undefined ? data.result.points_count : (data.result.vectors_count || null);
            return {
              ...col,
              pointsCount: count
            };
          }
        }
      } catch (err: any) {
        console.error(`Failed to fetch stats for Qdrant collection ${col.id}:`, err.message);
      }
      return {
        ...col,
        pointsCount: null
      };
    })
  );

  res.json({
    hasApiKey: !!config.routeraiKey,
    collections: updatedCollections,
    defaultModel: config.llmModel,
    embeddingModel: config.embeddingModel,
    useOllama: config.useOllama,
    routeraiBaseUrl: config.routeraiBaseUrl,
    qdrantUrl: config.qdrantUrl
  });
});

// API: Search Qdrant and SQL Tree Database directly
app.post("/api/search", async (req, res) => {
  try {
    const config = getRequestConfig(req);
    const { query, collections, limit } = req.body;
    if (!query) {
      return res.status(400).json({ error: "Missing 'query' parameter" });
    }

    const selectedCollections = collections && Array.isArray(collections) && collections.length > 0
      ? collections
      : COLLECTIONS_INFO.map(c => c.id);

    const limitVal = typeof limit === "number" ? limit : 4;

    // Decompose user's query into multiple sub-queries for broader and more precise coverage
    const subQueries = await decomposeUserQuery(query, config);
    const optimizedQuery = subQueries.join(" | ");
    
    // For SQL Tree API search, use the ORIGINAL user query (text-based LIKE search)
    // For Qdrant, use the LLM-reformulated sub-queries (optimized for vector embeddings)
    const sqlQuery = query; // original user query is best for SQL LIKE search
    
    // Fetch in parallel for all sub-queries (decoupled: SQL and Qdrant run independently)
    const searchPromises = subQueries.map(async (subQuery) => {
      const [qdrantResults, sqlResults] = await Promise.allSettled([
        searchQdrant(subQuery, selectedCollections, config, limitVal),
        searchSqlAndBuildResults(sqlQuery, config, 2) // use original query for SQL search
      ]);
      const collected: any[] = [];
      if (sqlResults.status === "fulfilled") collected.push(...sqlResults.value);
      if (qdrantResults.status === "fulfilled") collected.push(...qdrantResults.value);
      return collected;
    });

    const allSubResults = await Promise.all(searchPromises);
    const combinedResults = allSubResults.flat();

    // De-duplicate results
    const seenIds = new Set<string>();
    let uniqueResults = combinedResults.filter(res => {
      const id = res.id;
      if (!id || seenIds.has(String(id))) {
        return false;
      }
      seenIds.add(String(id));
      return true;
    });

    // Sort by match score descending
    uniqueResults.sort((a, b) => (b.score || 0) - (a.score || 0));

    // Limit to top 16 highest quality results
    if (uniqueResults.length > 16) {
      uniqueResults = uniqueResults.slice(0, 16);
    }

    return res.json({ results: uniqueResults, optimizedQuery });
  } catch (err: any) {
    console.error("Error in /api/search:", err);
    return res.status(500).json({ error: err.message || "Internal search error" });
  }
});

// API: Chat with context (RAG)
app.post("/api/chat", async (req, res) => {
  try {
    const config = getRequestConfig(req);
    const { messages, collections } = req.body;
    if (!messages || !Array.isArray(messages) || messages.length === 0) {
      return res.status(400).json({ error: "Missing or invalid 'messages' array" });
    }

    const selectedCollections = collections && Array.isArray(collections) && collections.length > 0
      ? collections
      : COLLECTIONS_INFO.map(c => c.id);

    // Find the last user message to use as the search query
    const lastUserMessage = [...messages].reverse().find(m => m.role === "user");
    const queryText = lastUserMessage ? lastUserMessage.content : "";

    let searchResults: any[] = [];
    let optimizedQuery = "";
    if (queryText) {
      try {
        // Decompose user's query into multiple sub-queries (C# technical aspects or versions)
        const subQueries = await decomposeUserQuery(queryText, config);
        optimizedQuery = subQueries.join(" | ");
        
        // Fetch in parallel for each sub-query (decoupled: SQL and Qdrant run independently)
        // SQL Tree API uses the ORIGINAL user query (text-based LIKE search)
        const searchPromises = subQueries.map(async (subQuery) => {
          const [qdrantResults, sqlResults] = await Promise.allSettled([
            searchQdrant(subQuery, selectedCollections, config, 3), // limit 3 per collection to keep payload size optimal
            searchSqlAndBuildResults(queryText, config, 2) // use original query for SQL LIKE search
          ]);
          const collected: any[] = [];
          if (sqlResults.status === "fulfilled") collected.push(...sqlResults.value);
          if (qdrantResults.status === "fulfilled") collected.push(...qdrantResults.value);
          return collected;
        });

        const allSubResults = await Promise.all(searchPromises);
        const combinedResults = allSubResults.flat();

        // De-duplicate results by unique ID
        const seenIds = new Set<string>();
        searchResults = combinedResults.filter(res => {
          const id = res.id;
          if (!id || seenIds.has(String(id))) {
            return false;
          }
          seenIds.add(String(id));
          return true;
        });

        // Sort by match score descending (ensures SQL results are preferred and highest scores appear first)
        searchResults.sort((a, b) => (b.score || 0) - (a.score || 0));

        // Limit to top 16 highest quality matches to avoid overloading the context window
        if (searchResults.length > 16) {
          searchResults = searchResults.slice(0, 16);
        }
      } catch (err: any) {
        console.error("Search failed, continuing chat without search results:", err.message);
      }
    }

    // Build context string from search results
    let contextStr = "";
    if (searchResults.length > 0) {
      contextStr = "Here are the most relevant documentation and code entries found in the RAG database:\n\n";
      searchResults.forEach((res, index) => {
        const fields = extractDocumentFields(res.payload);
        let colInfo = COLLECTIONS_INFO.find(c => c.id === res.collection)?.name || res.collection;
        if (res.collection && res.collection.startsWith("sql_revit_")) {
          const version = res.collection.replace("sql_revit_", "");
          colInfo = `SQL Database (Revit ${version} API)`;
        }
        
        contextStr += `--- Document #${index + 1} (Collection: ${colInfo}, Match Score: ${(res.score * 100).toFixed(1)}%) ---\n`;
        contextStr += `Title: ${fields.title}\n`;
        if (res.payload && res.payload.version) {
          contextStr += `Target Revit Version: ${res.payload.version}\n`;
        }
        if (res.payload && res.payload.entry_type) {
          contextStr += `API Member Type: ${res.payload.entry_type}\n`;
        }
        if (fields.source) contextStr += `Source/File: ${fields.source}\n`;
        if (fields.content) contextStr += `Content: ${fields.content}\n`;
        if (fields.code) {
          contextStr += `Code/Snippet:\n\`\`\`csharp\n${fields.code}\n\`\`\`\n`;
        }
        contextStr += `\n`;
      });
    } else {
      contextStr = "No direct documentation or code entries were found matching the query in the database. Use your general training data for Revit/Navisworks API to answer, but let the user know that no direct RAG matches were found.";
    }

    const systemPrompt = `You are an expert Revit API, Revit SDK, Navisworks API, and BIM Development Assistant.
Your goal is to answer developer questions accurately, providing clean, production-ready C# code examples, explanations, and advice on breaking changes or best practices.

Use the provided RAG database search results below to formulate your response. 
- ALWAYS pay close attention to the "Target Revit Version" and "Collection" metadata for each search result. 
- You have access to SQL Database sources representing Revit API across versions 2022, 2023, 2024, 2025, 2026, and 2027.
- If the user asks about version differences, deprecations, changes, or how to write code for multiple or specific versions:
  1. Contrast the search results for different Revit versions side-by-side.
  2. Clearly state when a class, method, or property was introduced, renamed, changed, or deprecated/removed (e.g. "In Revit 2024+, use X; in Revit 2023 and earlier, use Y").
  3. Offer version-specific code snippets or workarounds where there are differences.
- Always prefer information and code snippets from the retrieved search results if they are relevant to the user's question.
- Cite the source collections (e.g. Revit API Knowledge, Revit SDK Samples, Revit What's New, Navisworks API, SQL Database Revit 2022-2027) when you use information from them.
- If the search results do not contain the direct answer, use your pre-trained developer knowledge of Autodesk Revit API / Navisworks API (C# / .NET) to answer fully and correctly, but clearly specify that the answer is based on general knowledge rather than a direct database match.
- Provide clean, well-commented C# code examples whenever possible, following Revit API guidelines (e.g., using transactions properly, handling document modification states, checking for nulls).
- Respond in the language used by the user. If they write in Russian, reply in Russian. If they write in English, reply in English.

--- RAG DATABASE SEARCH CONTEXT ---
${contextStr}
----------------------------------
`;

    // Format messages for active LLM (limit history to last 10 messages for token efficiency and memory management)
    const recentMessages = messages.slice(-10);
    
    // Call Chat
    const answer = await callLlmChat(config, systemPrompt, recentMessages);

    return res.json({
      answer: answer,
      searchResults: searchResults,
      optimizedQuery: optimizedQuery
    });

  } catch (err: any) {
    console.error("Error in /api/chat:", err);
    const causeMsg = err.cause ? ` (Cause: ${err.cause.message || JSON.stringify(err.cause)})` : "";
    return res.status(500).json({ error: (err.message || "Internal server error") + causeMsg });
  }
});

// Vite middleware for development or serving compiled client files
async function startServer() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on port ${PORT}`);
  });
}

startServer().then(() => initSqlite());
