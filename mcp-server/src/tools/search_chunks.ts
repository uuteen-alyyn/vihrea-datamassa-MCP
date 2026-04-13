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

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(output, null, 2),
          },
        ],
      };
    }
  );
}
