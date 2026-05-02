import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { search, buildFtsQuery } from "../search.js";
import type { ChunkResult } from "../types.js";

// ---------------------------------------------------------------------------
// Response-size caps (claude.ai web renderer threshold workaround)
// ---------------------------------------------------------------------------
//
// claude.ai's MCP renderer hangs silently when a tool response's cumulative
// text content exceeds ~5 KB (operator bisected: limit=3 ≈ 4.5 KB worked,
// limit=4 ≈ 6 KB hung, same query). The threshold is undocumented and
// shared with the code path described in anthropics/claude-code #38437
// ("MCP proxy silently hangs on tool_use results"). It's MUCH stricter
// than Claude Code's documented MAX_MCP_OUTPUT_TOKENS (~25,000 tokens /
// ~500 KB ceiling).
//
// Two coordinated knobs:
//   1. MAX_CHUNK_TEXT_CHARS — per-chunk text cap. Predictable per-block
//      size, avoids any single chunk being pathologically large.
//   2. MAX_RESPONSE_BYTES — total cumulative response cap. Loop stops
//      adding result blocks once cumulative bytes (incl. reserved header
//      space) would exceed this. Whatever fits is returned; the rest are
//      reported as dropped in the header so the LLM knows to refine.
//
// 4500 bytes ≈ 25% safety margin under the operator's observed
// limit=3-success / limit=4-hang boundary. Drop further if a future test
// shows hangs at this size; relax if a future claude.ai client release
// raises the threshold.

const MAX_CHUNK_TEXT_CHARS = 800;
const MAX_RESPONSE_BYTES = 4500;
const HEADER_RESERVE_BYTES = 400; // upper bound on the header block size; reserved before result-block loop

