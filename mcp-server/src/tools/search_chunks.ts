import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { search, buildFtsQuery } from "../search.js";
import type { ChunkResult } from "../types.js";

const SearchChunksInput = z.object({
  query: z.string().min(1).describe(
    "Hakutermi tai -lause suomeksi. Esimerkki: 'ydinvoima', 'Nato-jäsenyys', 'perustulo'."
  ),
  limit: z.coerce.number().int().min(1).max(20).default(5).describe(
    "Tulosten maksimimäärä (1–20, oletus 5)."
  ),
  attempt: z.coerce.number().int().min(1).max(3).default(1).describe(
    "Hakuyrityksen numero (1–3). Lisää tähän 1 per uudelleenyritys nollatuloksen jälkeen."
  ),
});

const DESCRIPTION = `\
Hakee Vihreiden asiakirjakorpuksesta relevantit tekstikatkelmat (chunkit) FTS5-haulla.

Käytä tätä aina kun käyttäjä kysyy Vihreiden kannasta, ohjelmasta tai menettelystä.

Hakustrategia: Snowball-stemmaus + prefix-matching + fraasihaku. Suomen taivutusmuodot
tunnistetaan automaattisesti — hae perusmuodolla tai kysymyksen omilla sanoilla.

Jos tulos on tyhjä (0 chunkkia): muotoile hakutermi eri sanastolla ja kutsu uudelleen
attempt-arvolla 2 tai 3. Maksimissaan 3 yritystä per käyttäjän kysymys.

Jos kaikki 3 yritystä palauttavat 0 tulosta: ilmoita käyttäjälle ettei aiheesta löydy
tietoa korpuksesta — älä keksi tietoja.

Vastaus: ensimmäinen content-blokki on tiivistelmä; sen jälkeen yksi blokki per chunk
sisältäen otsikon, lähde-URL:n, otsikkopolun ja chunk-tekstin (Finnish plain text).`;

// ---------------------------------------------------------------------------
// Response formatters (extracted as pure functions for testability)
// ---------------------------------------------------------------------------
//
// We return one MCP content block per result, plus a leading header block.
// Reasons:
//   1. Smaller individual blocks (~1–2 KB each vs 13–20 KB single blob).
//      Vihrea-MCP's deploy hit a claude.ai UI hang on the single-blob shape
//      even after stripping markdown from the response (see commits
//      1a6ff99 + 60f2972 for the diagnostic + markdown-strip iteration).
//      Multi-block sidesteps any single-blob rendering issue regardless of
//      what was actually causing it.
//   2. Plain-text content per block (labels + chunk text). No JSON wrapper,
//      no markdown nesting. claude.ai's renderer treats each block
//      independently.
//   3. Each block is human-readable and self-cites (title + URL + path),
//      so the LLM can quote a chunk by source without further parsing.

export function formatHeaderBlock(
  query: string,
  attempt: number,
  resultCount: number,
): string {
  if (resultCount === 0) {
    const attemptNote = attempt > 1 ? ` (yritys ${attempt}/3)` : "";
    return `Korpuksesta ei löytynyt osumia haulle "${query}"${attemptNote}.`;
  }
  const plural = resultCount === 1 ? "osuma" : "osumaa";
  return (
    `Löytyi ${resultCount} ${plural} haulle "${query}". ` +
    `Tulokset järjestyksessä parhaasta huonompaan:`
  );
}

export function formatResultBlock(
  result: ChunkResult,
  index: number,
  total: number,
): string {
  const headingPath = result.heading_path.join(" > ");
  const lines: string[] = [
    `Tulos ${index + 1}/${total} (osuvuus ${result.score.toFixed(2)})`,
    `Otsikko: ${result.title}`,
    `Lähde: ${result.source_url}`,
  ];
  if (headingPath) lines.push(`Polku: ${headingPath}`);
  lines.push(`Chunk ID: ${result.chunk_id}`);
  lines.push(""); // blank line before chunk text
  lines.push(result.text);
  return lines.join("\n");
}

export function registerSearchChunks(server: McpServer): void {
  server.tool(
    "search_chunks",
    DESCRIPTION,
    SearchChunksInput.shape,
    { readOnlyHint: true, idempotentHint: true },
    async ({ query, limit, attempt }) => {
      // attempt > 3 ei pitäisi tapahtua Zod-validoinnin jälkeen, mutta varmuuden vuoksi
      if (attempt > 3) {
        return {
          isError: true,
          content: [
            {
              type: "text" as const,
              text: "Maksimiyritykset (3) käytetty. Kerro käyttäjälle ettei aiheesta löydy tietoa.",
            },
          ],
        };
      }

      let results: ChunkResult[];

      try {
        // buildFtsQuery is called only for the diagnostic line below; the
        // actual FTS query is built inside search() itself.
        buildFtsQuery(query);
        results = search(query, limit);
      } catch (err) {
        return {
          isError: true,
          content: [
            {
              type: "text" as const,
              text: "Tietokantavirhe haun aikana. Yritä uudelleen.",
            },
          ],
        };
      }

      // Build content blocks: header + one per result.
      const blocks: Array<{ type: "text"; text: string }> = [
        { type: "text" as const, text: formatHeaderBlock(query, attempt, results.length) },
      ];
      for (let i = 0; i < results.length; i++) {
        blocks.push({
          type: "text" as const,
          text: formatResultBlock(results[i]!, i, results.length),
        });
      }

      // Emit a single one-line diagnostic per call. Tracks: result count,
      // total payload bytes (sum across all blocks), and block count.
      // Useful for bisecting future claude.ai-render regressions from
      // `docker logs vihrea-mcp` without a packet capture.
      const totalBytes = blocks.reduce((sum, b) => sum + b.text.length, 0);
      console.log(
        `[corpus_search_chunks] query=${JSON.stringify(query)} ` +
          `limit=${limit} attempt=${attempt} → ` +
          `${results.length} result${results.length === 1 ? "" : "s"}, ` +
          `${totalBytes} bytes across ${blocks.length} content blocks`,
      );

      // Optional per-block summary dump for diagnosing downstream rendering
      // bugs. Enable with CORPUS_DEBUG_DUMP=1. Off by default; outputs a
      // JSON array of {block, type, bytes, preview} per block, bracketed
      // with markers for easy grep/extract.
      if (process.env["CORPUS_DEBUG_DUMP"]) {
        const summary = blocks.map((b, i) => ({
          block: i,
          type: b.type,
          bytes: b.text.length,
          preview: b.text.slice(0, 200),
        }));
        console.log(
          `[corpus_search_chunks] DEBUG_DUMP_BEGIN ` +
            `(${blocks.length} blocks, ${totalBytes} bytes total)`,
        );
        console.log(JSON.stringify(summary, null, 2));
        console.log(`[corpus_search_chunks] DEBUG_DUMP_END`);
      }

      return { content: blocks };
    }
  );
}
