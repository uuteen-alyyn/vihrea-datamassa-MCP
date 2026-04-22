"""
build_db.py — Phase 4

Rakentaa SQLite-tietokannan (data/green_data.db) normalisoiduista Markdown-tiedostoista.

Vaiheet:
1. Lue metatiedot kaikista _meta.json-tiedostoista
2. Luo skeema (sources, documents, document_versions, chunks, chunks_fts)
3. Lataa jokainen Processed/**/*.md:
   a. Poimi otsikko ensimmäisestä H1:stä
   b. Chunkkaa chunk.py:n avulla
   c. Kirjoita tietokantaan
4. Rakenna FTS5-indeksi

Idempotent: jos tietokanta on jo olemassa, ohitetaan (ellei --force).

Käyttö:
    python -m pipeline.build_db
    python -m pipeline.build_db --force        # ylikirjoita olemassa oleva tietokanta
    python -m pipeline.build_db --verify       # aja vain tarkistuskyselyt
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

from pipeline.chunk import chunk_file

# ---------------------------------------------------------------------------
# Hakemistot ja tiedostot
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = BASE_DIR / "Processed"
RAW_DIR = BASE_DIR / "Raw"
DB_PATH = BASE_DIR / "data" / "green_data.db"

GITHUB_META = RAW_DIR / "Ohjelmat" / "github" / "_meta.json"
WEB_META = RAW_DIR / "Ohjelmat" / "web" / "_meta.json"
EHDOKASOPAS_META = RAW_DIR / "Ehdokasopas" / "_meta.json"
YHDISTYSOPAS_META = RAW_DIR / "Yhdistysopas" / "_meta.json"
AINEISTOPANKKI_META = RAW_DIR / "Aineistopankki" / "_meta.json"

GITHUB_REPO = "https://github.com/jannepeltola/vihreiden-ohjelma-alusta"
GITHUB_BLOB_BASE = f"{GITHUB_REPO}/blob/main"

H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)

# ---------------------------------------------------------------------------
# Skeema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'fi'
);

CREATE TABLE IF NOT EXISTS documents (
    document_id     TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    title           TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'fi'
);

CREATE TABLE IF NOT EXISTS document_versions (
    version_id      TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(document_id),
    version_label   TEXT NOT NULL,
    status          TEXT NOT NULL,
    published_at    TEXT,
    valid_from      TEXT NOT NULL,
    valid_to        TEXT,
    is_current      INTEGER NOT NULL CHECK(is_current IN (0, 1)),
    source_url      TEXT NOT NULL,
    change_summary  TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES documents(document_id),
    version_id      TEXT NOT NULL REFERENCES document_versions(version_id),
    heading_path    TEXT NOT NULL,
    chunk_order     INTEGER NOT NULL,
    text            TEXT NOT NULL,
    tokens_estimate INTEGER,
    char_start      INTEGER,
    char_end        INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id    UNINDEXED,
    document_id UNINDEXED,
    version_id  UNINDEXED,
    heading_path,
    text,
    content='chunks',
    content_rowid='rowid',
    tokenize='unicode61'
);
"""

# ---------------------------------------------------------------------------
# Apufunktiot
# ---------------------------------------------------------------------------

