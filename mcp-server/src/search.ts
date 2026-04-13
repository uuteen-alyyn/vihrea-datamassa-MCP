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
    heading_path: JSON.parse(row.heading_path) as string[],
    score: row.score,
    text: row.text,
  }));
}
