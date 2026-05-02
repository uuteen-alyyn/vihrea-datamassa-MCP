import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { search, buildFtsQuery } from "../search.js";
import type { SearchChunksOutput } from "../types.js";

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

Palauttaa: lista chunkeista kentillä chunk_id, title, source_url, heading_path,
score (negatiivinen float, pienempi = parempi osuvuus), text.`;

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

      let results;
      let queryUsed: string;

      try {
        queryUsed = buildFtsQuery(query);
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

      const output: SearchChunksOutput = {
        results,
        query_used: queryUsed,
        attempt,
      };

      // Emit a single one-line diagnostic per call. Vihreä-MCP's deploy hit a
      // case where the HTTP layer returned 200 in 131 ms but claude.ai's UI
      // displayed "took very long, never finished" — the MCP wire response
      // was opaque from the access log alone. This log makes result count
      // and serialised payload size visible so future regressions are
      // bisectable from `docker logs vihrea-mcp` without standing up a
      // packet capture.
      const responseText = JSON.stringify(output, null, 2);
      console.log(
        `[corpus_search_chunks] query=${JSON.stringify(query)} ` +
          `limit=${limit} attempt=${attempt} → ` +
          `${results.length} result${results.length === 1 ? "" : "s"}, ` +
          `${responseText.length} bytes`,
      );

      // Optional full-payload dump for diagnosing downstream rendering bugs
      // (e.g. claude.ai's UI not displaying a 200-OK response). Enable with
      // CORPUS_DEBUG_DUMP=1 in the environment. Off by default; outputs
      // first 4 KB of the response to stderr, bracketed with markers for
      // easy grep/extract. Disable by removing the env var and restarting.
      // Server team's diagnostic ask: "could you dump the actual response
      // payload to logs (one-off debug line) for the next call and we'll
      // look at the structure?"
      if (process.env["CORPUS_DEBUG_DUMP"]) {
        const PREVIEW_LIMIT = 4096;
        const preview = responseText.slice(0, PREVIEW_LIMIT);
        console.log(
          `[corpus_search_chunks] DEBUG_DUMP_BEGIN ` +
            `(first ${preview.length} of ${responseText.length} bytes)`,
        );
        console.log(preview);
        console.log(`[corpus_search_chunks] DEBUG_DUMP_END`);
      }

      return {
        content: [
          {
            type: "text" as const,
            text: responseText,
          },
        ],
      };
    }
  );
}
