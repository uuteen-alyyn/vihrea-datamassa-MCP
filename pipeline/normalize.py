"""
normalize.py — Phase 2

Muuntaa kaikki raakatiedostot puhtaaksi Markdown-muotoisiksi tiedostoiksi
Processed/-hakemistoon.

Lähdekohtainen logiikka:
  Raw/Ohjelmat/github/*.md      → Processed/Ohjelmat/<nimi>.md       (kevyt siivous)
  Raw/Ohjelmat/web/*.html       → Processed/Ohjelmat/<nimi>.md       (HTML → MD, vihreat.fi)
  Raw/Ehdokasopas/*.html        → Processed/Ehdokasopas/<nimi>.md    (HTML → MD, Google Sites)
  Raw/Yhdistysopas/*.html       → Processed/Yhdistysopas/<nimi>.md   (HTML → MD, Google Sites)
  Raw/Aineistopankki/*.html     → Processed/Aineistopankki/<nimi>.md (HTML → MD, Google Sites)

Idempotent: ohittaa jo normalisoidut tiedostot (ellei --force).

Käyttö:
    python normalize.py [--source github|ohjelmat|ehdokasopas|yhdistysopas|aineistopankki|kaikki] [--force]
"""

import argparse
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from markdownify import markdownify

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "Raw"
PROCESSED_DIR = BASE_DIR / "Processed"

# ---------------------------------------------------------------------------
# Apufunktiot
# ---------------------------------------------------------------------------

def clean_markdown(text: str) -> str:
    """Yleinen Markdown-siivous: ylimääräiset tyhjät rivit, välilyönnit jne."""
    # Korvaa Windows-rivinvaihdot
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Poista enemmän kuin 2 peräkkäistä tyhjää riviä
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Poista rivin lopun välilyönnit
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


def html_to_markdown(html_fragment: str) -> str:
    """Muuntaa HTML-fragmentin Markdowniksi."""
    return markdownify(
        html_fragment,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style", "nav", "footer", "header"],
    )


# ---------------------------------------------------------------------------
# GitHub Markdown -tiedostot
# ---------------------------------------------------------------------------

FRONT_MATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def normalize_github_md(src: Path, dest: Path, force: bool) -> str:
    """Kopioi GitHub MD -tiedoston kevyesti siivottuna."""
    if dest.exists() and not force:
        return "ohitettu"

    text = src.read_text(encoding="utf-8")

    # Poista YAML front matter jos on
    text = FRONT_MATTER_RE.sub("", text)

    text = clean_markdown(text)
    if not text:
        return "tyhjä"

    dest.write_text(text, encoding="utf-8")
    return "ok"


# ---------------------------------------------------------------------------
# vihreat.fi HTML -sivut
# ---------------------------------------------------------------------------

def extract_vihreat_fi(soup: BeautifulSoup) -> str | None:
    """
    Poimii vihreat.fi-ohjelmasivulta otsikon ja pääsisällön.

    Sivustolla on kaksi rakennetta:
      - Vanha (Drupal): sisältö on .field-name-body -divissä, H1 erillisessä otsikkoelementissä
      - Uusi (WP visual editor): sisältö on .l-visual-editor -section-elementissä (sisältää otsikon)

    Palauttaa HTML-merkkijonon tai None jos sisältöä ei löydy.
    """
    # Vanha rakenne: .field-name-body
    body_div = soup.select_one(".field-name-body")
    if body_div:
        h1 = soup.find("h1")
        title_html = str(h1) if h1 else ""
        # Poista nested .field-name-body (Drupalen rakenne toistaa divin)
        for nested in body_div.find_all("div", class_="field-name-body"):
            nested.unwrap()
        return title_html + str(body_div)

    # Uusi rakenne: .l-visual-editor
    visual = soup.select_one(".l-visual-editor")
    if visual:
        return str(visual)

    return None


def normalize_vihreat_html(src: Path, dest: Path, force: bool) -> str:
    if dest.exists() and not force:
        return "ohitettu"

    soup = BeautifulSoup(src.read_text(encoding="utf-8"), "html.parser")
    html_content = extract_vihreat_fi(soup)

    if not html_content:
        return "ei sisältöä"

    md = html_to_markdown(html_content)
    md = clean_markdown(md)
    if not md:
        return "tyhjä"

    dest.write_text(md, encoding="utf-8")
    return "ok"


# ---------------------------------------------------------------------------
# Google Sites HTML -sivut
# ---------------------------------------------------------------------------

