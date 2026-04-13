# MCP Server — Toteutussuunnitelma

Päivitetty: 2026-04-12
Perustuu: PRD.md v1.1, MCP best practices -dokumentit, käytännön testihavainnot

---

## Yleiskuva

MCP-palvelin on TypeScript/Node.js-prosessi joka tarjoaa Vihreiden asiakirjakorpuksen AI-agenteille MCP-protokollan (Model Context Protocol) kautta.

**Palvelin on täysin read-only.** Se ei koskaan scrape, nouda tai muokkaa lähdeaineistoa — ainoastaan hakee valmiiksi indeksoidusta SQLite-tietokannasta.

**Kohderyhmä:** ~20–30 käyttäjää. Pilvihosting käytännössä ilmainen tässä mittakaavassa.

---

## Arkkitehtuuriperiaatteet

### Vastuunjako (kriittinen)

| MCP-kerros omistaa | LLM-kerros omistaa |
|---|---|
| FTS5-haku ja tulosten normalisointi | Kyselyn tulkinta |
| BM25-pisteiden järjestys | Työkalun valinta |
| Syötteen validointi ja virheenkäsittely | Uudelleenmuotoilu nollatuloksella |
| Tietokantayhteys | Vastaustekstin muodostus |

### Zero-result retry (MCP-tason logiikka)

Jos `search_chunks` palauttaa 0 tulosta:
1. Palautetaan tyhjä tulos `attempt`-kentällä (`attempt: 1`)
2. Työkuvaus (`description`) ohjaa LLM:n muotoilemaan kyselyn uudelleen eri sanastolla
3. Maksimissaan **3 hakua** per käyttäjän kysymys
4. Jos kaikki 3 palauttavat 0 tulosta, LLM ilmoittaa ettei tietoa löydy

Tämä korvaa staattisen aliases.json-tiedoston: LLM osaa ennustaa sanaston vaihtoehtoja paremmin kuin mikään käsin koottu lista.

---

## Tekninen pino

| Komponentti | Teknologia |
|---|---|
| Palvelinruntime | Node.js (LTS) |
| Kieli | TypeScript (strict mode) |
| MCP SDK | `@modelcontextprotocol/sdk` |
| Skeemavalidointi | Zod |
| Tietokanta | SQLite (`better-sqlite3`) |
| Testaus | Vitest |
| Build | `tsc` |
| Transport (kehitys) | stdio |
| Transport (tuotanto) | Streamable HTTP |

---

## Tiedostorakenne

```
mcp-server/
  src/
    index.ts          — palvelimen entry point
    tools/
      search_chunks.ts
      get_document.ts
      list_sources.ts
    resources/
      index_resource.ts
      document_resource.ts
    prompts/
      hae_kanta.ts
    db.ts             — SQLite-yhteys (better-sqlite3)
    search.ts         — build_fts_query() TypeScript-portti
    types.ts          — jaetut tyypit
  system_prompt.md    — MCP-palvelimen käyttäjälle suunnattu kuvaus
  package.json
  tsconfig.json
  vitest.config.ts
```

---

## Vaihe 1 — Projektin alustus

### Tehtävät

- [ ] Luo `mcp-server/` hakemisto
- [ ] `npm init` ja asenna riippuvuudet:
  ```
  @modelcontextprotocol/sdk
  better-sqlite3
  zod
  ```
  Dev-riippuvuudet:
  ```
  typescript @types/node @types/better-sqlite3
  vitest
  ```
- [ ] Luo `tsconfig.json` (strict: true, moduleResolution: node, target: ES2022)
- [ ] Luo `src/index.ts` — tyhjä MCP-palvelin, stdio-transport
- [ ] Varmista että palvelin käynnistyy ja MCP Inspector tunnistaa sen

### Definition of Done

- `npm run build` exit 0
- MCP Inspector (`npx @modelcontextprotocol/inspector`) yhdistää palvelimeen
- Ei yhtään rekisteröityä työkalua vielä — pelkkä yhteys toimii

---

## Vaihe 2 — Tietokantayhteys (`db.ts`)

### Tehtävät

- [ ] Kirjoita `src/db.ts`:
  - `better-sqlite3` yhteys `data/green_data.db`:hen
  - Singleton-yhteys (ei uutta yhteyttä per kutsu)
  - `DB_PATH` ympäristömuuttujasta tai oletuspolusta
