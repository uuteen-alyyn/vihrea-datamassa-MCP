# Build Pipeline Plan: Data Ingestion & Local Search Database

Version: 1.1
Date: 2026-04-01
Status: In progress

---

## Current State

| Source | Raw | Processed (MD) |
|---|---|---|
| Puolueen ohjelmat — GitHub | ✅ 67 .md files | ❌ Not done |
| Puolueen ohjelmat — vihreat.fi/ohjelmat/ | ✅ 66 .html files | ❌ Not done |
| Ehdokasopas (Google Sites) | ✅ 10 .html files | ❌ Not done |
| Yhdistysopas (Google Sites) | ✅ 15 .html files | ❌ Not done |

> **Note:** Alternative budget PDFs (vaihtoehtobudjetit) are out of scope. PDF conversion is too unreliable for MVP. The pre-processed Markdown files for 2024 and 2025 exist under `Processed/Vaihtoehtobudjetit/` but will not be ingested until a clean pipeline exists for them.

---

## Target State

A local SQLite database (`data/green_data.db`) that:

- [ ] Stores all source documents as clean Markdown
- [ ] Stores semantically chunked text with full heading context
- [ ] Links every chunk back to its source document and URL
- [ ] Supports full-text keyword search (SQLite FTS5)
- [ ] Supports version-aware queries (current vs. historical)

---

## Directory Structure

```
/
├── Project documentation/       # Plans, specs, logbook, backlog
├── Raw/                         # Unmodified source files (never edited)
│   ├── Ohjelmat/                # MD files from GitHub + HTML from vihreat.fi
│   ├── Ehdokasopas/             # Scraped HTML pages
│   └── Yhdistysopas/            # Scraped HTML pages
├── Processed/                   # Normalized Markdown (one file per document)
│   ├── Ohjelmat/
│   ├── Ehdokasopas/
│   └── Yhdistysopas/
├── pipeline/                    # Python pipeline scripts
│   ├── ingest/
│   │   ├── fetch_github.py      # Downloads MD files from GitHub repo
│   │   ├── scrape_ohjelmat.py   # Scrapes missing programs from vihreat.fi/ohjelmat/
│   │   └── scrape_sites.py      # Scrapes Google Sites (Ehdokasopas, Yhdistysopas)
│   ├── normalize.py             # Cleans and standardizes Markdown
│   ├── chunk.py                 # Splits documents into chunks
│   ├── build_db.py              # Loads chunks into SQLite
│   └── run_pipeline.py          # Orchestrates full pipeline run
├── data/
│   └── green_data.db            # SQLite database (pipeline output)
├── aliases.json                 # Finnish synonym/alias map
└── requirements.txt             # Python dependencies
```

---

## Phase 1 — Ingest all sources

**Execution order within this phase:**

1. Fetch party programs from GitHub
2. Scrape missing programs from vihreat.fi
3. Scrape Ehdokasopas
4. Scrape Yhdistysopas

---

### 1a. Fetch party programs from GitHub

Script: `pipeline/ingest/fetch_github.py`

The GitHub repository contains many programs in Markdown format but not all current programs are there. Fetch what is available.

- Use the GitHub API to list all `.md` files under `vihreat-data/md/`
- Download each file and save to `Raw/Ohjelmat/`
- Capture per file: filename, commit SHA, commit date (used as `published_at`)
- Log: file count, any fetch errors

Tasks:
- [x] Write `fetch_github.py`
- [x] Fetch all `.md` files from `vihreat-data/md/`
- [x] Save raw files to `Raw/Ohjelmat/github/`
- [x] Log commit date and SHA per file (8 files missing committed_at due to rate limit — pending backfill)

---

### 1b. Scrape missing programs from vihreat.fi/ohjelmat/

Script: `pipeline/ingest/scrape_ohjelmat.py`

The vihreat.fi website contains programs not available on GitHub (newer or supplementary ones). After fetching from GitHub, compare and scrape what is missing.

- Start from `https://www.vihreat.fi/ohjelmat/`
- Identify program pages not already fetched from GitHub (by title matching)
- Scrape each program page HTML
- Save to `Raw/Ohjelmat/web/`
- Log: URL, scrape timestamp, HTTP status

Tasks:
- [x] Write `scrape_ohjelmat.py`
- [x] Scrape index at vihreat.fi/ohjelmat/ to discover all program URLs
- [x] Compare against GitHub fetch — identify gaps (URL slug matching)
- [x] Scrape missing programs and save HTML to `Raw/Ohjelmat/web/`
- [x] Log all URLs and statuses (3 pages returned 404 — genuinely removed)

