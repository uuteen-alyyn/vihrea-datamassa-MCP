"""
chunk.py — Phase 3

Pilkkoo normalisoidut Markdown-tiedostot semanttisiksi tekstipaloiksi (chunkeiksi).

Algoritmi:
1. Jäsennä Markdown otsikkopuuraksi (heading-bounded sections)
2. Kävele osiot, kerää kappaleita kunnes tokeniestimaatti on 300–700
3. Ylivuodossa: jaa kappale- tai lauserajalla
4. Siirrä viimeinen kappale limittäiseksi (overlap) seuraavaan chunkkiin
5. Merkitse heading_path jokaiselle chunkille

Tokeniestimaatti: merkkimäärä / 4 (riittävä tarkkuus suomen kielelle)

chunk_id: sha256(chunk_text)[:8] — deterministinen

Käyttö kirjastona:
    from pipeline.chunk import chunk_file
    chunks = chunk_file(path_to_md_file)

Käyttö komentorivillä:
    python -m pipeline.chunk Processed/Ohjelmat/aluevaaliohjelma-2025.md
    python -m pipeline.chunk --all              # chunkkaa kaikki Processed/**/*.md
    python -m pipeline.chunk --stats            # tulosta tilastot ilman chunkkeja
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Vakiot
# ---------------------------------------------------------------------------

TOKENS_MIN = 300       # Alle tämän: yritetään yhdistää seuraavaan
TOKENS_MAX = 700       # Yli tämän: pakollinen jako
TOKENS_OVERLAP = 100   # ~1–2 lausetta, siirrytään seuraavaan chunkkiin

BASE_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = BASE_DIR / "Processed"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Apufunktiot
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    return len(text) // 4


def make_chunk_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def split_paragraphs(text: str) -> list[str]:
    """Jaa teksti kappaleisiin (tyhjä rivi erottimena)."""
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def split_sentences(text: str) -> list[str]:
    """
    Karkea lauseenjako suomen kielelle.
    Jakaa '. ', '! ', '? ' + iso kirjain tai listamerkin jälkeen.
    """
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÅ\-])", text)
    return [p.strip() for p in parts if p.strip()]


def heading_prefix(heading_path: list[str]) -> str:
    """Rakenna otsikkokonteksti chunkin eteen: 'Otsikko1 > Otsikko2\n\n'"""
    if not heading_path:
        return ""
    return " > ".join(heading_path) + "\n\n"


# ---------------------------------------------------------------------------
# Markdown-jäsentäjä
# ---------------------------------------------------------------------------

def parse_sections(md_text: str) -> list[dict]:
    """
    Jäsennä Markdown otsikko-ohjattuihin osioihin.

    Palauttaa listan sanakirjoja:
        heading_path : list[str]  — polku juuresta tähän otsikkoon
        level        : int        — otsikkotaso (0 = ennen ensimmäistä otsikkoa)
        content      : str        — sisältöteksti tämän otsikon alla (ei ala-otsikot)
        char_start   : int        — alkaa tässä kohdassa lähdetiedostossa
        char_end     : int        — päättyy tähän kohtaan lähdetiedostossa

    Huom: content sisältää VAIN tekstin suoraan tämän otsikon alla,
    ei ala-otsikkoja eikä niiden tekstiä.
    """
    headings = list(HEADING_RE.finditer(md_text))
    sections = []

    # Preamble: teksti ennen ensimmäistä otsikkoa
    first_pos = headings[0].start() if headings else len(md_text)
    preamble = md_text[:first_pos].strip()
    if preamble:
        sections.append({
            "heading_path": [],
            "level": 0,
            "content": preamble,
            "char_start": 0,
            "char_end": first_pos,
        })

    # Otsikkopino: [(level, text), ...]
    stack: list[tuple[int, str]] = []

    for idx, match in enumerate(headings):
        level = len(match.group(1))
        heading_text = match.group(2).strip()

        # Päivitä pino: poista saman tai syvemmän tason otsikot
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading_text))

        path = [h[1] for h in stack]

        # Osion alku: heti otsikon jälkeen (rivin loppu + rivinvaihto)
        content_start = match.end()

        # Osion loppu: seuraavan saman- tai ylempitasoisen otsikon alku,
        # tai seuraavan otsikon alku jos se on matalampi taso
        # → käytännössä: teksti jatkuu seuraavaan otsikkoon asti
        if idx + 1 < len(headings):
            content_end = headings[idx + 1].start()
        else:
            content_end = len(md_text)

        # Poista seuraava otsikko ja sen alla oleva teksti — ei, otetaan vain
        # teksti suoraan tämän otsikon alla (ennen ala-otsikkoja)
        # → löydä ensimmäinen ala-otsikko tässä alueessa
        sub_match = HEADING_RE.search(md_text, content_start, content_end)
        if sub_match:
            direct_end = sub_match.start()
        else:
            direct_end = content_end

        content = md_text[content_start:direct_end].strip()

        if content:
            sections.append({
                "heading_path": path,
                "level": level,
                "content": content,
                "char_start": content_start,
                "char_end": direct_end,
            })

    return sections


# ---------------------------------------------------------------------------
# Chunkkaus
# ---------------------------------------------------------------------------

def build_chunks_from_paragraphs(
    paragraphs: list[str],
    heading_path: list[str],
    start_order: int,
    base_char: int,
) -> list[dict]:
    """
    Muodosta chunkit kappalelistasta.

    Logiikka:
    - Kerää kappaleita kunnes tokeniestimaatti saavuttaa TOKENS_MAX
    - Ylivuodossa: emitoi chunk, siirrä viimeinen kappale limittäiseksi
    - Yksittäinen liian iso kappale: jaa lauserajalla
    """
    chunks: list[dict] = []
    prefix = heading_prefix(heading_path)
    prefix_tokens = estimate_tokens(prefix)
    order = start_order

    current: list[str] = []
    current_tokens = prefix_tokens

    def emit(parts: list[str], carry: str | None = None) -> None:
        nonlocal order, current, current_tokens
        if not parts:
            return
        body = "\n\n".join(parts)
        text = prefix + body if prefix else body
        chunks.append({
            "chunk_id": make_chunk_id(text),
            "heading_path": list(heading_path),
            "order": order,
            "text": text,
            "tokens_estimate": estimate_tokens(text),
            "char_start": base_char,   # approksimaatio
            "char_end": base_char + len(text),
        })
        order += 1
        # Aloita seuraava chunk limittäisellä kappaleella
        if carry:
            current = [carry]
            current_tokens = prefix_tokens + estimate_tokens(carry)
        else:
            current = []
            current_tokens = prefix_tokens

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        if para_tokens > TOKENS_MAX:
            # Kappale on itsessään liian suuri → jaa lauserajalla
            if current:
                carry = current[-1] if len(current) > 1 else None
                emit(current, carry)

            sentences = split_sentences(para)
            for sent in sentences:
                sent_tokens = estimate_tokens(sent)
                if current_tokens + sent_tokens > TOKENS_MAX and current:
                    carry = current[-1] if len(current) > 1 else None
                    emit(current, carry)
                current.append(sent)
                current_tokens += sent_tokens
        else:
            if current_tokens + para_tokens > TOKENS_MAX and current:
                carry = current[-1] if len(current) > 1 else None
                emit(current, carry)
            current.append(para)
            current_tokens += para_tokens

    # Jäljelle jäänyt sisältö
    if current:
        emit(current)

    return chunks


def chunk_section(section: dict, start_order: int) -> list[dict]:
    """Chunkkaa yksi Markdown-osio."""
    paragraphs = split_paragraphs(section["content"])
    if not paragraphs:
        return []
    return build_chunks_from_paragraphs(
        paragraphs,
        section["heading_path"],
        start_order,
        section["char_start"],
    )


def chunk_file(md_path: Path) -> list[dict]:
    """
    Chunkkaa yksi normalisoitu Markdown-tiedosto.

    Palauttaa listan chunkkeja. Jokaisessa chunkkissa:
        chunk_id        : str         — sha256[:8] chunkin tekstistä
        heading_path    : list[str]   — otsikkopolku
        order           : int         — järjestysnumero tiedostossa (0-indeksoitu)
        text            : str         — chunkin koko teksti (otsikkokonteksti + sisältö)
        tokens_estimate : int         — tokeniestimaatti
        char_start      : int         — approksimaattinen alkukohta lähdetiedostossa
        char_end        : int         — approksimaattinen loppukohta lähdetiedostossa
    """
    md_text = md_path.read_text(encoding="utf-8")
    sections = parse_sections(md_text)

    all_chunks: list[dict] = []
    order = 0

    for section in sections:
        new_chunks = chunk_section(section, order)
        all_chunks.extend(new_chunks)
        order += len(new_chunks)

    return all_chunks


# ---------------------------------------------------------------------------
# Validointi
# ---------------------------------------------------------------------------

def validate_chunks(chunks: list[dict], source_label: str) -> list[str]:
    """Tarkista chunkit — palauttaa lista varoituksista."""
    warnings = []
    ids = set()

    for i, c in enumerate(chunks):
        label = f"{source_label}[{i}]"

        if c["tokens_estimate"] > 1200:
            warnings.append(f"{label}: chunk ylittää 1200 tokenia ({c['tokens_estimate']})")

        if not c["heading_path"] and not c["text"].strip():
            warnings.append(f"{label}: tyhjä chunk ilman otsikkopolkua")

        if c["chunk_id"] in ids:
            warnings.append(f"{label}: duplikaatti chunk_id '{c['chunk_id']}'")
        ids.add(c["chunk_id"])

    return warnings


# ---------------------------------------------------------------------------
# Komentorivirajapinta
# ---------------------------------------------------------------------------

def print_chunks(chunks: list[dict], label: str, verbose: bool = False) -> None:
    print(f"\n=== {label} — {len(chunks)} chunkkia ===")
    for c in chunks:
        path_str = " > ".join(c["heading_path"]) if c["heading_path"] else "(johdanto)"
        print(f"  [{c['order']:3d}] {c['chunk_id']}  {c['tokens_estimate']:4d} tok  {path_str[:60]}")
        if verbose:
            preview = c["text"][:200].replace("\n", " ")
            print(f"        {preview}…")


def print_stats(all_stats: list[dict]) -> None:
    import statistics

    token_counts = [c["tokens_estimate"] for stats in all_stats for c in stats["chunks"]]
    if not token_counts:
        print("Ei chunkkeja.")
        return

    print(f"\n{'='*60}")
    print(f"YHTEENVETO")
    print(f"{'='*60}")
    print(f"Tiedostoja:      {len(all_stats)}")
    print(f"Chunkkeja:       {len(token_counts)}")
    print(f"Tokeneja yht.:   {sum(token_counts)}")
    print(f"Keskiarvo:       {statistics.mean(token_counts):.0f} tok/chunk")
    print(f"Mediaani:        {statistics.median(token_counts):.0f} tok/chunk")
    print(f"Min:             {min(token_counts)}")
    print(f"Max:             {max(token_counts)}")
    over = sum(1 for t in token_counts if t > TOKENS_MAX)
    under = sum(1 for t in token_counts if t < TOKENS_MIN)
    print(f"Yli {TOKENS_MAX} tok:     {over} ({100*over/len(token_counts):.1f} %)")
    print(f"Alle {TOKENS_MIN} tok:    {under} ({100*under/len(token_counts):.1f} %)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunkkaa Markdown-tiedostot.")
    parser.add_argument("files", nargs="*", metavar="FILE", help="Chunkkaa nämä tiedostot")
    parser.add_argument("--all", action="store_true", help="Chunkkaa kaikki Processed/**/*.md")
    parser.add_argument("--stats", action="store_true", help="Tulosta vain tilastot")
    parser.add_argument("--verbose", "-v", action="store_true", help="Näytä tekstikatkelmat")
    parser.add_argument("--json", action="store_true", help="Tulosta chunkit JSON-muodossa")
    args = parser.parse_args()

    if args.all:
        paths = sorted(PROCESSED_DIR.rglob("*.md"))
    elif args.files:
        paths = [Path(f) for f in args.files]
    else:
        parser.print_help()
        sys.exit(0)

    if not paths:
        print("Ei tiedostoja löydetty.", file=sys.stderr)
        sys.exit(1)

    all_stats = []
    total_warnings = []

    for path in paths:
        if not path.exists():
            print(f"VIRHE: tiedostoa ei löydy: {path}", file=sys.stderr)
            continue

        chunks = chunk_file(path)
        warnings = validate_chunks(chunks, path.name)
        total_warnings.extend(warnings)

        all_stats.append({"path": path, "chunks": chunks})

        if args.json:
            print(json.dumps(chunks, ensure_ascii=False, indent=2))
        elif not args.stats:
            print_chunks(chunks, path.name, verbose=args.verbose)

    if args.stats or len(paths) > 1:
        print_stats(all_stats)

    if total_warnings:
        print(f"\nVAROITUKSIA ({len(total_warnings)}):")
        for w in total_warnings:
            print(f"  ⚠  {w}")
        sys.exit(1)


if __name__ == "__main__":
    main()