def extract_google_sites(soup: BeautifulSoup) -> str | None:
    """
    Poimii Google Sites -sivulta otsikon ja pääsisällön.

    Google Sites -rakenne:
      - [role=main] sisältää sivun h1-otsikon
      - div.tyJCtd -elementit sisältävät sisältölohkoja;
        otetaan kaikki lohkot joissa on tekstiä
    """
    # Otsikko
    title_tag = soup.select_one("[role=main] h1")
    title_html = str(title_tag) if title_tag else ""

    # Sisältölohkot: kaikki .tyJCtd-divit, joissa on yli 50 merkkiä tekstiä,
    # järjestettynä dokumentin järjestyksessä (ei pisimmän mukaan)
    content_divs = soup.find_all("div", class_="tyJCtd")
    content_parts = []
    for div in content_divs:
        text = div.get_text(strip=True)
        if len(text) > 50:
            content_parts.append(str(div))

    if not content_parts:
        return None

    return title_html + "\n".join(content_parts)


def normalize_google_sites_html(src: Path, dest: Path, force: bool) -> str:
    if dest.exists() and not force:
        return "ohitettu"

    soup = BeautifulSoup(src.read_text(encoding="utf-8"), "html.parser")
    html_content = extract_google_sites(soup)

    if html_content:
        md = html_to_markdown(html_content)
        md = clean_markdown(md)
        if not md:
            return "tyhjä"
        dest.write_text(md, encoding="utf-8")
        return "ok"

    # Varapolku: käytä viereisenä tiedostona tallennettua Google Docs -tekstiä
    gdoc_txt = src.parent / (src.stem + "_gdoc.txt")
    if gdoc_txt.exists():
        text = gdoc_txt.read_text(encoding="utf-8-sig").strip()  # utf-8-sig poistaa BOM:in
        if not text:
            return "tyhjä (gdoc)"
        md = clean_markdown(text)
        dest.write_text(md, encoding="utf-8")
        return "ok (gdoc)"

    return "ei sisältöä"


# ---------------------------------------------------------------------------
# Päälogiikka
# ---------------------------------------------------------------------------

SOURCES = {
    "github": {
        "raw": RAW_DIR / "Ohjelmat" / "github",
        "processed": PROCESSED_DIR / "Ohjelmat",
        "pattern": "*.md",
        "fn": normalize_github_md,
    },
    "ohjelmat": {
        "raw": RAW_DIR / "Ohjelmat" / "web",
        "processed": PROCESSED_DIR / "Ohjelmat",
        "pattern": "*.html",
        "fn": normalize_vihreat_html,
    },
    "ehdokasopas": {
        "raw": RAW_DIR / "Ehdokasopas",
        "processed": PROCESSED_DIR / "Ehdokasopas",
        "pattern": "*.html",
        "fn": normalize_google_sites_html,
    },
    "yhdistysopas": {
        "raw": RAW_DIR / "Yhdistysopas",
        "processed": PROCESSED_DIR / "Yhdistysopas",
        "pattern": "*.html",
        "fn": normalize_google_sites_html,
    },
    "aineistopankki": {
        "raw": RAW_DIR / "Aineistopankki",
        "processed": PROCESSED_DIR / "Aineistopankki",
        "pattern": "*.html",
        "fn": normalize_google_sites_html,
    },
}


def run_source(name: str, cfg: dict, force: bool) -> None:
    raw_dir: Path = cfg["raw"]
    processed_dir: Path = cfg["processed"]
    pattern: str = cfg["pattern"]
    fn = cfg["fn"]

    processed_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(raw_dir.glob(pattern))
    if not files:
        print(f"  [{name}] Ei tiedostoja: {raw_dir / pattern}")
        return

    ok = skipped = empty = errors = 0

    for src in files:
        # Tulostiedoston nimi: aina .md
        dest = processed_dir / (src.stem + ".md")
        try:
            result = fn(src, dest, force)
        except Exception as e:
            print(f"  VIRHE {src.name}: {e}")
            errors += 1
            continue

        if result.startswith("ok"):
            ok += 1
        elif result == "ohitettu":
            skipped += 1
        else:
            print(f"  [{name}] {src.name}: {result}")
            empty += 1

    print(
        f"  [{name}] ok={ok}, ohitettu={skipped}, tyhjä/ei_sisältöä={empty}, virheitä={errors}"
        f"  ({len(files)} tiedostoa)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalisoi raakatiedostot Markdowniksi.")
    parser.add_argument(
        "--source",
        choices=list(SOURCES.keys()) + ["kaikki"],
        default="kaikki",
        help="Mikä lähde normalisoidaan (oletus: kaikki).",
    )
    parser.add_argument("--force", action="store_true", help="Ylikirjoita olemassa olevat tiedostot.")
    args = parser.parse_args()

    targets = list(SOURCES.keys()) if args.source == "kaikki" else [args.source]

    print(f"Normalisoidaan: {', '.join(targets)}")
    print()

    for name in targets:
        run_source(name, SOURCES[name], force=args.force)

    print()
    print("Valmis.")

    # Per-document normalize errors are logged inline by run_source().
    # They are NOT pipeline-fatal: a single malformed source HTML
    # shouldn't kill the chunk/build_db steps that follow. (The previous
    # `if any_errors` gate was always False — `any_errors` was a dead
    # local variable that run_source never propagated to.)


if __name__ == "__main__":
    main()