---

### 1c. Scrape Candidate Guide (Ehdokasopas)

Script: `pipeline/ingest/scrape_sites.py`

Google Sites renders server-side so standard `requests` + `BeautifulSoup` works.

- Start URL: `https://sites.google.com/vihreat.fi/ehdokasopas-fi`
- Follow all internal links to sub-pages
- Save each page as HTML to `Raw/Ehdokasopas/`
- Log: page URL, scrape timestamp, HTTP status

Tasks:
- [x] Write `scrape_sites.py` (shared between Ehdokasopas and Yhdistysopas)
- [x] Crawl all pages under Ehdokasopas
- [x] Save HTML files to `Raw/Ehdokasopas/`
- [x] Verify page count is reasonable (10 pages — looks complete)

---

### 1d. Scrape Association Guide (Yhdistysopas)

Same script as 1c, different starting URL.

- Start URL: `https://sites.google.com/vihreat.fi/vihreayhdistystieto/etusivu`

Tasks:
- [x] Crawl all pages under Yhdistysopas
- [x] Save HTML files to `Raw/Yhdistysopas/`
- [x] Verify page count is reasonable (15 pages — looks complete)

---

## Phase 2 — Normalize to Markdown

Script: `pipeline/normalize.py`

For each raw source, produce a single clean Markdown file in `Processed/`.

| Source type | Conversion | Notes |
|---|---|---|
| GitHub Markdown | Direct copy + light cleanup | Remove front matter artifacts |
| vihreat.fi HTML | `markdownify` | Strip nav, footer, sidebars |
| Google Sites HTML | `markdownify` | Strip nav, footer, sidebars |

**Normalization rules:**
- H1 = document title, H2+ = content sections
- Remove duplicate whitespace and encoding artifacts
- Preserve all list structures
- Strip navigation, page numbers, cookie banners, footers

Tasks:
- [x] Write `normalize.py`
- [x] Normalize all GitHub Markdown files → `Processed/Ohjelmat/` (67 files)
- [x] Normalize all vihreat.fi HTML files → `Processed/Ohjelmat/` (66 files)
- [x] Normalize Ehdokasopas HTML → `Processed/Ehdokasopas/` (9 files; 1 skipped — embed-only)
- [x] Normalize Yhdistysopas HTML → `Processed/Yhdistysopas/` (14 files; 1 skipped — embed-only)
- [x] Manually review a sample (3–5 files per source) for quality — spot-checked, output looks good

---

## Phase 3 — Chunk documents

Script: `pipeline/chunk.py`

**Algorithm:**

1. Parse Markdown into a tree of heading-bounded sections
2. Walk the tree, accumulating text until token estimate reaches 300–700 tokens
3. At overflow: split at heading > paragraph > sentence boundary
4. When splitting a large section, carry 1–2 sentence overlap into the next chunk
5. Record `heading_path` as an array (e.g. `["Ympäristöpolitiikka", "Luonnonsuojelu"]`)

**Token estimation:** character count / 4 (fast approximation, good enough for Finnish)

**Output per chunk:**
```json
{
  "chunk_id": "sha256-prefix-8chars",
  "document_id": "...",
  "version_id": "...",
  "heading_path": ["...", "..."],
  "order": 0,
  "text": "...",
  "tokens_estimate": 420,
  "char_start": 1240,
  "char_end": 2890
}
```

Tasks:
- [x] Write `chunk.py`
- [x] Verify chunking is deterministic (same input = same output)
- [x] Verify no chunk exceeds 1200 tokens (max 1020, no validation warnings)
- [x] Verify every chunk carries a `heading_path` (preamble chunks carry empty path)
- [x] Spot-check chunk boundaries for semantic coherence

---

## Phase 4 — Build SQLite database

Script: `pipeline/build_db.py`

### Schema

