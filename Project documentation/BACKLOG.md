# BACKLOG

Persistent work queue. Surface outstanding items at the start of every session.

Format: group by priority. Add dates when items are created. Remove items only when explicitly confirmed done or dropped by the user.

---

## 🔴 Critical

*(nothing currently)*

---

## 🟡 Medium

- **[2026-04-12] Build pipeline — Definition of Done -tarkistus**
  Phases 1–5 valmis. Tarkista BUILD_PIPELINE_PLAN.md Definition of Done -lista ennen kuin siirrytään MCP-palvelimeen.
  Status: **Valmis (2026-04-13).** Kaikki 7 kohtaa läpäisty.

---

- **[2026-04-12] Uusi lähde: Vihreän ehdokkaan aineistopankki**
  URL: https://sites.google.com/vihreat.fi/vihreanehdokkaanaineistopankki/
  Status: **Valmis (2026-04-13).** 86 sivua kaapattu, 32 normalisoitu, integroitu kantaan. Playwright ei tarvittu — plain requests toimi. Playwright-arvio backlogissa oli virheellinen.

## 🟢 Low

- **[2026-04-01] Seed `aliases.json`**
  Create initial Finnish synonym map with ~10–20 high-value terms.
  Can be done any time before Phase 5.
  Status: Not started.

- **[2026-04-22] Vaihtoehtobudjetit — lisää kantaan (Phase 6)**
  Processed Markdown -tiedostot on lisätty kaikille kolmelle vuodelle (2024, 2025, 2026). Lisää `vaihtoehtobudjetti`-lähde `build_db.py`:hen, lisää `Vaihtoehtobudjetit`-tapaus `resolve_meta()`-funktioon kovakoodatuilla metadatoilla ja aja pipeline uudelleen.
  Katso suunnitelma: BUILD_PIPELINE_PLAN.md → Phase 6.
  Status: **Valmis (2026-04-22).** 190 dokumenttia, 3461 chunkkia, 0 ohitettu.
