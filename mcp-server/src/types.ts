export interface ChunkResult {
  chunk_id: string;
  document_id: string;
  title: string;
  source_url: string;
  heading_path: string[];
  score: number;
  text: string;
}

export interface SearchChunksOutput {
  results: ChunkResult[];
  query_used: string;
  attempt: number;
}