def stable_id(seed: str, length: int = 12) -> str:
    """Deterministinen ID sha256-hajautuksesta."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


def extract_title(md_text: str, fallback: str) -> str:
    """Poimii ensimmäisen H1-otsikon tai palauttaa fallback-arvon."""
    m = H1_RE.search(md_text)
    if m:
        return m.group(1).strip()
    return fallback


def load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# ---------------------------------------------------------------------------
# Metatietojen ratkaisu
# ---------------------------------------------------------------------------

def resolve_meta(
    processed_path: Path,
    gh_meta: dict,
    web_meta: dict,
    ehd_meta: dict,
    yhd_meta: dict,
    ain_meta: dict,
) -> dict | None:
    """
    Yhdistä normalisoitu tiedosto lähteen metatietoihin.

    Palauttaa sanakirjan:
        source_id   : str
        source_url  : str   — dokumentin alkuperäinen URL
        published_at: str | None
        valid_from  : str
        version_label: str
    tai None jos metatietoja ei löydy.
    """
    stem = processed_path.stem
    subdir = processed_path.parent.name  # "Ohjelmat", "Ehdokasopas", "Yhdistysopas"

    if subdir == "Ohjelmat":
        # Kokeile GitHub ensin
        gh_key = stem + ".md"
        if gh_key in gh_meta:
            entry = gh_meta[gh_key]
            github_path = entry.get("github_path", f"vihreat-data/md/{gh_key}")
            doc_url = f"{GITHUB_BLOB_BASE}/{github_path}"
            published = entry.get("committed_at")
            return {
                "source_id": "github",
                "source_url": doc_url,
                "published_at": published,
                "valid_from": published or "2024-01-01T00:00:00Z",
                "version_label": entry.get("commit_sha", "v1")[:8] if entry.get("commit_sha") else "v1",
            }

        # Tiedosto on levyllä GitHub-hakemistossa mutta puuttuu metasta
        # (8 tiedostoa joiden metatietojen haku epäonnistui rate limiteistä) —
        # rakennetaan URL tiedostonimestä
        github_raw_path = RAW_DIR / "Ohjelmat" / "github" / gh_key
        if github_raw_path.exists():
            github_path = f"vihreat-data/md/{gh_key}"
            doc_url = f"{GITHUB_BLOB_BASE}/{github_path}"
            return {
                "source_id": "github",
                "source_url": doc_url,
                "published_at": None,
                "valid_from": "2024-01-01T00:00:00Z",
                "version_label": "v1",
            }

        # Kokeile vihreat.fi web
        if stem in web_meta:
            entry = web_meta[stem]
            doc_url = entry.get("source_url", "https://www.vihreat.fi/ohjelmat/")
            scraped = entry.get("scraped_at")
            return {
                "source_id": "vihreat_fi",
                "source_url": doc_url,
                "published_at": None,
                "valid_from": scraped or "2026-01-01T00:00:00Z",
                "version_label": "v1",
            }

        return None  # Ei metatietoja — ohitetaan

    elif subdir == "Ehdokasopas":
        if stem in ehd_meta:
            entry = ehd_meta[stem]
            doc_url = entry.get("source_url", "https://sites.google.com/vihreat.fi/ehdokasopas-fi")
            scraped = entry.get("scraped_at")
            return {
                "source_id": "ehdokasopas",
                "source_url": doc_url,
                "published_at": None,
                "valid_from": scraped or "2026-01-01T00:00:00Z",
                "version_label": "v1",
            }
        return None

    elif subdir == "Yhdistysopas":
        if stem in yhd_meta:
            entry = yhd_meta[stem]
            doc_url = entry.get("source_url", "https://sites.google.com/vihreat.fi/vihreayhdistystieto/etusivu")
            scraped = entry.get("scraped_at")
            return {
                "source_id": "yhdistysopas",
                "source_url": doc_url,
                "published_at": None,
                "valid_from": scraped or "2026-01-01T00:00:00Z",
                "version_label": "v1",
            }
        return None

    elif subdir == "Aineistopankki":
        if stem in ain_meta:
            entry = ain_meta[stem]
            doc_url = entry.get("source_url", "https://sites.google.com/vihreat.fi/vihreanehdokkaanaineistopankki/")
            scraped = entry.get("scraped_at")
            return {
                "source_id": "aineistopankki",
                "source_url": doc_url,
                "published_at": None,
                "valid_from": scraped or "2026-01-01T00:00:00Z",
                "version_label": "v1",
            }
        return None

    elif subdir == "Vaihtoehtobudjetit":
        VAIHTOEHTOBUDJETTI_META = {
            "vaihtoehtobudjetti2024": {
                "source_url": "https://www.vihreat.fi/vaihtoehtobudjetti-2024/",
                "published_at": "2023-11-01T00:00:00Z",
            },
            "vaihtoehtobudjetti2025": {
                "source_url": "https://www.vihreat.fi/vaihtoehtobudjetti-2025/",
                "published_at": "2024-11-01T00:00:00Z",
            },
            "vaihtoehtobudjetti2026": {
                "source_url": "https://www.vihreat.fi/vaihtoehtobudjetti-2026/",
                "published_at": "2025-11-01T00:00:00Z",
            },
        }
        if stem in VAIHTOEHTOBUDJETTI_META:
            entry = VAIHTOEHTOBUDJETTI_META[stem]
            return {
                "source_id": "vaihtoehtobudjetti",
                "source_url": entry["source_url"],
                "published_at": entry["published_at"],
                "valid_from": entry["published_at"],
                "version_label": "v1",
            }
        return None

    return None


# ---------------------------------------------------------------------------
# Tietokantarakentaja
# ---------------------------------------------------------------------------

SOURCES_DATA = [
    {
        "source_id": "github",
        "name": "Vihreiden ohjelma-alusta (GitHub)",
        "source_type": "github",
        "source_url": GITHUB_REPO,
        "language": "fi",
    },
    {
        "source_id": "vihreat_fi",
        "name": "vihreat.fi/ohjelmat/",
        "source_type": "scraped_site",
        "source_url": "https://www.vihreat.fi/ohjelmat/",
        "language": "fi",
    },
    {
        "source_id": "ehdokasopas",
        "name": "Ehdokasopas (Google Sites)",
        "source_type": "scraped_site",
        "source_url": "https://sites.google.com/vihreat.fi/ehdokasopas-fi",
        "language": "fi",
    },
    {
        "source_id": "yhdistysopas",
        "name": "Yhdistysopas (Google Sites)",
        "source_type": "scraped_site",
        "source_url": "https://sites.google.com/vihreat.fi/vihreayhdistystieto/etusivu",
        "language": "fi",
    },
    {
        "source_id": "aineistopankki",
        "name": "Vihreän ehdokkaan aineistopankki (Google Sites)",
        "source_type": "scraped_site",
        "source_url": "https://sites.google.com/vihreat.fi/vihreanehdokkaanaineistopankki/",
        "language": "fi",
    },
    {
        "source_id": "vaihtoehtobudjetti",
        "name": "Vihreiden vaihtoehtobudjetit",
        "source_type": "manual",
        "source_url": "https://www.vihreat.fi/",
        "language": "fi",
    },
]


def build_database(force: bool = False) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists() and not force:
        print(f"Tietokanta on jo olemassa: {DB_PATH}")
        print("Käytä --force ylikirjoittaaksesi.")
        return

    if DB_PATH.exists() and force:
        DB_PATH.unlink()
        print(f"Poistettu vanha tietokanta: {DB_PATH}")

    # Lataa metatiedot
    gh_meta = load_json(GITHUB_META)
    web_meta = load_json(WEB_META)
    ehd_meta = load_json(EHDOKASOPAS_META)
    yhd_meta = load_json(YHDISTYSOPAS_META)
    ain_meta = load_json(AINEISTOPANKKI_META)

    print(f"GitHub meta: {len(gh_meta)} tiedostoa")
    print(f"Web meta:    {len(web_meta)} tiedostoa")
    print(f"Ehdokasopas meta: {len(ehd_meta)} sivua")
    print(f"Yhdistysopas meta: {len(yhd_meta)} sivua")
    print(f"Aineistopankki meta: {len(ain_meta)} sivua")
    print()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)

    # Lähteet
    conn.executemany(
        "INSERT OR IGNORE INTO sources VALUES (:source_id, :name, :source_type, :source_url, :language)",
        SOURCES_DATA,
    )
    conn.commit()
    print(f"Lähteet lisätty: {len(SOURCES_DATA)} kpl")

    # Käy läpi kaikki normalisoidut tiedostot
    processed_files = sorted(PROCESSED_DIR.rglob("*.md"))
    print(f"Normalisoituja tiedostoja: {len(processed_files)}")
    print()

    doc_count = 0
    chunk_count = 0
    skipped = 0

    for md_path in processed_files:
        meta = resolve_meta(md_path, gh_meta, web_meta, ehd_meta, yhd_meta, ain_meta)
        if meta is None:
            print(f"  OHITETAAN (ei meta): {md_path.relative_to(BASE_DIR)}")
            skipped += 1
            continue

        md_text = md_path.read_text(encoding="utf-8")
        title = extract_title(md_text, fallback=md_path.stem)

        document_id = stable_id(meta["source_url"])
        version_id = stable_id(meta["source_url"] + ":v1")

        # Dokumentti
        conn.execute(
            "INSERT OR IGNORE INTO documents (document_id, source_id, title, language) VALUES (?, ?, ?, 'fi')",
            (document_id, meta["source_id"], title),
        )

        # Dokumenttiversion
        conn.execute(
            """INSERT OR IGNORE INTO document_versions
               (version_id, document_id, version_label, status,
                published_at, valid_from, valid_to, is_current, source_url, change_summary)
               VALUES (?, ?, ?, 'published', ?, ?, NULL, 1, ?, NULL)""",
            (
                version_id,
                document_id,
                meta["version_label"],
                meta["published_at"],
                meta["valid_from"],
                meta["source_url"],
            ),
        )

        # Chunkit
        chunks = chunk_file(md_path)
        for c in chunks:
            conn.execute(
                """INSERT OR IGNORE INTO chunks
                   (chunk_id, document_id, version_id, heading_path,
                    chunk_order, text, tokens_estimate, char_start, char_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c["chunk_id"],
                    document_id,
                    version_id,
                    json.dumps(c["heading_path"], ensure_ascii=False),
                    c["order"],
                    c["text"],
                    c["tokens_estimate"],
                    c["char_start"],
                    c["char_end"],
                ),
            )

        chunk_count += len(chunks)
        doc_count += 1

        if doc_count % 20 == 0:
            print(f"  ... {doc_count} dokumenttia käsitelty")

    conn.commit()

    # Rakenna FTS5-indeksi
    print()
    print("Rakennetaan FTS5-indeksi ...")
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.commit()

    conn.close()

    print()
    print(f"Valmis.")
    print(f"  Dokumentteja:  {doc_count}")
    print(f"  Chunkkeja:     {chunk_count}")
    print(f"  Ohitettu:      {skipped}")
    print(f"  Tietokanta:    {DB_PATH}")


