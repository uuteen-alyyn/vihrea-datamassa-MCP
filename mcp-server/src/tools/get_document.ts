import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { getDb } from "../db.js";

const GetDocumentInput = z.object({
  document_id: z.string().describe(
    "Dokumentin ID. Saadaan search_chunks-tuloksen document_id-kentästä tai green://index-resurssista."
  ),
});

const DESCRIPTION = `\
Palauttaa kaikki chunkit tietyltä dokumentilta järjestyksessä.

Käytä tätä kun haluat lukea koko ohjelman tai oppaan — ei vain yksittäisiä hakutuloksia.
document_id saadaan search_chunks-tuloksen document_id-kentästä tai green://index-resurssista.

Palauttaa: dokumentin metatiedot (title, source_url, published_at, version_label, is_current)
sekä kaikki chunkit järjestyksessä (chunk_order, heading_path, text).`;

const DOC_SQL = `
  SELECT
    d.document_id,
    d.title,
    s.name    AS source_name,
    dv.source_url,
    dv.published_at,
    dv.version_label,
    dv.is_current
  FROM documents d
  JOIN sources s              ON s.source_id  = d.source_id
  JOIN document_versions dv   ON dv.document_id = d.document_id
  WHERE d.document_id = ?
    AND dv.is_current = 1
  LIMIT 1
`;

const CHUNKS_SQL = `
  SELECT
    c.chunk_id,
    c.chunk_order,
    c.heading_path,
    c.text,
    c.tokens_estimate
  FROM chunks c
  JOIN document_versions dv ON dv.version_id = c.version_id
  WHERE c.document_id = ?
    AND dv.is_current = 1
  ORDER BY c.chunk_order
`;

export function registerGetDocument(server: McpServer): void {
  server.tool(
    "get_document",
    DESCRIPTION,
    GetDocumentInput.shape,
    { readOnlyHint: true, idempotentHint: true },
    async ({ document_id }) => {
      const db = getDb();

      const doc = db.prepare(DOC_SQL).get(document_id) as {
        document_id: string;
        title: string;
        source_name: string;
        source_url: string;
        published_at: string | null;
        version_label: string;
        is_current: number;
      } | undefined;

      if (!doc) {
        return {
          isError: true,
          content: [
            {
              type: "text" as const,
              text: `Dokumenttia ei löydy: "${document_id}". Tarkista document_id search_chunks-tuloksesta tai green://index-resurssista.`,
            },
          ],
        };
      }

      const chunks = db.prepare(CHUNKS_SQL).all(document_id) as Array<{
        chunk_id: string;
        chunk_order: number;
        heading_path: string;
        text: string;
        tokens_estimate: number | null;
      }>;

      const output = {
        document_id: doc.document_id,
        title: doc.title,
        source_name: doc.source_name,
        source_url: doc.source_url,
        published_at: doc.published_at,
        version_label: doc.version_label,
        chunk_count: chunks.length,
        chunks: chunks.map((c) => ({
          chunk_id: c.chunk_id,
          chunk_order: c.chunk_order,
          heading_path: JSON.parse(c.heading_path) as string[],
          tokens_estimate: c.tokens_estimate,
          text: c.text,
        })),
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
