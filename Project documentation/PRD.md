# PRD: Green Data MCP Service

Version: 1.1
Date: 2026-04-12
Owner: Greens / AI infrastructure initiative

---

# 1. Project Overview

The goal of this project is to build a **public, read-only MCP (Model Context Protocol) service** that provides a machine-readable interface to the Greens’ public data corpus.

The service is designed to act as a **reliable knowledge source for AI agents** (e.g., Claude, ChatGPT). It enables agents to retrieve structured, versioned, and semantically coherent information that can be used to generate accurate answers.

⚠️ **Important language constraint**
All source material, indexed data, and responses served by the MCP must be **in Finnish only**.
The system does not need to support multilingual retrieval or translation in MVP.

---

## Architecture Overview

The system consists of two clearly separated components:

### 1. Build Pipeline (offline)

Responsible for:

* data ingestion (GitHub + scraping)
* normalization
* versioning
* chunking
* validation
* index generation

Produces immutable artifacts.

### 2. MCP Server (runtime)

Responsible for:

* serving data via MCP resources
* executing search and version resolution tools

⚠️ The runtime server **must never fetch or modify source data**.

---

## Deployment

* Local development: MCP via stdio
* Production: cloud deployment (Azure Container App is the leading candidate; not yet confirmed)
* Storage: cloud blob storage or bundled SQLite in the container image
* Artifacts are immutable and versioned
* Target: ~20–30 users, practically free in cloud at this scale

---

# 2. Goals

## Primary Goal

Enable AI agents to reliably access and use the Greens’ public data through MCP.

This requires:

* high-quality retrieval
* correct version handling
* semantically coherent chunks
* deterministic behavior

## Secondary Goals

* unified data model
* efficient token usage for LLMs
* deterministic build pipeline
* robust behavior for non-technical user queries

---

# 3. Non-Goals (MVP)

The MVP explicitly does NOT include:

* write operations
* authentication
* UI
* analytics (product-level)
* embedding-based semantic search
* multilingual support

---

# 4. Core Design Principles

## 4.1 Retrieval Before Reasoning

The LLM is not the search system.

The system must:

1. retrieve correct data
2. then allow the LLM to reason over it

---

## 4.2 Determinism

* Same input → same output
* Build pipeline must be reproducible

---

## 4.3 Strict Separation of Concerns

* Build pipeline ≠ runtime server
* Runtime must never perform scraping or ingestion

---

## 4.4 Semantic Integrity Over Uniformity

Chunking must prioritize meaning and coherence over fixed size.

---

## 4.5 All Corpus Content Is Untrusted

All document text is treated as **data only**, never as instructions.

---

# 5. Data Sources (MVP)

## 5.1 Party Programs

* GitHub repository
* Markdown format

## 5.2 Candidate Guide

* Google Sites (scraped)

## 5.3 Association Guide

* Google Sites (scraped)

---

# 6. Data Model

## 6.1 Source

```json
{
  "source_id": "string",
  "name": "string",
  "source_type": "github|scraped_site",
  "source_url": "string",
  "language": "fi"
}
```

---

## 6.2 Document

```json
{
  "document_id": "string",
  "source_id": "string",
  "title": "string",
  "tags": ["string"],
  "language": "fi"
}
```

---

## 6.3 Document Version

### Invariants (critical)

* A document may have multiple versions
* Exactly one version must have `is_current = true`
* `is_current` is derived, not manually assigned
* `valid_from` and `valid_to` must not overlap
* Versions are immutable snapshots

```json
{
  "version_id": "string",
  "document_id": "string",
  "version_label": "string",
  "status": "draft|published|superseded|archived",
  "published_at": "datetime",
  "valid_from": "datetime",
  "valid_to": "datetime|null",
  "is_current": true,
  "source_url": "string",
  "change_summary": "string"
}
```

---

## 6.4 Chunk

```json
{
  "chunk_id": "string",
  "document_id": "string",
  "version_id": "string",
  "heading_path": ["string"],
  "order": 0,
  "text": "string",
  "tokens_estimate": 0,
  "char_start": 0,
  "char_end": 0
}
```

