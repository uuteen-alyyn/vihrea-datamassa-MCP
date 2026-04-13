import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { getDb } from "../db.js";

const DOC_META_SQL = `
  SELECT
    d.document_id,
    d.title,
    s.name    AS source_name,
    dv.source_url,
    dv.published_at,
    dv.version_label,
    dv.is_current
  FROM documents d
  JOIN sources s            ON s.source_id  = d.source_id
  JOIN document_versions dv ON dv.document_id = d.document_id
  WHERE d.document_id = ?
    AND dv.is_current = 1
  LIMIT 1
`;

export function registerDocumentResource(server: McpServer): void {
  server.resource(
    "green-document",
    new ResourceTemplate("green://document/{document_id}", { list: undefined }),
    {
      description:
        "Metatiedot yksittäisestä dokumentista (title, source_url, published_at, is_current). " +
        "Nopea tarkistus ennen koko dokumentin lataamista get_document-työkalulla.",
      mimeType: "application/json",
    },
    async (uri, { document_id }) => {
      const db = getDb();

      const doc = db.prepare(DOC_META_SQL).get(document_id) as {
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
          contents: [
            {
              uri: uri.href,
              text: JSON.stringify({ error: `Dokumenttia ei löydy: "${document_id}"` }),
              mimeType: "application/json",
            },
          ],
        };
      }

      return {
        contents: [
          {
            uri: uri.href,
            text: JSON.stringify(doc, null, 2),
            mimeType: "application/json",
          },
        ],
      };
    }
  );
}