# ---------------------------------------------------------------------------
# Tarkistuskyselyt
# ---------------------------------------------------------------------------

VERIFY_QUERIES = [
    ("ilmastonmuutos", "ilmastokriisi"),
    ("maahanmuutto", "siirtolaisuus"),
    ("koulutus", "oppivelvollisuus"),
    ("terveydenhuolto", "sote"),
    ("talous", "budjetti"),
]


def verify_database() -> None:
    if not DB_PATH.exists():
        print(f"Tietokantaa ei löydy: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=== Perustilastot ===")
    for table in ("sources", "documents", "document_versions", "chunks"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} riviä")

    print()
    print("=== Testihaut ===")

    search_sql = """
        SELECT
            c.chunk_id,
            d.title,
            dv.source_url,
            c.heading_path,
            bm25(chunks_fts) AS score,
            substr(c.text, 1, 120) AS preview
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
        JOIN documents d ON d.document_id = c.document_id
        JOIN document_versions dv ON dv.version_id = c.version_id
        WHERE chunks_fts MATCH ?
          AND dv.is_current = 1
        ORDER BY score
        LIMIT 3
    """

    for terms in VERIFY_QUERIES:
        query = " OR ".join(terms)
        print(f"\n  Haku: {query!r}")
        rows = conn.execute(search_sql, (query,)).fetchall()
        if not rows:
            print("    (ei tuloksia)")
        for row in rows:
            path = json.loads(row["heading_path"])
            path_str = " > ".join(path) if path else "(johdanto)"
            print(f"    [{row['score']:.2f}] {row['title'][:50]} — {path_str[:40]}")
            print(f"           {row['preview'].replace(chr(10), ' ')}…")

    conn.close()


# ---------------------------------------------------------------------------
# Komentorivirajapinta
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Rakenna SQLite-tietokanta.")
    parser.add_argument("--force", action="store_true", help="Ylikirjoita olemassa oleva tietokanta.")
    parser.add_argument("--verify", action="store_true", help="Aja vain tarkistuskyselyt.")
    args = parser.parse_args()

    if args.verify:
        verify_database()
    else:
        build_database(force=args.force)


if __name__ == "__main__":
    main()