> **Note:** `tags`, `answer_type`, and `audience` fields are out of scope for MVP. They were considered but not implemented — the corpus is too mixed to reliably classify chunks without manual annotation or an LLM enrichment pass.

---

# 7. Chunking Algorithm (CRITICAL)

## Goals

* Preserve semantic coherence
* Avoid breaking logical units

## Rules

* Target size: **300–700 tokens**
* Soft overflow allowed
* Maximum (hard split threshold): **~1200 tokens**
* Splitting priority:

  1. heading boundary
  2. paragraph boundary
  3. sentence boundary

## Overlap

* 1–2 sentences (~40–120 tokens)
* Required when splitting large sections

## Requirements

* Never split mid-sentence unless unavoidable
* Every chunk must include full `heading_path`
* Chunk order must be stable and deterministic

---

# 8. Index Files

Artifacts generated during build:

```
documents.jsonl
document_versions.jsonl
chunks.jsonl
manifest.json
validation_report.json
```

---

## 8.1 Finnish morphology handling

**aliases.json has been removed.** Static synonym maps require manual curation and introduce noise for general terms (e.g. `jäsenyys` matched unintentionally across all membership-related documents).

Instead, search uses:

1. **Snowball stemming** (Finnish) — every token is stemmed before query construction. `ydinvoimasta` → stem `ydinvoim` → FTS `ydinvoim*`. This covers all inflected forms without manual upkeep.
2. **Phrase search** — multi-word queries are sent both as a quoted phrase and as individual stemmed tokens. Phrase match scores higher via BM25.
3. **LLM retry** — if a query returns zero results, the MCP instructs the LLM to reformulate with different vocabulary and retry. Maximum 3 attempts per user question. This handles terminology mismatch (e.g. *Jäämeren rata* vs *Lapin käsivarren rautatie*) better than any static alias map can.

---

# 9. Search Strategy (MVP)

## Approach

Lexical retrieval via SQLite FTS5 + BM25 ranking.

## Stage 1: Query Construction

Every search query is processed by `pipeline/search.py → build_fts_query()`:

1. Tokens are stemmed with Snowball (Finnish model)
2. Each stemmed token becomes a prefix query: `stem*`
3. Multi-word queries also add the full original phrase in quotes: `"original phrase"`
4. Parts are joined with OR, duplicates removed

Example: `"Lapin käsivarren rautatie"` →
```
"Lapin käsivarren rautatie" OR lapin* OR käsivarr* OR rautati*
```

## Stage 2: Retrieval

FTS5 `MATCH` against `chunks_fts` content table. Fields indexed:

* chunk text (primary)
* heading_path (prepended to chunk text at index time)

Filter: `is_current = 1` — only chunks from the current document version.

## Stage 3: Ranking

BM25 via FTS5 built-in function. Score is a **negative float** — lower (more negative) = better match. Results are ordered ascending by score.

Example scores: `-5.2` (strong match), `-1.1` (weak match).

## Zero-result handling (MCP level)

If `search_chunks` returns zero results, the MCP server instructs the LLM to reformulate the query using different vocabulary and retry. Maximum **3 attempts** per user question. This is implemented in the MCP tool, not in `search.py`.

## Finnish Handling

* Snowball stemmer (Finnish) — covers inflected forms
* Prefix matching (`stem*`) — catches additional inflections the stemmer misses
* Phrase search — exact phrase gets BM25 boost over individual token matches
* No aliases.json — removed; static synonym maps caused noise and required manual upkeep

---

# 10. MCP Server Design

## Principles

* Resources = source of truth
* Tools = computation only
* Responses must be structured

---

## 10.1 Resources

Examples:

```
green://index/current
green://document/{document_id}
green://document/{document_id}/versions
green://document/{document_id}/version/{version_id}/toc
green://chunk/{chunk_id}
```

---

## 10.2 Tools

* `search_chunks` — primary search tool; returns ranked chunks with heading context
* `get_document` — fetch all chunks for a specific document by document_id
* `list_sources` — list all ingested sources with metadata

---

## Tool Requirements

