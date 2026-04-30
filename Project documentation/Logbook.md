# Logbook

Append-only activity log. Add new entries at the bottom. Never remove existing entries.

Entry format:
```
## ENTRY TITLE YYYY-MM-DD HH:MM
[what was done]
[decisions made]
[test results]
[notes]
```

---

## PROJECT SETUP 2026-04-01

**What was done:**
- Created PRD.md with full product requirements
- Created BUILD_PIPELINE_PLAN.md with phased implementation plan
- Created CLAUDE.md with project-specific agent instructions
- Created Logbook.md (this file)
- Created BACKLOG.md

**Decisions made:**
- Alternative budget PDFs (vaihtoehtobudjetit) are out of scope for the pipeline. PDF conversion is too unreliable. The pre-processed Markdown files for 2024/2025 exist but are not part of the active pipeline.
- Party programs require two ingestion paths: GitHub (existing MD files) + vihreat.fi/ohjelmat/ scrape (for programs not in GitHub).
- Local SQLite with FTS5 chosen for the search database. No external server required.
- Python for the pipeline, TypeScript/Node.js for the future MCP server.
- All content is Finnish only. No multilingual support in MVP.

**Status:** Planning complete. No code written yet. Ready to start Phase 1.

## PHASE 2 NORMALIZATION 2026-04-01

**What was done:**
- Wrote pipeline/normalize.py with three extraction strategies:
  - GitHub MD: direct copy + front matter strip + whitespace cleanup
  - vihreat.fi HTML (old Drupal): H1 + .field-name-body via markdownify
  - vihreat.fi HTML (new WP visual editor): .l-visual-editor via markdownify
  - Google Sites HTML: [role=main] H1 + all .tyJCtd divs >50 chars via markdownify
- Ran normalize.py on all sources

**Results:**
- Processed/Ohjelmat/: 132 .md files (67 GitHub + 66 web - 1 skipped duplicate = 132 unique stems; some overlap in filenames possible)
- Processed/Ehdokasopas/: 9 .md files (1 page had no extractable content — embedded Google Doc)
- Processed/Yhdistysopas/: 14 .md files (1 page had no extractable content — embedded doc)

**Decisions made:**
- vihreat.fi has two HTML structures (old Drupal, new visual editor) — both handled
- Google Sites: .tyJCtd is the content container; pages with 0 such divs are embed-only pages, skipped
- markdownify heading_style=ATX, bullets="-" for consistent output

**Edge cases and surprises:**
- 12 vihreat.fi pages initially showed "ei sisältöä" — they use .l-visual-editor not .field-name-body (newer WP theme)
- Processed/Ohjelmat/ will contain some slug-variant duplicates (e.g. vihrea-energiavisio-2035 from web and vihreiden-energiavisio-2035 from GitHub) — deduplication deferred to DB phase

## PHASE 1 INGESTION 2026-04-01

**What was done:**
- Created full directory structure: Raw/Ohjelmat/github/, Raw/Ohjelmat/web/, Raw/Ehdokasopas/, Raw/Yhdistysopas/, Processed/ subdirs, pipeline/ingest/, data/
- Wrote pipeline/ingest/fetch_github.py — downloads all .md files from jannepeltola/vihreiden-ohjelma-alusta/vihreat-data/md/ via GitHub API
- Wrote pipeline/ingest/scrape_ohjelmat.py — scrapes vihreat.fi/ohjelmat/ and downloads programs not matched by GitHub URL slug
- Wrote pipeline/ingest/scrape_sites.py — crawls Google Sites for Ehdokasopas and Yhdistysopas
- Wrote requirements.txt

**Results:**
- Raw/Ohjelmat/github/: 67 .md files + _meta.json (59 with commit dates, 8 missing due to GitHub rate limit)
- Raw/Ohjelmat/web/: 66 .html files + _meta.json (3 pages returned 404 — genuinely removed content)
- Raw/Ehdokasopas/: 10 .html files + _meta.json
- Raw/Yhdistysopas/: 15 .html files + _meta.json