- [ ] Kirjoita `src/search.ts` — TypeScript-portti `pipeline/search.py`:n `build_fts_query()`:sta
  - Snowball-stemmaus: käytä `natural`-kirjastoa tai portaa logiikka suoraan
  - Vaihtoehto: kutsu Python-skriptiä child_process:na (ei suositella tuotantoon)
  - Paras vaihtoehto: reimplementoi stemming TypeScript:ssä käyttäen `snowball-stemmers` npm-pakettia

### Huomio stemmauksesta

`snowball-stemmers` npm-paketti tarjoaa Finnish-tuen. Varmista ennen käyttöä että se tuottaa samat vartalot kuin Python-versio muutamalla testitermillä.

### Definition of Done

- `db.ts` palauttaa yhteyden ilman virheitä
- `search.ts:build_fts_query("ydinvoimasta")` → `"ydinvoim*"`
- `search.ts:build_fts_query("Lapin käsivarsi")` → `'"Lapin käsivarsi" OR lapin OR käsivar*'` (lap < 4 merkkiä → ei tähteä)

---

## Vaihe 3 — Työkalu: `search_chunks`

Tämä on palvelimen tärkein työkalu.

### Skeema (Zod)

```typescript
const SearchChunksInput = z.object({
  query: z.string().min(1).describe(
    "Hakutermi tai -lause suomeksi. Esimerkki: 'ydinvoima', 'Nato-jäsenyys', 'perustulo'."
  ),
  limit: z.coerce.number().int().min(1).max(20).default(5).describe(
    "Tulosten maksimimäärä (1–20, oletus 5)."
  ),
  attempt: z.coerce.number().int().min(1).max(3).default(1).describe(
    "Hakuyrityksen numero (1–3). Lisää tähän 1 per uudelleenyritys."
  ),
});
```

### Työkuvaus

```
Hakee Vihreiden asiakirjakorpuksesta relevantit tekstikatkelmat (chunkit) FTS5-haulla.

Käytä tätä aina kun käyttäjä kysyy Vihreiden kannasta, ohjelmasta tai menettelystä.

Hakustrategia: Snowball-stemmaus + prefix-matching + fraasihaku. Suomen taivutusmuodot
tunnistetaan automaattisesti — hae perusmuodolla tai kysymyksen omilla sanoilla.

Jos tulos on tyhjä (0 chunkkia): muotoile hakutermi eri sanastolla ja kutsu uudelleen
attempt-arvolla 2 tai 3. Maksimissaan 3 yritystä per käyttäjän kysymys.

Jos kaikki 3 yritystä palauttavat 0 tulosta: ilmoita käyttäjälle ettei aiheesta löydy
tietoa korpuksesta — älä keksi tietoja.

Palauttaa: lista chunkeista kentillä chunk_id, title, source_url, heading_path,
score (negatiivinen float, pienempi = parempi osuvuus), text.
```

### Vastausrakenne

```typescript
{
  results: Array<{
    chunk_id: string;
    title: string;
    source_url: string;
    heading_path: string[];
    score: number;      // negatiivinen BM25-arvo, pienempi = parempi
    text: string;
  }>;
  query_used: string;   // FTS5-kysely sellaisena kuin se lähetettiin
  attempt: number;      // 1, 2 tai 3
}
```

### Virhetilanteet

- Tyhjä `query` → `isError: true`, viesti: "Hakutermi ei voi olla tyhjä."
- `attempt > 3` → `isError: true`, viesti: "Maksimiyritykset (3) käytetty. Kerro käyttäjälle ettei aiheesta löydy tietoa."
- Tietokantavirhe → `isError: true`, ei sisäisiä virheilmoituksia käyttäjälle

### Annotaatiot

```typescript
{ readOnlyHint: true, idempotentHint: true }
```

### Definition of Done

- Haku "ydinvoima" palauttaa ≥3 chunkkia
- Haku "Lapin käsivarren rautatie" palauttaa 0 tulosta (attempt 1)
- Haku "Jäämeren rata" attempt 2 palauttaa relevantteja chunkkeja
- `score`-kenttä on negatiivinen float
- MCP Inspector näyttää oikeat tulokset

---

## Vaihe 4 — Työkalu: `get_document`

### Skeema

```typescript
const GetDocumentInput = z.object({
  document_id: z.string().describe(
    "Dokumentin ID. Saadaan search_chunks-tuloksen chunk_id:stä tai green://index-resurssista."
  ),
});
```

### Työkuvaus

```
Palauttaa kaikki chunkit tietyltä dokumentilta järjestyksessä.

Käytä tätä kun haluat lukea koko ohjelman tai oppaan, ei vain yksittäisiä hakutuloksia.
document_id saadaan search_chunks-tuloksesta tai green://index-resurssista.

Palauttaa: dokumentin metatiedot + kaikki chunkit järjestyksessä.
```