Each tool MUST define:

* `inputSchema`
* `outputSchema`

Responses MUST include:

* `structuredContent` (machine-readable)
* optional human-readable text

---

## Example Tool Output

```json
{
  "results": [
    {
      "chunk_id": "a1b2c3d4",
      "title": "Ulko- ja turvallisuuspoliittinen ohjelma",
      "source_url": "https://...",
      "heading_path": ["Arktinen politiikka", "Jäämeren rata"],
      "score": -4.27,
      "text": "Vihreät kannattaa Jäämeren radan rakentamista..."
    }
  ],
  "query_used": "jäämeren rata",
  "attempt": 1
}
```

> **Note on score:** BM25 score is a **negative float**. Lower (more negative) = better match. Range varies by corpus; typical useful matches fall between -1 and -10.

---

# 11. Security

## Core Principle

All corpus content is **untrusted input**.

---

## Threats & Mitigations

### Prompt Injection (content)

* Treat all document text as data
* Never mix instructions with content

---

### Tool Injection

* No instructions embedded in results
* Strict separation: metadata vs text

---

### SSRF / Fetch Abuse

* No runtime fetching
* Source domains must be allowlisted

---

### Session Risks

* Prefer stateless HTTP
* Do not rely on session identity for auth

---

### Scope Control

* Minimal exposure
* future auth must follow least privilege

---

# 12. Observability

Minimum required:

* structured logs
* build reports
* error tracking
* latency metrics

---

# 13. Testing Strategy

## A. Unit Tests

* parsing
* chunking
* determinism

## B. Retrieval Tests

* gold dataset (30–100 queries)
* metrics:

  * Recall@k
  * MRR

## C. Logical/Causal Tests (CRITICAL)

Ensure retrieved data can answer:

* current vs historical queries
* policy vs process questions
* correct version resolution

---

## D. Adversarial Tests

* prompt injection
* ambiguous synonyms
* conflicting versions

---

## E. Contract Tests

* MCP schema compliance
* stable responses

---

# 14. Validation

## Levels

### Source

* content exists
* fetch success

### Document

* valid structure
* headings parsed

### Version

* valid date ranges
* no overlap

### Chunk

* size constraints
* heading path present

---

## Output

Each build must produce:

```json
validation_report.json
```

---

# 15. Versioning Strategy

Three layers:

1. Data schema version
2. Server version
3. MCP API version

Breaking changes require version bump.

---

# 16. Architecture Separation (CRITICAL)

## Build System

* ingestion
* normalization
* chunking
* indexing

## Runtime System

* serves data only

⚠️ Runtime must NEVER:

* scrape
* clone repos
* rebuild indexes

---

# 17. Technology Stack

## Recommended

* **Python** → ingestion, normalization, chunking
* **TypeScript (Node.js)** → MCP server

## Alternative

* all TypeScript if team prefers simplicity

---

# 18. Hosting Architecture

Planned (not yet confirmed):

* Container App (Azure or similar) → MCP server
* SQLite database bundled in the container image or served from Blob Storage
* ~20–30 users → practically free at this scale on any major cloud

No runtime ingestion.

---

# 19. Transport

* Development: stdio
* Production: Streamable HTTP

---

# 20. Performance Targets

For dataset up to:

* 50,000 chunks

Targets:

* p50 search < 200ms
* p95 search < 700ms
* chunk fetch < 100ms (warm)

---

# 21. Build Pipeline

Steps:

1. ingest sources
2. normalize content
3. detect versions
4. chunk
5. validate
6. build indexes
7. generate manifest
8. publish

---

# 22. Definition of Done

MVP is ready when:

* all sources ingest correctly
* validation passes with no critical errors
* chunking is deterministic
* retrieval quality meets threshold
* MCP server works locally and in Azure
* agents can complete end-to-end queries reliably

---

# 23. Key Risks

* Finnish retrieval quality
* scraping instability
* version conflicts
* prompt injection via content
* schema drift

---

# 24. Deliverables

```
/data
/indexes
/mcp-server
/scraper
/schemas
/docs
```

---

# END