**Decisions made:**
- URL slug comparison (not title text) to match GitHub files against vihreat.fi links — link anchors say "Lue lisää", not titles
- 69 programs marked as "missing" from GitHub; some are slug-variant duplicates of GitHub files (e.g. vihrea-energiavisio-2035 vs vihreiden-energiavisio-2035). Deduplication deferred to normalize/DB phase.
- commit-info API failure (rate limit) is non-fatal — file is saved, meta records blob_sha and null committed_at; committed_at can be backfilled on next run
- GitHub personal access token ($GITHUB_TOKEN) recommended to avoid unauthenticated rate limit (60 req/h)

**Edge cases and surprises:**
- One "missing" link was an anchor fragment to `/vihrea-politiikka/ohjelmat/vihreiden-poliittinen-tavoiteohjelma-2019-2023#...` — a different path entirely, returned 404. That document exists in GitHub.
- Google Sites crawl found all pages correctly (10 + 15). No JavaScript rendering required — server-side HTML works with plain requests.

## PHASE 3 CHUNKKAUS 2026-04-12

**Mitä tehtiin:**
- Kirjoitettiin pipeline/chunk.py
- Toteutettu chunkkausalgoritmi: Markdown jäsennetään otsikko-ohjattuihin osioihin, kappaleet kerätään 300–700 tokenin chunkeiksi, ylivuodossa jaetaan kappale- tai lauserajalla, viimeinen kappale siirretään limittäiseksi seuraavaan chunkkiin
- chunk_id lasketaan sha256(chunk_text)[:8] — deterministinen
- heading_path rakennetaan otsikkopinosta (H1 > H2 > H3), lisätään chunkin tekstin eteen kontekstina
- Tokeniestimaatti: merkkimäärä / 4
- Validointi: varoitus jos chunk yli 1200 tokenia tai duplikaatti chunk_id

**Tulokset (--all --stats):**
- Tiedostoja: 157
- Chunkkeja: 3183
- Tokeneja yhteensä: ~1 238 924
- Keskiarvo: 389 tok/chunk, mediaani 388 tok/chunk
- Min: 8 tok, Max: 1020 tok (alle 1200-rajan, ei varoituksia)
- Yli 700 tok: 72 chunkkia (2,3 %) — lyhyitä ylivuotoja pitkistä bullet-listakappaleista
- Alle 300 tok: 1219 chunkkia (38,3 %) — odotettua, lyhyet aliosiot (lakiteksti, checklista, määritelmät)

**Päätökset:**
- Preamble (teksti ennen ensimmäistä otsikkoa) saa tyhjän heading_path:n — OK semanttisesti
- heading_prefix lisätään chunkin tekstin eteen muodossa "H1 > H2\n\n" — antaa hakukontekstin
- Alle 300 tokenin chunkkeja ei yhdistetä naapureihinsa: lyhyet osiot ovat usein semanttisesti itsenäisiä
- char_start/char_end ovat approksimaatioita — tarkka positiointi ei ole MVP:n kannalta kriittistä

**Reunatapaukset ja yllätykset:**
- argparse ei salli positional-argumenttia mutually exclusive -ryhmässä Python 3.13:ssa — korjattu poistamalla ryhmä
- Osa ohjelmista alkaa pitkällä johdantotekstillä ennen ensimmäistä H1:tä — preamble-käsittely toimii oikein

## PHASE 4 TIETOKANTA 2026-04-12

**Mitä tehtiin:**
- Kirjoitettiin pipeline/build_db.py
- Toteutettu skeema: sources, documents, document_versions, chunks, chunks_fts (FTS5)
- Metatiedot yhdistetään lähde-hakemistoittain: GitHub → blob URL + committed_at, vihreat.fi → scraped_at, Google Sites → scraped_at
- Otsikot poimitaan normalisoitujen Markdown-tiedostojen ensimmäisestä H1:stä
- FTS5-indeksi rakennettu rebuild-komennolla latauksen jälkeen
- Tarkistuskyselyt (--verify) ajettiin 5 suomenkielisellä haulla — kaikki palautti relevantteja tuloksia

**Tulokset:**
- sources: 4 riviä (github, vihreat_fi, ehdokasopas, yhdistysopas)
- documents: 155 riviä
- document_versions: 155 riviä
- chunks: 3156 riviä (chunk_count 3174, 18 duplikaattia ohitettu OR IGNORE)
- Ohitettu: 2 (vaihtoehtobudjetti2024.md, vaihtoehtobudjetti2025.md — ei metaa, out of scope)

