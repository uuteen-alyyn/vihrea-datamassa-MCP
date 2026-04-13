"""
search.py — Phase 5 (v2)

FTS5-hakutyökalu Snowball-stemmauksella ja fraasihaulla.

Hakustrategia:
1. Jokainen hakutermi stemmataan (Snowball, suomi) ja haetaan prefix-matchingilla
   → "ydinvoimasta" → stem "ydinvoim" → FTS "ydinvoim*"
   → löytää: ydinvoima, ydinvoiman, ydinvoimaa, ydinvoimalle, ...
2. Monisanaiselle haulle lisätään myös koko fraasi lainausmerkeissä
   → "Lapin käsivarsi" → FTS '"Lapin käsivarsi" OR lapin* OR käsivarr*'
   → täsmäosuma saa painoarvon, yksittäiset sanat laajentavat kattavuutta

aliases.json on poistettu käytöstä — stemmaus hoitaa morfologian,
terminologiset erikoistapaukset katetaan tarvittaessa suoraan hakukyselyssä.

Käyttö kirjastona (MCP-palvelin käyttää tätä):
    from pipeline.search import search
    results = search("ydinvoima", limit=10)

Käyttö komentorivillä:
    python -m pipeline.search "ydinvoima"
    python -m pipeline.search "Lapin käsivarren rautatie" --limit 5
    python -m pipeline.search "perustulo" --show-query
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import snowballstemmer

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "green_data.db"

MIN_STEM_LENGTH = 4  # lyhyemmät vartalot jätetään ilman prefix-tähtä

_STEMMER = snowballstemmer.stemmer("finnish")


# ---------------------------------------------------------------------------
# Kyselyjen rakentaminen
# ---------------------------------------------------------------------------

def stem_token(token: str) -> str:
    """Palauttaa Snowball-vartalon suomen kielellä."""
    return _STEMMER.stemWord(token.lower())


def build_fts_query(query: str) -> str:
    """
    Rakentaa FTS5-kyselymerkkijonon hakusyötteestä.

    Logiikka:
    - Jokainen token stemmataan ja haetaan prefix-matchingilla (stem*)
    - Lyhyet vartalot (< MIN_STEM_LENGTH) haetaan sellaisenaan ilman tähteä
    - Monisanaiselle haulle lisätään koko alkuperäinen fraasi lainausmerkeissä

    Esimerkki:
        "ydinvoimasta"          → 'ydinvoim*'
        "Lapin käsivarsi"       → '"Lapin käsivarsi" OR lapin* OR käsivarr*'
        "Nato jäsenyys"         → '"Nato jäsenyys" OR nato* OR jäsenyytt*'
    """
    tokens = query.strip().split()
    parts = []

    # Fraasihaku koko syötteelle jos useampi sana
    if len(tokens) > 1:
        parts.append(f'"{query.strip()}"')

    # Prefix-haku jokaiselle stemmatulle tokenille
    for token in tokens:
        clean = token.strip('",.')
        if not clean:
            continue
        stem = stem_token(clean)
        if len(stem) >= MIN_STEM_LENGTH:
            parts.append(f"{stem}*")
        else:
            parts.append(clean.lower())

    # Poista duplikaatit säilyttäen järjestys
    seen = set()
    unique = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    return " OR ".join(unique)


# ---------------------------------------------------------------------------
# Haku
# ---------------------------------------------------------------------------

SEARCH_SQL = """
    SELECT
        c.chunk_id,
        d.title,
        dv.source_url,
        c.heading_path,
        bm25(chunks_fts)  AS score,
        c.text
    FROM chunks_fts
    JOIN chunks c          ON c.chunk_id    = chunks_fts.chunk_id
    JOIN documents d       ON d.document_id = c.document_id
    JOIN document_versions dv ON dv.version_id = c.version_id
    WHERE chunks_fts MATCH ?
      AND dv.is_current = 1
    ORDER BY score
    LIMIT ?
"""


def search(
    query: str,
    limit: int = 10,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """
    Hae chunkkeja FTS5-indeksistä Snowball-stemmauksella.

    Parametrit:
        query   : hakutermi tai -lause suomeksi
        limit   : tulosten maksimimäärä (oletus 10)
        db_path : SQLite-tietokannan polku

    Palauttaa listan sanakirjoja:
        chunk_id    : str
        title       : str
        source_url  : str
        heading_path: list[str]
        score       : float   — BM25 (negatiivinen, pienempi = parempi)
        text        : str
    """
    fts_query = build_fts_query(query)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(SEARCH_SQL, (fts_query, limit)).fetchall()
    except sqlite3.OperationalError as e:
        raise ValueError(f"Hakuvirhe (FTS-kysely: {fts_query!r}): {e}") from e
    finally:
        conn.close()

    return [
        {
            "chunk_id": row["chunk_id"],
            "title": row["title"],
            "source_url": row["source_url"],
            "heading_path": json.loads(row["heading_path"]),
            "score": row["score"],
            "text": row["text"],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Komentorivirajapinta
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Hae Vihreiden datamassasta.")
    parser.add_argument("query", help="Hakutermi tai -lause suomeksi")
    parser.add_argument("--limit", "-n", type=int, default=5)
    parser.add_argument("--show-query", action="store_true", help="Näytä FTS-kysely")
    parser.add_argument("--json", action="store_true", help="Tulosta JSON-muodossa")
    args = parser.parse_args()

    if args.show_query:
        fts = build_fts_query(args.query)
        print(f"Alkuperäinen: {args.query!r}")
        print(f"FTS-kysely:   {fts!r}")
        print()

    try:
        results = search(args.query, limit=args.limit)
    except ValueError as e:
        print(f"VIRHE: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        print("Ei tuloksia.")
        return

    for i, r in enumerate(results, 1):
        path = " > ".join(r["heading_path"]) if r["heading_path"] else "(johdanto)"
        print(f"\n[{i}] {r['title']}")
        print(f"    {path[:70]}")
        print(f"    {r['source_url']}")
        print(f"    Pisteet: {r['score']:.3f}")
        preview = r["text"][:200].replace("\n", " ")
        print(f"    {preview}…")


if __name__ == "__main__":
    main()