### Definition of Done

- `get_document("tunnettu_id")` palauttaa chunkit oikeassa järjestyksessä
- `get_document("tuntematon_id")` palauttaa `isError: true` selkeällä viestillä

---

## Vaihe 5 — Työkalu: `list_sources`

### Skeema

```typescript
// Ei syöteparametreja
```

### Työkuvaus

```
Listaa kaikki korpuksen lähteet metatietoineen.

Käytä tätä selvittääksesi mitä aineistoa on saatavilla ennen hakua,
tai kun käyttäjä kysyy mistä tiedot on kerätty.

Palauttaa: lista lähteistä (source_id, name, source_type, document_count).
```

### Definition of Done

- Palauttaa 5 lähdettä (github, vihreat_fi, ehdokasopas, yhdistysopas, aineistopankki)
- Dokumenttimäärät vastaavat tietokannan sisältöä

---

## Vaihe 6 — Resurssit

### `green://index`

Sisältö: lista kaikista dokumenteista title + document_id + source_id.

Käyttötarkoitus: LLM tai käyttäjä voi tarkistaa mitä dokumentteja on saatavilla ennen `get_document`-kutsua.

```typescript
server.resource(
  "green://index",
  "Vihreiden korpuksen dokumenttiluettelo",
  async () => ({
    contents: [{ uri: "green://index", text: buildIndexText() }]
  })
);
```

### `green://document/{document_id}`

Sisältö: dokumentin metatiedot (title, source_url, published_at, is_current).

Käyttötarkoitus: nopea metatietojen tarkistus ennen koko dokumentin lataamista.

### Huomio resursseista

Resurssit ovat *application-controlled* — ne eivät ole LLM:n suoraan kutsuttavissa. Ne ovat viiteaineistoa jonka asiakas (esim. Claude Desktop) voi injektoida kontekstiin.

---

## Vaihe 7 — MCP Prompt: `hae_kanta`

Monikäyttöinen haku-workflow. Rekisteröidään MCP Promptiksi jotta käyttäjä voi kutsua sitä nimellä.

```typescript
server.prompt(
  "hae_kanta",
  "Hae Vihreiden kanta annettuun aiheeseen",
  { aihe: z.string().describe("Aihe tai kysymys suomeksi") },
  ({ aihe }) => ({
    messages: [{
      role: "user",
      content: {
        type: "text",
        text: `Hae Vihreiden kanta aiheeseen: "${aihe}"

Ohje:
1. Kutsu search_chunks hakutermillä joka kuvaa aihetta.
2. Jos tulos on tyhjä, muotoile hakutermi uudelleen eri sanastolla (attempt 2).
3. Muodosta vastaus löydetyistä chunkeista. Mainitse lähdeohjelma ja url.
4. Jos 3 hakua tuottaa 0 tulosta, kerro ettei aiheesta löydy tietoa korpuksesta.`
      }
    }]
  })
);
```

---

## Vaihe 8 — Järjestelmäprompt (`system_prompt.md`)

Tiedosto `mcp-server/system_prompt.md` on dokumentaatio MCP-palvelimen kuluttajille (esim. Claude Desktop -käyttäjille jotka konfiguroivat palvelimen).

```xml
<role>
Olet Vihreiden asiakirja-asiantuntija. Käytät Green Data MCP -palvelinta
hakemaan tietoja Vihreiden puolueohjelmista, ehdokasoppaasta ja yhdistysoppaasta.
</role>

<domain_context>
Korpus sisältää Vihreiden julkiset asiakirjat suomeksi: puolueohjelmat (GitHub + vihreat.fi),
ehdokasopas ja yhdistysopas (Google Sites). Kaikki tieto on suomeksi.
</domain_context>

<constraints>
- Vastaa aina suomeksi.
- Mainitse aina lähdeohjelma ja URL kun esität tietoja.
- Jos tietoa ei löydy korpuksesta, sano se suoraan — älä keksi kantoja.
- Käytä search_chunks ensin. Jos saat 0 tulosta, yritä uudella hakutermillä (max 3 kertaa).
</constraints>

<tool_guidance>
Aloita aina search_chunks-kutsulla. Jos haluat koko dokumentin, käytä get_document.
Lähteiden lista: kutsu list_sources tai lue green://index.
</tool_guidance>
```

---

## Vaihe 9 — Transport: Streamable HTTP (tuotanto)

Kehityksessä palvelin käyttää stdio-transportia. Tuotantoa varten lisätään HTTP-endpoint.

### Toteutus