**Päätökset:**
- 8 GitHub-tiedostoa puuttui _meta.json:sta kokonaan (rate limit -ongelma Phase 1:ssä). Ratkaisu: build_db.py rakentaa URL:n tiedostonimestä jos raw-tiedosto löytyy levyltä mutta ei metasta. published_at=None näille tiedostoille.
- document_id ja version_id lasketaan stable_id(source_url) — deterministinen, toistettava
- Vaihtoehtobudjetit ohitetaan odotetusti (ei metaa, out of scope)

**Reunatapaukset:**
- 18 OR IGNORE -ohitusta chunkeissa — pieniä duplikaatteja chunk_id-törmäyksistä (sha256[:8], marginaalinen riski). Ei vaadi toimenpiteitä MVP:ssä.

## PHASE 5 SUOMEN KIELEN KÄSITTELY 2026-04-12

**Mitä tehtiin:**
- Luotiin aliases.json: 15 aliasryhmää, ~60 termiä (joukkoliikenne, ilmastonmuutos, maahanmuutto, varhaiskasvatus, ikääntyneet, asuminen, uusiutuva energia, luonnonsuojelu, yhdenvertaisuus, esteettömyys, sosiaaliturva, verotus, liikenne, työllisyys, metsänsuojelu)
- Kirjoitettiin pipeline/search.py: bidirektionaalinen alias-indeksi + FTS5-hakufunktio
- Alias-laajennus on bidirektionaalinen: jokainen ryhmän termi aktivoi kaikki muut
- Testattiin 3 kollokviaalisella termillä: päivähoito, bussi, vanhukset — kaikki tuottivat relevantteja tuloksia laajennuksen ansiosta

**Päätökset:**
- Alias-indeksi rakennetaan muistiin käynnistyksen yhteydessä (ei tietokantaan) — yksinkertaisempi, riittää MVP:lle
- Moniosaisten fraasien ympärille lisätään lainausmerkit FTS5-kyselyssä ("julkinen liikenne")
- search.py toimii sekä kirjastona (MCP-palvelin) että komentorivityökaluna

## SEARCH.PY UUDELLEENKIRJOITUS 2026-04-12

**Mitä tehtiin:**
- Korvattu alias-laajennus Snowball-stemmauksella (snowballstemmer, suomi)
- Lisätty fraasihaku: monisanaiset haut lähetetään FTS5:lle myös lainausmerkeissä
- Poistettu aliases.json kokonaan
- Lisätty snowballstemmer>=2.2 requirements.txt:ään

**Hakustrategia nyt:**
1. Jokainen token stemmataan → haetaan prefix-matchingilla (stem*)
2. Monisanaiselle haulle lisätään koko fraasi lainausmerkeissä

**Testitulokset:**
- ydinvoima: 2 → 5 relevanttia tulosta
- Nato jäsenyys: yhdistyksen jäsenasiat poistuivat, kaikki 5 tulosta relevantteja
- Lapin käsivarren rautatie: rautatieohjelmat löytyvät, mutta Jäämeren rata ei vieläkään — H1-ongelma (terminologiamismatch) jää avoimeksi

**Avoin ongelma (H1, H2):**
Terminologiamismatch (Jäämeren rata vs. Lapin käsivarren rautatie) ei ratkea stemmauksella. Vaatisi pienen kohdennetun aliases-tiedoston tai muuta lähestymistapaa. Jätetään avoimeksi.

**Corpus-tarkistuksia ennen alias-valintojen tekemistä:**
- siirtolaisuus=0, pakolainen=0, hakkuu=0 — näitä ei jätetty pois vaan lisättiin aliasiksi (etsintä pääkäsitteelle silti toimii)
- Verotus=70, toimeentulo=69, varhaiskasvatus=57 — nämä ovat keskeisiä termejä, hyvä olla mukana

## UUSI LÄHDE: VIHREÄN EHDOKKAAN AINEISTOPANKKI 2026-04-13

