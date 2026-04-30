"""
fetch_github.py — Phase 1a

Lataa kaikki .md-tiedostot GitHub-reposta vihreat-data/md/ hakemistoon Raw/Ohjelmat/github/.
Tallentaa metatiedot (commit SHA, commit date) JSON-tiedostoon.

Idempotent: ohittaa jo ladatut tiedostot (ellei --force).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

REPO_OWNER = "jannepeltola"
REPO_NAME = "vihreiden-ohjelma-alusta"
REPO_PATH = "vihreat-data/md"
BRANCH = "main"

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "Raw" / "Ohjelmat" / "github"
META_FILE = RAW_DIR / "_meta.json"

GITHUB_API = "https://api.github.com"


def github_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def list_md_files(session: requests.Session) -> list[dict]:
    """Palauttaa listan .md-tiedostoista repossa (nimi, sha, download_url)."""
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{REPO_PATH}"
    params = {"ref": BRANCH}
    resp = session.get(url, headers=github_headers(), params=params, timeout=30)
    resp.raise_for_status()
    items = resp.json()
    return [
        {
            "name": item["name"],
            "sha": item["sha"],
            "download_url": item["download_url"],
            "path": item["path"],
        }
        for item in items
        if item["type"] == "file" and item["name"].endswith(".md")
    ]


def get_commit_info(session: requests.Session, file_path: str) -> dict:
    """Hakee viimeisimmän commit-tiedon tiedostolle."""
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/commits"
    params = {"path": file_path, "sha": BRANCH, "per_page": 1}
    resp = session.get(url, headers=github_headers(), params=params, timeout=30)
    resp.raise_for_status()
    commits = resp.json()
    if not commits:
        return {"commit_sha": None, "committed_at": None}
    commit = commits[0]
    return {
        "commit_sha": commit["sha"],
        "committed_at": commit["commit"]["committer"]["date"],
    }


def download_file(session: requests.Session, url: str) -> str:
    """Lataa tiedoston sisällön merkkijonona."""
    resp = session.get(url, headers=github_headers(), timeout=30)
    resp.raise_for_status()
    return resp.text


def load_meta() -> dict:
    if META_FILE.exists():
        return json.loads(META_FILE.read_text(encoding="utf-8"))
    return {}


def save_meta(meta: dict) -> None:
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lataa ohjelmat GitHubista.")
    parser.add_argument("--force", action="store_true", help="Lataa uudelleen vaikka tiedosto on jo olemassa.")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    meta = load_meta()

    print(f"Haetaan tiedostolista reposta {REPO_OWNER}/{REPO_NAME}/{REPO_PATH} ...")
    try:
        files = list_md_files(session)
    except requests.HTTPError as e:
        print(f"VIRHE: GitHub API -pyyntö epäonnistui: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Löydettiin {len(files)} .md-tiedostoa.")

    fetched = 0
    skipped = 0
    errors = 0

    for file_info in files:
        name = file_info["name"]
        dest = RAW_DIR / name

        if dest.exists() and not args.force:
            # Jos tiedosto on levyllä mutta puuttuu metasta, täytetään vain meta
            if name not in meta:
                print(f"  Meta puuttuu: {name} — haetaan commit-info ...", end=" ")
                commit_info: dict = {"commit_sha": None, "committed_at": None}
                try:
                    commit_info = get_commit_info(session, file_info["path"])
                except requests.HTTPError as e:
                    print(f"(commit-info epäonnistui: {e}) ", end="")
                meta[name] = {
                    "blob_sha": file_info["sha"],
                    "github_path": file_info["path"],
                    "commit_sha": commit_info["commit_sha"],
                    "committed_at": commit_info["committed_at"],
                }
                print("OK")
                time.sleep(0.5)
            else:
                skipped += 1
            continue

        print(f"  Ladataan: {name} ...", end=" ")
        try:
            content = download_file(session, file_info["download_url"])
            dest.write_text(content, encoding="utf-8")
        except requests.HTTPError as e:
            print(f"VIRHE tiedoston latauksessa ({e})")
            errors += 1
            continue

        # Commit-metatiedot — erillinen API-pyyntö, voi epäonnistua rate limitin takia
        commit_info: dict = {"commit_sha": None, "committed_at": None}
        try:
            commit_info = get_commit_info(session, file_info["path"])
        except requests.HTTPError as e:
            print(f"(commit-info epäonnistui: {e}) ", end="")

        meta[name] = {
            "blob_sha": file_info["sha"],
            "github_path": file_info["path"],
            "commit_sha": commit_info["commit_sha"],
            "committed_at": commit_info["committed_at"],
        }
        print("OK")
        fetched += 1
        # Varovaisuus: vältetään rate limit
        time.sleep(0.5)

    save_meta(meta)

    print()
    print(f"Valmis. Ladattu: {fetched}, ohitettu: {skipped}, virheitä: {errors}")
    print(f"Metatiedot tallennettu: {META_FILE}")

    # Per-file errors (transient GitHub 5xx, abuse-rate-limit 403 on a
    # single file, etc.) are recorded in _meta.json. They are NOT
    # pipeline-fatal: a partial fetch is better than no run at all, and
    # the next weekly run picks up whatever was missed. Only the listing
    # API failure earlier in main() is fatal — that means we can't even
    # enumerate the corpus.


if __name__ == "__main__":
    main()