```sql
CREATE TABLE sources (
    source_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,   -- 'github' | 'scraped_site'
    source_url      TEXT NOT NULL,
    language        TEXT DEFAULT 'fi'
);

CREATE TABLE documents (
    document_id     TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    title           TEXT NOT NULL,
    language        TEXT DEFAULT 'fi'
);

CREATE TABLE document_versions (
    version_id      TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(document_id),
    version_label   TEXT NOT NULL,
    status          TEXT NOT NULL,   -- 'published' | 'superseded' | 'archived'
    published_at    TEXT,            -- ISO 8601
    valid_from      TEXT NOT NULL,
    valid_to        TEXT,            -- NULL = current
    is_current      INTEGER NOT NULL CHECK(is_current IN (0, 1)),
    source_url      TEXT NOT NULL,
    change_summary  TEXT
);

CREATE TABLE chunks (
    chunk_id        TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(document_id),
    version_id      TEXT NOT NULL REFERENCES document_versions(version_id),
    heading_path    TEXT NOT NULL,   -- JSON array stored as text
    chunk_order     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    tokens_estimate INTEGER,
    char_start      INTEGER,
    char_end        INTEGER
);

-- FTS5 full-text search index
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id UNINDEXED,
    document_id UNINDEXED,
    version_id UNINDEXED,
    heading_path,
    text,
    content='chunks',
    content_rowid='rowid',
    tokenize='unicode61'
);
```

### Search query pattern

```sql
SELECT
    c.chunk_id,
    c.text,
    c.heading_path,
    d.title,
    dv.source_url,
    dv.is_current,
    bm25(chunks_fts) AS score
FROM chunks_fts
JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
JOIN documents d ON d.document_id = c.document_id
JOIN document_versions dv ON dv.version_id = c.version_id
WHERE chunks_fts MATCH ?
  AND dv.is_current = 1
ORDER BY score
LIMIT 10;
```

Tasks:
- [x] Write `build_db.py`
- [x] Create schema and FTS5 index
- [x] Load all chunks from all sources
- [x] Verify row counts match expected document/chunk counts (155 docs, 3156 chunks)
- [x] Run 5 manual test queries and confirm relevant results (--verify, kaikki relevantteja)

---

## Phase 5 — Finnish language handling

The FTS5 `unicode61` tokenizer handles Finnish UTF-8 correctly out of the box.

### Alias expansion (`aliases.json`)

Before running an FTS query, expand search terms using the alias map:

```json
{
  "joukkoliikenne": ["julkinen liikenne", "bussi", "ratikka", "metro"],
  "ilmastonmuutos": ["ilmastokriisi", "ilmasto"],
  "maahanmuutto": ["siirtolaisuus", "maahanmuuttaja"]
}
```

Start small; grow the alias list from failed queries.

### Optional stemming (later)

The `Snowball` stemmer has a Finnish model. Can be added without schema changes — wrap FTS queries with stemmed term variants. Out of scope for initial build.

Tasks:
- [x] Create `aliases.json` with seed entries (15 aliasryhmää, ~60 termiä)
- [x] Implement alias expansion in `pipeline/search.py` (bidirektionaalinen indeksi)
- [x] Test alias expansion with 3 queries using colloquial Finnish terms (päivähoito, bussi, vanhukset — kaikki toimivat)

---

## Python Dependencies

```
# requirements.txt
requests>=2.31         # HTTP fetching
beautifulsoup4>=4.12   # HTML parsing
markdownify>=0.11      # HTML → Markdown
PyGithub>=1.59         # GitHub API (or use requests directly)
```

No external database server needed — SQLite is built into Python.

---

## Pipeline Run Order

```
run_pipeline.py
  1. ingest/fetch_github.py         → Raw/Ohjelmat/github/
  2. ingest/scrape_ohjelmat.py      → Raw/Ohjelmat/web/
  3. ingest/scrape_sites.py         → Raw/Ehdokasopas/, Raw/Yhdistysopas/
  4. normalize.py                   → Processed/**
  5. chunk.py                       → in-memory chunk objects
  6. build_db.py                    → data/green_data.db
```

All steps are idempotent: skip if output already exists, unless `--force` flag is passed.

---

## Definition of Done

- [x] All party programs fetched (GitHub + vihreat.fi gaps filled)
- [x] Ehdokasopas fully scraped and normalized to Markdown
- [x] Yhdistysopas fully scraped and normalized to Markdown
- [x] SQLite database created and populated
- [x] FTS5 search returns relevant results for 5 manual test queries in Finnish
- [x] Every chunk links back to a source URL
- [x] Chunking is deterministic (pipeline can be re-run and produce identical output)

---

## Next Phase (out of scope here)

Once this database exists, the MCP server reads from it at runtime — no scraping, no pipeline logic. Covered in PRD sections 10–12.
