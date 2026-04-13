import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerSearchChunks } from "./tools/search_chunks.js";
import { registerGetDocument } from "./tools/get_document.js";
import { registerListSources } from "./tools/list_sources.js";
import { registerIndexResource } from "./resources/index_resource.js";
import { registerDocumentResource } from "./resources/document_resource.js";
import { registerHaeKantaPrompt } from "./prompts/hae_kanta.js";

const server = new McpServer({
  name: "green-data",
  version: "0.1.0",
});

registerSearchChunks(server);
registerGetDocument(server);
registerListSources(server);
registerIndexResource(server);
registerDocumentResource(server);
registerHaeKantaPrompt(server);

// Vaihe 8: järjestelmäprompt (system_prompt.md)

const transport = new StdioServerTransport();
await server.connect(transport);
