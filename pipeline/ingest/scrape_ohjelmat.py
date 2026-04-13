"""
scrape_ohjelmat.py — Phase 1b

Kaapii vihreat.fi/ohjelmat/-sivulta ohjelmat, joita ei löydy GitHubista.
Tallentaa HTML:n Raw/Ohjelmat/web/ -hakemistoon.

Idempotent: ohittaa jo kaapatut tiedostot (ellei --force).

Käyttö:
    python scrape_ohjelmat.py [--force] [--dry-run]
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

INDEX_URL = "https://www.vihreat.fi/ohjelmat/"

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_GITHUB_DIR = BASE_DIR / "Raw" / "Ohjelmat" / "github"
RAW_WEB_DIR = BASE_DIR / "Raw" / "Ohjelmat" / "web"
GITHUB_META_FILE = RAW_GITHUB_DIR / "_meta.json"
WEB_META_FILE = RAW_WEB_DIR / "_meta.json"

HEADERS = {
    "User-Agent": "GreenDataMCP/1.0 (tietoaineisto-tutkimus; ei-kaupallinen)",
}

THROTTLE_S = 1.5  # sekuntia pyyntöjen välillä


def slug_from_url(url: str) -> str:
    """Muodostaa tiedostonimen URL:sta."""
    path = urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    slug = parts[-1] if parts else "unknown"
    slug = re.sub(r"[^\w\-]", "_", slug)
    return slug[:80]  # max pituus


def github_slugs() -> set[str]:
    """Palauttaa GitHub-reposta löytyneiden tiedostojen slugit (tiedostonimet ilman .md)."""
    if not GITHUB_META_FILE.exists():
        return set()
    meta = json.loads(GITHUB_META_FILE.read_text(encoding="utf-8"))
    return {Path(name).stem.lower() for name in meta}


def discover_program_links(session: requests.Session) -> list[dict]:
    """
    Hakee vihreat.fi/ohjelmat/-indeksisivulta kaikki ohjelmalinkit.
    Palauttaa listan {"title": ..., "url": ...} -hakemistoja.
    """
    print(f"Haetaan indeksisivu: {INDEX_URL}")
    resp = session.get(INDEX_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    seen = set()

    # Ohjelmalinkit ovat tyypillisesti artikkeli- tai korttielementeissä
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full_url = urljoin(INDEX_URL, href)
        parsed = urlparse(full_url)

        # Vain vihreat.fi-sivuston ohjelmasivut
        if parsed.netloc not in ("www.vihreat.fi", "vihreat.fi"):
            continue
        if "/ohjelmat/" not in parsed.path:
            continue
        if parsed.path.rstrip("/") == urlparse(INDEX_URL).path.rstrip("/"):
            continue  # itse indeksisivu
        if full_url in seen:
            continue

        title = a.get_text(strip=True) or slug_from_url(full_url)
        links.append({"title": title, "url": full_url})
        seen.add(full_url)

    return links


def url_slug(url: str) -> str:
    """Poimii URL:sta ohjelman tunnisteen (viimeinen polkuosa)."""
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1].lower() if path else ""


def is_already_in_github(url: str, gh_slugs: set[str]) -> bool:
    """Vertaa URL-slugia GitHub-tiedostonimiin."""
    slug = url_slug(url)
    return slug in gh_slugs


def load_meta() -> dict:
    if WEB_META_FILE.exists():
        return json.loads(WEB_META_FILE.read_text(encoding="utf-8"))
    return {}


def save_meta(meta: dict) -> None:
    WEB_META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kaapii puuttuvat ohjelmat vihreat.fi:stä.")
    parser.add_argument("--force", action="store_true", help="Kaapaa uudelleen vaikka tiedosto on jo olemassa.")
    parser.add_argument("--dry-run", action="store_true", help="Näytä mitä kaapattaisiin, älä tallenna.")
    args = parser.parse_args()

    RAW_WEB_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    gh_slugs_set = github_slugs()
    meta = load_meta()

    try:
        links = discover_program_links(session)
    except requests.HTTPError as e:
        print(f"VIRHE: indeksisivun haku epäonnistui: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Löydettiin {len(links)} ohjelmalinkkiä indeksisivulta.")

    # Luokittele: GitHub vs. ei (vertaa URL-slugeja GitHub-tiedostonimiin)
    missing = []
    seen_slugs: set[str] = set()
    for link in links:
        slug = url_slug(link["url"])
        if slug in seen_slugs:
            continue  # sama ohjelma useilla linkeillä samalla sivulla
        seen_slugs.add(slug)
        in_gh = is_already_in_github(link["url"], gh_slugs_set)
        status = "github" if in_gh else "puuttuu"
        print(f"  [{status:7s}] {slug}  →  {link['url']}")
        if not in_gh:
            missing.append(link)

    print(f"\n{len(missing)} ohjelmaa puuttuu GitHubista — kaapataan nämä.")

    if args.dry_run:
        print("(--dry-run: ei tallenneta)")
        return

    fetched = 0
    skipped = 0
    errors = 0

    for link in missing:
        slug = slug_from_url(link["url"])
        dest = RAW_WEB_DIR / f"{slug}.html"

        if dest.exists() and not args.force:
            skipped += 1
            continue

        print(f"  Kaapataan: {slug} ...", end=" ")
        time.sleep(THROTTLE_S)
        try:
            resp = session.get(link["url"], headers=HEADERS, timeout=30)
            resp.raise_for_status()
            dest.write_text(resp.text, encoding="utf-8")
            meta[slug] = {
                "title": link["title"],
                "source_url": link["url"],
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "http_status": resp.status_code,
            }
            print("OK")
            fetched += 1
        except requests.HTTPError as e:
            print(f"VIRHE ({e})")
            meta[slug] = {
                "title": link["title"],
                "source_url": link["url"],
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "http_status": getattr(e.response, "status_code", None),
                "error": str(e),
            }
            errors += 1

    save_meta(meta)

    print()
    print(f"Valmis. Kaapattu: {fetched}, ohitettu: {skipped}, virheitä: {errors}")
    print(f"Metatiedot tallennettu: {WEB_META_FILE}")

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
