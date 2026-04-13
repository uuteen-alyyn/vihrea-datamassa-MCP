"""
scrape_sites.py — Phase 1c ja 1d

Kaapii Google Sites -sivustot:
  - Ehdokasopas:  https://sites.google.com/vihreat.fi/ehdokasopas-fi
  - Yhdistysopas: https://sites.google.com/vihreat.fi/vihreayhdistystieto/etusivu

Google Sites renderöi palvelinpuolella, joten requests + BeautifulSoup riittää.

Tallentaa sivut HTML-tiedostoina Raw/Ehdokasopas/ ja Raw/Yhdistysopas/ -hakemistoihin.

Idempotent: ohittaa jo kaapatut sivut (ellei --force).

Käyttö:
    python scrape_sites.py [--site ehdokasopas|yhdistysopas|molemmat] [--force] [--dry-run]
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

BASE_DIR = Path(__file__).resolve().parents[2]

SITES = {
    "ehdokasopas": {
        "start_url": "https://sites.google.com/vihreat.fi/ehdokasopas-fi",
        "raw_dir": BASE_DIR / "Raw" / "Ehdokasopas",
        "allowed_prefix": "/vihreat.fi/ehdokasopas-fi",
    },
    "yhdistysopas": {
        "start_url": "https://sites.google.com/vihreat.fi/vihreayhdistystieto/etusivu",
        "raw_dir": BASE_DIR / "Raw" / "Yhdistysopas",
        "allowed_prefix": "/vihreat.fi/vihreayhdistystieto",
    },
    "aineistopankki": {
        "start_url": "https://sites.google.com/vihreat.fi/vihreanehdokkaanaineistopankki/",
        "raw_dir": BASE_DIR / "Raw" / "Aineistopankki",
        "allowed_prefix": "/vihreat.fi/vihreanehdokkaanaineistopankki",
    },
}

GOOGLE_SITES_HOST = "sites.google.com"

HEADERS = {
    "User-Agent": "GreenDataMCP/1.0 (tietoaineisto-tutkimus; ei-kaupallinen)",
}

THROTTLE_S = 2.0


def slug_from_url(url: str) -> str:
    """Muodostaa tiedostonimen URL:sta."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    # Poista "vihreat.fi" ja sivuston nimi polusta
    meaningful = parts[2:] if len(parts) >= 2 else parts
    slug = "_".join(meaningful) if meaningful else "etusivu"
    slug = re.sub(r"[^\w\-]", "_", slug)
    return slug[:80]


def find_internal_links(soup: BeautifulSoup, base_url: str, allowed_prefix: str) -> list[str]:
    """Kerää sivulta kaikki saman sivuston sisäiset linkit."""
    found = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.netloc != GOOGLE_SITES_HOST:
            continue
        if not parsed.path.startswith(allowed_prefix):
            continue
        # Siisti URL: poista fragmentit ja query-parametrit
        clean = f"https://{parsed.netloc}{parsed.path}"
        found.append(clean)
    return found


def load_meta(raw_dir: Path) -> dict:
    meta_file = raw_dir / "_meta.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text(encoding="utf-8"))
    return {}


def save_meta(raw_dir: Path, meta: dict) -> None:
    meta_file = raw_dir / "_meta.json"
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def crawl_site(session: requests.Session, site_cfg: dict, force: bool, dry_run: bool) -> None:
    start_url: str = site_cfg["start_url"]
    raw_dir: Path = site_cfg["raw_dir"]
    allowed_prefix: str = site_cfg["allowed_prefix"]

    raw_dir.mkdir(parents=True, exist_ok=True)
    meta = load_meta(raw_dir)

    queue = [start_url]
    visited: set[str] = set()
    fetched = 0
    skipped = 0
    errors = 0

    print(f"\nAloitetaan kaappaus: {start_url}")

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        slug = slug_from_url(url)
        dest = raw_dir / f"{slug}.html"

        if dest.exists() and not force:
            skipped += 1
            # Silti parsitaan linkit, jotta löydetään kaapatuista sivuista uudet sivut
            soup = BeautifulSoup(dest.read_text(encoding="utf-8"), "html.parser")
            new_links = find_internal_links(soup, url, allowed_prefix)
            for link in new_links:
                if link not in visited:
                    queue.append(link)
            continue

        if dry_run:
            print(f"  [dry-run] {url}")
            fetched += 1
            continue

        print(f"  Kaapataan: {url} ...", end=" ")
        time.sleep(THROTTLE_S)
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            dest.write_text(resp.text, encoding="utf-8")
            meta[slug] = {
                "source_url": url,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "http_status": resp.status_code,
            }
            print("OK")
            fetched += 1

            # Etsi uudet linkit juuri haetulta sivulta
            soup = BeautifulSoup(resp.text, "html.parser")
            new_links = find_internal_links(soup, url, allowed_prefix)
            for link in new_links:
                if link not in visited:
                    queue.append(link)

        except requests.HTTPError as e:
            print(f"VIRHE ({e})")
            meta[slug] = {
                "source_url": url,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "http_status": getattr(e.response, "status_code", None),
                "error": str(e),
            }
            errors += 1

    save_meta(raw_dir, meta)

    print(f"  Valmis. Kaapattu: {fetched}, ohitettu: {skipped}, virheitä: {errors}, sivuja yhteensä: {len(visited)}")

    if errors > 0:
        print(f"  VAROITUS: {errors} virhettä kaappauksessa.", file=sys.stderr)


