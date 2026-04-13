import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { getDb } from "../db.js";

const DESCRIPTION = `\
Listaa kaikki korpuksen lähteet metatietoineen.

Käytä tätä selvittääksesi mitä aineistoa on saatavilla ennen hakua,
tai kun käyttäjä kysyy mistä tiedot on kerätty.

Palauttaa: lista lähteistä (source_id, name, source_type, source_url, document_count).`;

const SOURCES_SQL = `
  SELECT
    s.source_id,
    s.name,
    s.source_type,
    s.source_url,
    COUNT(d.document_id) AS document_count
  FROM sources s
  LEFT JOIN documents d ON d.source_id = s.source_id
  GROUP BY s.source_id
  ORDER BY s.name
`;

export function registerListSources(server: McpServer): void {
  server.tool(
    "list_sources",
    DESCRIPTION,
    {},
    { readOnlyHint: true, idempotentHint: true },
    async () => {
      const db = getDb();

      const rows = db.prepare(SOURCES_SQL).all() as Array<{
        source_id: string;
        name: string;
        source_type: string;
        source_url: string;
        document_count: number;
      }>;

      const output = {
        sources: rows,
        total_documents: rows.reduce((sum, r) => sum + r.document_count, 0),
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