const SearchChunksInput = z.object({
  query: z.string().min(1).describe(
    "Hakutermi tai -lause suomeksi. Esimerkki: 'ydinvoima', 'Nato-jäsenyys', 'perustulo'."
  ),
  limit: z.coerce.number().int().min(1).max(20).default(5).describe(
    "Tulosten maksimimäärä (1–20, oletus 5). Huom: vastauksen kokoraja saattaa palauttaa vähemmän chunkkeja kuin pyydetty — katso vastauksen header."
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

VASTAUKSEN KOKORAJA: claude.ai:n MCP-renderöijä jämähtää isoihin vastauksiin (~5 KB).
Tämä työkalu palauttaa enintään ~4 chunkkia per kutsu (kokoraja, ei korpuksen rajoite).
Kunkin chunkin teksti on katkaistu ${MAX_CHUNK_TEXT_CHARS} merkkiin. Jos käyttäjän
kysymys vaatii kattavampaa hakua, KUTSU TYÖKALUA USEITA KERTOJA ERI HAKUTERMEILLÄ:
- Tarkenna alkuperäisiä hakusanoja (esim. "perustulo" → "perustulokokeilu")
- Käytä lähikäsitteitä (esim. "perustulo" → "sosiaaliturva", "kelan tuet")
- Hae eri näkökulmista (esim. politiikka vs. talous vs. työmarkkinat)
Eri hakutermit löytävät usein eri chunkit samasta aiheesta.

Jos haluat yhden chunkin koko tekstin (ilman 800-merkin katkaisua), kutsu
corpus_get_document chunk-ID:llä.

Jos tulos on tyhjä (0 chunkkia): muotoile hakutermi eri sanastolla ja kutsu uudelleen
attempt-arvolla 2 tai 3. Maksimissaan 3 yritystä per käyttäjän kysymys.

Jos kaikki 3 yritystä palauttavat 0 tulosta: ilmoita käyttäjälle ettei aiheesta löydy
tietoa korpuksesta — älä keksi tietoja.

Vastaus: ensimmäinen content-blokki on tiivistelmä (löytyikö, kuinka monta näytetään,
mitä jäi pois); sen jälkeen yksi blokki per chunk sisältäen otsikon, lähde-URL:n,
otsikkopolun ja chunk-tekstin (Finnish plain text, max ${MAX_CHUNK_TEXT_CHARS} merkkiä).`;

// ---------------------------------------------------------------------------
// Response formatters (extracted as pure functions for testability)
// ---------------------------------------------------------------------------
//
// We return one MCP content block per result, plus a leading header block.
// Smaller individual blocks (~1 KB each), plain-text content, no JSON
// wrapper, no markdown nesting. Each block self-cites with title + URL +
// path so the LLM can quote a chunk by source without further parsing.

/**
 * Truncate chunk text to MAX_CHUNK_TEXT_CHARS with a "…" suffix when over.
 * Returns the (possibly truncated) text plus a flag.
 */
export function truncateChunkText(
  text: string,
): { text: string; truncated: boolean } {
  if (text.length <= MAX_CHUNK_TEXT_CHARS) return { text, truncated: false };
  return { text: text.slice(0, MAX_CHUNK_TEXT_CHARS) + "…", truncated: true };
}

export function formatHeaderBlock(
  query: string,
  attempt: number,
  totalFound: number,
  returned: number,
  dropped: number,
  anyTruncated: boolean,
): string {
  if (totalFound === 0) {
    const attemptNote = attempt > 1 ? ` (yritys ${attempt}/3)` : "";
    return `Korpuksesta ei löytynyt osumia haulle "${query}"${attemptNote}.`;
  }

  const lines: string[] = [];

  if (dropped > 0) {
    lines.push(
      `Löytyi ${totalFound} osumaa haulle "${query}". ` +
        `Näytetään ${returned} ensimmäistä — vastauksen kokoraja täyttyi ` +
        `(claude.ai-renderöijän rajoite, ~5 KB). ` +
        `Saadaksesi muita lähteitä, kutsu uudelleen tarkennetulla hakutermillä ` +
        `(eri synonyymit / lähikäsitteet löytävät usein eri chunkit samasta aiheesta).`,
    );
  } else {
    const plural = totalFound === 1 ? "osuma" : "osumaa";
    lines.push(
      `Löytyi ${totalFound} ${plural} haulle "${query}". ` +
        `Tulokset järjestyksessä parhaasta huonompaan:`,
    );
  }

  if (anyTruncated) {
    lines.push(
      "",
      `Huom: yhden tai useamman chunkin teksti on katkaistu ${MAX_CHUNK_TEXT_CHARS} ` +
        `merkkiin. Käytä corpus_get_document-työkalua chunk-ID:llä koko tekstille.`,
    );
  }

  return lines.join("\n");
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

      // Build result blocks with byte-budget enforcement. Header is built
      // last (needs to know how many were included vs dropped) but inserted
      // first into the final blocks array.
      const resultBlocks: Array<{ type: "text"; text: string }> = [];
      let cumulativeResultBytes = 0;
      let returned = 0;
      let dropped = 0;
      let anyTruncated = false;

      for (let i = 0; i < results.length; i++) {
        const original = results[i]!;
        const { text: truncatedText, truncated } = truncateChunkText(original.text);
        if (truncated) anyTruncated = true;

        const blockText = formatResultBlock(
          { ...original, text: truncatedText },
          i,
          results.length,
        );

        // Reserve HEADER_RESERVE_BYTES for the header (worst case). Stop
        // adding result blocks once cumulative + reserve would exceed
        // the cap.
        if (
          cumulativeResultBytes + blockText.length + HEADER_RESERVE_BYTES >
          MAX_RESPONSE_BYTES
        ) {
          dropped = results.length - i;
          break;
        }

        resultBlocks.push({ type: "text" as const, text: blockText });
        cumulativeResultBytes += blockText.length;
        returned++;
      }

      const headerText = formatHeaderBlock(
        query,
        attempt,
        results.length,
        returned,
        dropped,
        anyTruncated,
      );
      const blocks: Array<{ type: "text"; text: string }> = [
        { type: "text" as const, text: headerText },
        ...resultBlocks,
      ];

      // Emit a single one-line diagnostic per call. Tracks: result count,
      // total payload bytes, block count, and (if any) drops/truncations
      // so future regressions are bisectable from `docker logs vihrea-mcp`.
      const totalBytes = blocks.reduce((sum, b) => sum + b.text.length, 0);
      const dropNote = dropped > 0 ? ` (${dropped} dropped due to size cap)` : "";
      const truncNote = anyTruncated ? " (some chunk text truncated)" : "";
      console.log(
        `[corpus_search_chunks] query=${JSON.stringify(query)} ` +
          `limit=${limit} attempt=${attempt} → ` +
          `${returned}/${results.length} result${results.length === 1 ? "" : "s"} returned, ` +
          `${totalBytes} bytes across ${blocks.length} content blocks` +
          dropNote +
          truncNote,
      );

      // Optional per-block summary dump for diagnosing downstream rendering
      // bugs. Enable with CORPUS_DEBUG_DUMP=1. Off by default.
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