GDOC_EXPORT_THROTTLE_S = 1.5

GDOC_EXPORT_PATTERN = re.compile(
    r"https://docs\.google\.com/(document|presentation)/d/([a-zA-Z0-9_\-]+)"
)


def find_gdoc_url(html_path: Path) -> str | None:
    """Etsii sivulta ensimmäisen Google Docs -upotuksen URL:n (data-src tai src)."""
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    for iframe in soup.find_all("iframe"):
        src = iframe.get("data-src") or iframe.get("src") or ""
        m = GDOC_EXPORT_PATTERN.match(src)
        if m:
            return src
    return None


def gdoc_export_url(embed_url: str) -> str | None:
    """Muodostaa /export?format=txt -URL:n Google Docs -upotus-URL:sta."""
    m = GDOC_EXPORT_PATTERN.match(embed_url)
    if not m:
        return None
    doc_type, doc_id = m.group(1), m.group(2)
    if doc_type == "document":
        return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    elif doc_type == "presentation":
        return f"https://docs.google.com/presentation/d/{doc_id}/export/txt"
    return None


def fetch_embedded_gdocs(session: requests.Session, raw_dir: Path, force: bool) -> None:
    """
    Käy läpi kaikki hakemiston HTML-tiedostot, etsii Google Docs -upotukset
    ja hakee niiden tekstiversion (<slug>_gdoc.txt).

    Idempotent: ohittaa jo haetut tiedostot (ellei --force).
    """
    html_files = sorted(raw_dir.glob("*.html"))
    fetched = skipped = errors = 0

    print(f"\n  Haetaan Google Docs -upotukset ({len(html_files)} HTML-tiedostoa) ...")

    for html_path in html_files:
        gdoc_txt = raw_dir / (html_path.stem + "_gdoc.txt")

        if gdoc_txt.exists() and not force:
            skipped += 1
            continue

        embed_url = find_gdoc_url(html_path)
        if not embed_url:
            continue  # Ei Google Docs -upotusta

        export_url = gdoc_export_url(embed_url)
        if not export_url:
            continue

        print(f"    Haetaan GDoc: {html_path.name} ...", end=" ")
        time.sleep(GDOC_EXPORT_THROTTLE_S)
        try:
            resp = session.get(export_url, headers=HEADERS, timeout=30, allow_redirects=True)
            resp.raise_for_status()
            gdoc_txt.write_text(resp.text, encoding="utf-8")
            print("OK")
            fetched += 1
        except requests.HTTPError as e:
            print(f"VIRHE ({e})")
            errors += 1

    print(f"  GDoc-haku valmis. Haettu: {fetched}, ohitettu: {skipped}, virheitä: {errors}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Kaapii Ehdokasoppaan ja Yhdistysoppaan Google Sites -sivustot.")
    parser.add_argument(
        "--site",
        choices=["ehdokasopas", "yhdistysopas", "aineistopankki", "molemmat"],
        default="molemmat",
        help="Mikä sivusto kaapataan (oletus: molemmat = kaikki).",
    )
    parser.add_argument("--force", action="store_true", help="Kaapaa uudelleen vaikka tiedosto on jo olemassa.")
    parser.add_argument("--dry-run", action="store_true", help="Näytä mitä kaapattaisiin, älä tallenna.")
    args = parser.parse_args()

    session = requests.Session()

    targets = list(SITES.keys()) if args.site == "molemmat" else [args.site]

    for site_name in targets:
        print(f"\n=== {site_name.upper()} ===")
        crawl_site(session, SITES[site_name], force=args.force, dry_run=args.dry_run)
        if not args.dry_run:
            fetch_embedded_gdocs(session, SITES[site_name]["raw_dir"], force=args.force)

    print("\nKaikkien sivustojen kaappaus valmis.")


if __name__ == "__main__":
    main()
