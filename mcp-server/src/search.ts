import { newStemmer } from "snowball-stemmers";
import { getDb } from "./db.js";
import type { ChunkResult } from "./types.js";

// ---------------------------------------------------------------------------
// Stemmaaja
// ---------------------------------------------------------------------------

const stemmer = newStemmer("finnish");

const MIN_STEM_LENGTH = 4; // lyhyemmät vartalot ilman prefix-tähteä

function stemToken(token: string): string {
  return stemmer.stem(token.toLowerCase());
}

// ---------------------------------------------------------------------------
// FTS5-kyselyjen rakentaminen
// ---------------------------------------------------------------------------

/**
 * Rakentaa FTS5-kyselymerkkijonon hakusyötteestä.
 *
 * Logiikka (identtinen pipeline/search.py:n kanssa):
 * - Jokainen token stemmataan → prefix-matching (stem*)
 * - Lyhyet vartalot (< MIN_STEM_LENGTH) haetaan sellaisenaan
 * - Monisanaiselle haulle lisätään koko fraasi lainausmerkeissä
 *
 * Esimerkkejä:
 *   "ydinvoimasta"     → 'ydinvoim*'
 *   "Lapin käsivarsi"  → '"Lapin käsivarsi" OR lapin* OR käsivarr*'
 */
export function buildFtsQuery(query: string): string {
  const tokens = query.trim().split(/\s+/);
  const parts: string[] = [];

  // Fraasihaku koko syötteelle jos useampi sana
  if (tokens.length > 1) {
    parts.push(`"${query.trim()}"`);
  }

  // Prefix-haku jokaiselle stemmatulle tokenille
  for (const token of tokens) {
    const clean = token.replace(/^[",.\s]+|[",.\s]+$/g, "");
    if (!clean) continue;

    const stem = stemToken(clean);
    if (stem.length >= MIN_STEM_LENGTH) {
      parts.push(`${stem}*`);
    } else {
      parts.push(clean.toLowerCase());
    }
  }

  // Poista duplikaatit säilyttäen järjestys
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const p of parts) {
    if (!seen.has(p)) {
      seen.add(p);
      unique.push(p);
    }
  }

  return unique.join(" OR ");
}

// ---------------------------------------------------------------------------
// Hakulogiikka
// ---------------------------------------------------------------------------

const SEARCH_SQL = `
  SELECT
    c.chunk_id,
    c.document_id,
    d.title,
    dv.source_url,
    c.heading_path,
    bm25(chunks_fts) AS score,
    c.text
  FROM chunks_fts
  JOIN chunks c          ON c.chunk_id    = chunks_fts.chunk_id
  JOIN documents d       ON d.document_id = c.document_id
  JOIN document_versions dv ON dv.version_id = c.version_id
  WHERE chunks_fts MATCH ?
    AND dv.is_current = 1
  ORDER BY score
  LIMIT ?
`;

export type { ChunkResult };

export function search(query: string, limit: number = 10): ChunkResult[] {
  const ftsQuery = buildFtsQuery(query);
  const db = getDb();

  const rows = db.prepare(SEARCH_SQL).all(ftsQuery, limit) as Array<{
    chunk_id: string;
    document_id: string;
    title: string;
    source_url: string;
    heading_path: string;
    score: number;
    text: string;
  }>;

  return rows.map((row) => ({
    chunk_id: row.chunk_id,
    document_id: row.document_id,
    title: row.title,
    source_url: row.source_url,
    // Parse defensively. Pipeline always inserts json.dumps([...]) so this
    // SHOULD always be a valid JSON array of strings — but if any historical
    // row has a malformed value, a single bad row should not throw and kill
    // the whole map (which would surface as "Tietokantavirhe" to the user
    // and was previously indistinguishable from a real DB error).
    // Markdown is stripped from each entry — see stripMarkdown() comment.
    heading_path: parseHeadingPath(row.heading_path, row.chunk_id).map(stripMarkdown),
    score: row.score,
    // Markdown stripped from chunk text too. Source documents are markdown,
    // so chunk text legitimately contains link/bold/italic syntax — but
    // claude.ai's MCP renderer (Vihrea-MCP-päätiedosto's only consumer at
    // present) hangs on the raw markdown inside JSON-stringified responses.
    // See "BUG B ROOT CAUSE — MARKDOWN COLLISION IN JSON-STRINGIFIED
    // RESPONSE BLOB" Logbook entry for the dump that pinpointed this.
    text: stripMarkdown(row.text),
  }));
}

function parseHeadingPath(raw: unknown, chunkId: string): string[] {
  if (raw == null) return [];
  if (typeof raw !== "string") return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return parsed.filter((s): s is string => typeof s === "string");
    }
    return [];
  } catch {
    console.warn(
      `[search] invalid heading_path JSON for chunk ${chunkId}: ${JSON.stringify(raw).slice(0, 80)}`,
    );
    return [];
  }
}

// ---------------------------------------------------------------------------
// Markdown stripping (claude.ai render-collision workaround)
// ---------------------------------------------------------------------------
//
// Source documents in the corpus (vihreat.fi pages, GitHub MD files,
// Google Sites scrapes) are processed as markdown end-to-end. Chunk
// `heading_path` entries and `text` fields therefore preserve the
// original markdown syntax: `[label](url)` link constructs (sometimes
// with `**bold**` inside the label), `**bold**`/`*italic*` emphasis
// runs, occasional bullet markers.
//
// That worked fine for any consumer that treats the response payload as
// opaque JSON. claude.ai's MCP renderer evidently does NOT — when the
// search response is JSON.stringify'd into a single text content block,
// embedded markdown inside the string values causes the renderer to hang
// (tool stays "running" indefinitely with no useful chat output, despite
// HTTP 200 / clean response server-side). Confirmed by capturing the
// response payload via the env-gated `CORPUS_DEBUG_DUMP` diagnostic from
// commit 1a6ff99 and identifying nested `[**...**](url)` constructs in
// every result's `text` field plus markdown-link entries inside
// `heading_path` arrays.
//
// We strip at the search-response boundary (here), NOT at chunk-build
// time in the pipeline. Pipeline chunks keep their full markdown so
// future consumers — and the existing `corpus_get_document` tool, which
// returns full document text — get the canonical version. Only the
// `corpus_search_chunks` response is sanitised, because that's the one
// failing.
//
// Strategy:
//   - `[label](url)` → `label (url)` — preserves both the human-readable
//     label and the URL; loses just the link brackets so the renderer
//     doesn't try to interpret them.
//   - `**x**` and `*x*` → `x` — strip emphasis markers entirely.
//   - Other markdown (headings, blockquotes, lists, code spans) is left
//     alone — chunk text rarely has these at line-start positions inside
//     a chunk, and stripping them broadly risks corrupting genuine
//     content (e.g. `*` inside Finnish words).

const MD_LINK_RE = /\[([^\]]+)\]\(([^)]+)\)/g;
const MD_BOLD_RE = /\*\*([^*\n]+)\*\*/g;
const MD_ITALIC_RE = /\*([^*\n]+)\*/g;

export function stripMarkdown(text: string): string {
  if (!text) return text;
  return text
    .replace(MD_LINK_RE, "$1 ($2)")
    .replace(MD_BOLD_RE, "$1")
    .replace(MD_ITALIC_RE, "$1");
}
