import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { getDb } from "../db.js";

const INDEX_SQL = `
  SELECT
    d.document_id,
    d.title,
    d.source_id,
    s.name AS source_name,
    dv.source_url
  FROM documents d
  JOIN sources s            ON s.source_id  = d.source_id
  JOIN document_versions dv ON dv.document_id = d.document_id
  WHERE dv.is_current = 1
  ORDER BY s.name, d.title
`;

function buildIndexText(): string {
  const db = getDb();
  const rows = db.prepare(INDEX_SQL).all() as Array<{
    document_id: string;
    title: string;
    source_id: string;
    source_name: string;
    source_url: string;
  }>;

  const lines = [
    "# Vihreiden korpus — dokumenttiluettelo",
    `Yhteensä ${rows.length} dokumenttia.`,
    "",
    "Muoto: document_id | title | source_name | source_url",
    "",
  ];

  for (const r of rows) {
    lines.push(`${r.document_id} | ${r.title} | ${r.source_name} | ${r.source_url}`);
  }

  return lines.join("\n");
}

export function registerIndexResource(server: McpServer): void {
  server.resource(
    "green-index",
    "green://index",
    {
      description:
        "Lista kaikista Vihreiden korpuksen dokumenteista (document_id, title, source). " +
        "Käytä tätä selvittääksesi saatavilla olevat dokumentit ennen get_document-kutsua.",
      mimeType: "text/plain",
    },
    async (_uri) => ({
      contents: [
        {
          uri: "green://index",
          text: buildIndexText(),
          mimeType: "text/plain",
        },
      ],
    })
  );
}