**Mitä tehtiin:**
- Lisätty uusi lähde `aineistopankki` (https://sites.google.com/vihreat.fi/vihreanehdokkaanaineistopankki/)
- scrape_sites.py: lisätty `aineistopankki` SITES-dictiin, lisätty `fetch_embedded_gdocs`-funktio
- normalize.py: lisätty `aineistopankki` SOURCES-dictiin, lisätty Google Docs -varapolku `normalize_google_sites_html`-funktioon
- build_db.py: lisätty `AINEISTOPANKKI_META`, uusi lähde SOURCES_DATA:aan, Aineistopankki-haara `resolve_meta`-funktioon
- lähteet.txt: lisätty URL
- Kaapattu 86 sivua; normalisoitu 32 (19 tyJCtd + 13 Google Docs -tekstiä)
- Tietokanta rakennettu uudelleen: 187 dokumenttia, 3242 chunkkia

**Sivustoanalyysi:**
- Google Sites renderöi palvelinpuolella — plain requests toimii (backlogin Playwright-arvio oli virheellinen)
- 19 sivua: tyJCtd-divit — normaali Google Sites -teksti
- 16 sivua: Google Docs -upotukset (docs.google.com/document tai /presentation) — haettu `/export?format=txt`:llä
  - 13/16 onnistui, 3 epäonnistui (2 × 500 Server Error, 1 × 410 Gone)
- 6 sivua: YouTube-videoita — ohitettu (ei tekstiä)
- 45 sivua: Google Drive -tiedostoja (PDF/Slides preview) — ohitettu (PDF pipeline out of scope)

**Päätökset:**
- BOM-merkki (`\ufeff`) Google Docs -teksteissä poistetaan `utf-8-sig`-enkoodauksella normalisoidessa
- Google Docs -tekstitiedostot tallennetaan `<slug>_gdoc.txt`-nimellä Raw-hakemistoon
- Presentation-tyyppisistä Google Docs -upotuksista kokeillaan `/export/txt` — osalla toimii, osalla ei (presentaatiot voivat olla tyhjähköjä tekstinä)
- Google Drive file -upotukset (45 kpl) jätetään pois — ne ovat PDF:iä tai Slides-diaesityksiä, joiden tekstinpurku on out of scope MVP:ssä

**Reunatapaukset:**
- `ammattiliittojen-taloudellinen-tuki`: 410 Gone — asiakirja poistettu tai oikeudet muuttuneet
- `asiointipalvelun-ohje` ja `videoiden-tekstittäminen-someen`: 500 Server Error — väliaikainen Googlen ongelma tai pääsyrajoitus

---

## VAIHTOEHTOBUDJETIT LISÄTTY KANTAAN 2026-04-22

**Mitä tehtiin:**
- Lisätty `vaihtoehtobudjetti`-lähde `SOURCES_DATA`-listaan `build_db.py`:ssä
- Lisätty `Vaihtoehtobudjetit`-tapaus `resolve_meta()`-funktioon kovakoodatuilla metadatoilla per tiedosto
- Ajettu `python -m pipeline.build_db --force` — kanta rakennettu uudelleen
- Päivitetty `BUILD_PIPELINE_PLAN.md` (Phase 6), `BACKLOG.md` ja `lähteet.txt`

**Päätökset:**
- `source_url` per dokumentti on kanoninen vihreat.fi-sivu (ei PDF-linkki), koska MCP:n käyttäjät tarvitsevat selailtavan linkin
- `published_at` on arvioitu PDF-tiedostonimistä (marraskuu ko. vuoden edellisenä vuonna — vihreiden budjettiehdotukset julkaistaan syksyllä)
- Ei `_meta.json`-tiedostoa — metadata kovakoodattu suoraan `resolve_meta()`-funktioon, koska tiedostoja on vain 3 eikä scraperilla ole roolia

**Tulokset:**
- Dokumentteja ennen: 187 → jälkeen: 190 (+3)
- Chunkkeja ennen: 3156 → jälkeen: 3461 (+305)
- Ohitettu: 0
- Spot-check-haku "luonnonsuojelu vaihtoehtobudjetti" palautti kaikki kolme budjettia oikeilla URL-osoitteilla

---

## ENTRY PIPELINE FIX — OSITTAISET VIRHEET EIVÄT ENÄÄ TAPA AJOA 2026-04-30 14:30:00

Vihrea-MCP-päätiedostoprojektin Hetzner-deploy paljasti, että pipeline poistuu kesken ajon kun yksittäisiä lähteitä epäonnistuu — vaikka dataa olisi muuten haettu/normalisoitu/chunkkattu onnistuneesti.

**Konkreettinen toistunut tapaus:**
vihreat.fi/ohjelmat/-indeksisivu listaa kaksi vanhaa ohjelmaa, joiden URLit nykyään 404:
- `/ohjelmat/kohti-valikoivaa-asevelvollisuutta/`
- `/ohjelmat/eurooppa-ohjelma/`

`scrape_ohjelmat.py` käsitteli kummankin 404:n virheenä, kasvatti `errors`-laskuria ja kutsui `sys.exit(1)` lopussa. Pipeline-orkestraattorin `set -e` tappoi koko ajon → vaiheet 3–6 (scrape_sites, normalize, chunk, build_db) eivät päässeet käyntiin → `green_data.db` ei rakentunut → MCP:n `corpus_*`-työkalut palauttivat "tietokantavirhe".

**Korjaus — neljä paikkaa, sama kuvio:**

1. `pipeline/ingest/scrape_ohjelmat.py` — poistettu `if errors > 0: sys.exit(1)`. Yksittäiset 404:t kirjautuvat jo `Raw/Ohjelmat/web/_meta.json`:iin URL:n ja HTTP-statuksen kanssa. Indeksisivun kaatuminen earlier in main() on edelleen fatal (sen ilman emme voi enumeroida ollenkaan).

2. `pipeline/ingest/fetch_github.py` — sama kuvio, sama korjaus. GitHub-API:n listauskutsun epäonnistuminen on edelleen fatal; per-tiedosto 5xx tai 403 on warning-tason. Osittainen vaihe parempi kuin ei mitään — seuraava ajo paikkaa.

3. `pipeline/normalize.py` — `any_errors`-muuttuja oli kuollut (alustettu False, ei koskaan asetettu Trueksi koska `run_source` ei propagoi virheitä takaisin). `if any_errors: sys.exit(1)` -lohko ei siis koskaan ampunut; poistettu kommentilla varustettuna selittäväksi miksi.

4. `pipeline/chunk.py` — `if total_warnings: ... sys.exit(1)` muutettu pelkäksi tulostukseksi. Validointi-varoitukset (oversized chunk, empty chunk, duplikaatti chunk_id) ovat laatuasioita, eivät pipeline-fataaleja. Chunkit ovat silti käyttökelpoisia, FTS5-indeksointi käsittelee ne hyvin.

**Periaate:**
- Lähde-tason kaatuminen ennen kuin mitään dataa on saatu (esim. indeksisivu, listauskutsu): **fatal**, koska emme voi tietää mitä yrittää
- Per-dokumentti / per-tiedosto -virhe kun valtaosa onnistui: **warning**, kirjataan _meta.json:iin tai stdoutiin, ei taputeta
- Validointi-varoitukset valmiille chunkille: **info**, eivät edes warning-tasolla väärin

**Vaikutus:**
- Pipeline kestää vihreat.fi:n vanhentuneet linkit, GitHub:n hetkelliset 5xx:t, yksittäisten dokumenttien parse-virheet
- Operaattorille näkyvyys säilyy: virhelaskurit lopussa, detaljit `Raw/<lähde>/_meta.json`:issa
- Ei muutoksia onnistuneen ajon polkuun — vain epäonnistuneet ajot palautuvat siellä missä ne ennen kaatuivat

**Muutetut tiedostot:**
- `pipeline/ingest/scrape_ohjelmat.py`
- `pipeline/ingest/fetch_github.py`
- `pipeline/normalize.py`
- `pipeline/chunk.py`
- `Project documentation/Logbook.md` (tämä merkintä)

**Testit:**
Pipeline-skripteille ei ole yksikkötestejä. Tarkistus tapahtuu live-ajossa Hetzner-laatikolla `Vihreä-MCP`-umbrella-repon submodule-pin-bumpin jälkeen.

**Sivuhuomio Vihreille:**
vihreat.fi/ohjelmat/-sivulla on kaksi rikkinäistä linkkiä (`kohti-valikoivaa-asevelvollisuutta`, `eurooppa-ohjelma`). Lähetä joku korjaamaan ne sivuston puolella jos sopii.