```typescript
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import express from "express";

const app = express();
app.use(express.json());

app.post("/mcp", async (req, res) => {
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  await server.connect(transport);
  await transport.handleRequest(req, res, req.body);
});

app.listen(process.env.PORT ?? 3000);
```

Huomiot:
- Palvelin on stateless — ei sessiotilaa
- TLS terminoidaan infrastruktuuritasolla (Azure / Railway / Fly.io), ei Node.js-tasolla
- `PORT` ympäristömuuttujasta

---

## Vaihe 10 — Testaus

### Yksikkötestit (Vitest)

Tiedosto: `src/search.test.ts`

```typescript
describe("build_fts_query", () => {
  test("yksisanainen stemmataan", () => {
    expect(buildFtsQuery("ydinvoimasta")).toBe("ydinvoim*");
  });
  test("monisanainen saa fraasiosuuden", () => {
    const q = buildFtsQuery("Lapin käsivarsi");
    expect(q).toContain('"Lapin käsivarsi"');
    expect(q).toContain("lapin*");
  });
  test("lyhyt vartalo ei saa tähteä", () => {
    const q = buildFtsQuery("se");
    expect(q).not.toContain("*");
  });
});
```

### MCP Inspector -testi (manuaalinen, jokaisen vaiheen jälkeen)

```bash
npx @modelcontextprotocol/inspector node dist/index.js
```

Testattavat kyselyt:
1. `search_chunks("perustulo")` → ≥3 tulosta
2. `search_chunks("Lapin käsivarren rautatie", attempt=1)` → 0 tulosta
3. `search_chunks("Jäämeren rata", attempt=2)` → ≥1 tulos
4. `get_document("<tunnettu document_id>")` → kaikki chunkit järjestyksessä
5. `list_sources()` → 4 lähdettä

### Live-testi (Claude Desktop tai API) — pakollinen ennen julkaisua

Kyselyt suomeksi:
1. "Mitä Vihreät ajattelevat ydinvoimasta?" → vastauksessa lähdeviitteet
2. "Mitä mieltä vihreät ovat Lapin käsivarren rautatiestä?" → LLM kokeilee retry:tä
3. "Olen laittamassa kadunvarsikylttejä" → MCP ilmaisee ettei tarkkaa tietoa löydy

Kirjaa kaikki bugit Logbookiin.

---

## Vaihe 11 — Julkaisu (pilvi)

### Vaihtoehto A: Azure Container App (suositeltu)

```dockerfile
FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci --production
COPY dist/ ./dist/
COPY data/green_data.db ./data/
ENV PORT=3000
CMD ["node", "dist/index.js"]
```

- Skaalatuu nollaan kun ei käyttöä → käytännössä ilmainen ~20 käyttäjälle
- SQLite bundlataan imagen sisään (ei erillistä Blob Storage -riippuvuutta MVP:ssä)
- TLS Azure terminoi automaattisesti

### Vaihtoehto B: Railway / Fly.io

Sama Dockerfile toimii. Ei Azure-tiliä tarvita.

### Päätös

Julkaisualusta päätetään ennen Vaihetta 9 — ei kriittinen ennen sitä.

---

## Definition of Done — MCP-palvelin

- [ ] Kaikki 3 työkalua rekisteröity ja testattu MCP Inspectorilla
- [ ] Molemmat resurssit toimivat
- [ ] `hae_kanta`-prompt toimii
- [ ] Snowball-stemmaus toimii TypeScript-puolella (samat vartalot kuin Python)
- [ ] Zero-result retry toimii: attempt 1 → 0 tulosta → attempt 2 → tuloksia
- [ ] `npm run build` exit 0, `npm test` kaikki vihreänä
- [ ] Live-testi Claude Desktopilla tai API:lla (3 kyselyä, kirjattu Logbookiin)
- [ ] Julkaistu pilveen, URL toimii

---

## Riskit ja auki olevat päätökset

| Riski / päätös | Tila |
|---|---|
| Snowball Finnish TypeScript vs Python — sama vartalo? | Tarkistettava ennen Vaihetta 2 |
| Julkaisualusta (Azure vs Railway vs Fly.io) | Auki, päätettävä ennen Vaihetta 9 |
| SQLite bundled vs Blob Storage | Suositus: bundled MVP:ssä (yksinkertaisempi) |
| Aineistopankki-lähde (JS-rendering) | ~~Backlogissa~~ **Ratkaistu 2026-04-13** — plain requests toimi, 32 sivua kannassa |
| Prompti-injektio document-tekstistä | Lievennetty: corpus-teksti ei sekoitu ohjeisiin |
