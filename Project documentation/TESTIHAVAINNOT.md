# Testihavainnot

Havaintoja hakutestien perusteella. Kerätään ennen korjausten tekemistä.

Format: kukin havainto omana osionaan — otsikko, kuvaus, ehdotettu korjaus, prioriteetti.

---

## H1 — Terminologia-mismatch: Jäämeren rata vs. Lapin käsivarren rautatie

**Testitapaus:** "Mitä mieltä vihreät ovat Lapin käsivarren rautatiestä?"

**Havainto:** Haku ei löydä ulko- ja turvallisuuspoliittisen ohjelman kantaa, vaikka se on selkeästi kirjattu. Ohjelma käyttää termiä "Jäämeren rata" — käyttäjä hakee "Lapin käsivarren rautatie". Nämä tarkoittavat samaa asiaa mutta FTS ei yhdistä niitä.

**Ehdotettu korjaus:**
- **(A) aliases.json** — lisää ryhmä: `"jäämeren rata": ["Lapin käsivarren rautatie", "arktinen rata", "jäämerirata"]`
- **(B) Fraasihaun tuki search.py:ssä** — moniosainen syöte pitäisi hakea myös kokonaisena fraasina lainausmerkeissä, ei vain yksittäisinä sanoina
- **(C) Snowball-stemmaus** — normalisoisi taivutusmuodot (`rautatie → rata`), kattavin mutta eniten työtä

**Päätös:** Ratkaistaan MCP-tasolla — jos haku palauttaa 0 tulosta, LLM muotoilee kysymyksen uudelleen ja hakee uudelleen. Maksimissaan 3 hakua per kysymys. Ei tarvita staattisia aliaksia.

**Prioriteetti:** ~~Korkea~~ **SULJETTU** — ratkaistaan MCP-arkkitehtuurissa

---

## H2 — Alias-laajennus hajottaa moniosaisen haun liiaksi

**Testitapaus:** "Lapin käsivarsi rautatie" → laajennettu: `käsivarsi OR lapin OR rautatie`

**Havainto:** Moniosainen hakulause pilkotaan yksittäisiksi sanoiksi. `lapin` osuu sattumalta kaikkiin dokumentteihin joissa Lappi mainitaan — ei hakuaikomuksen kannalta relevanteista syistä. Tulokset hukkuvat kohinaan.

**Ehdotettu korjaus:** Hakutermi pitäisi lähettää FTS5:lle myös kokonaisena fraasina (`"Lapin käsivarsi rautatie"`), yksittäisten tokenien lisäksi tai sijaan. Fraasiosuma painotettaisiin korkeammalle kuin yksittäisten sanojen osuma.

**Päätös:** Osittain ratkaistu fraasihaullla (search.py v2). Lopullinen ratkaisu MCP-tasolla: LLM uudelleenmuotoilee jos 0 tulosta.

**Prioriteetti:** ~~Korkea~~ **SULJETTU**

---

## H3 — FTS5 ei tee suomen taivutusmuotojen normalisointia

**Testitapaus:** `rautatie` ei osu `rataan`, `rakentaa` ei osu `rakentamiseen`

**Havainto:** `unicode61`-tokenizer käsittelee jokaisen taivutusmuodon erillisenä tokenina. Suomi on agglutinoiva kieli — sama sana voi esiintyä kymmenissä muodoissa. Tämä heikentää haun kattavuutta merkittävästi.

**Ehdotettu korjaus:** Snowball-stemmer suomen kielelle (`PyStemmer` tai `nltk`). Voitaisiin lisätä joko FTS5:n tokenizeriksi tai esikäsittelyvaiheeksi ennen hakua. Ei vaadi skeemamuutoksia — hakutermit stemmattaisiin ennen FTS-kyselyä.

**Prioriteetti:** ~~Keskisuuri~~ **KORJATTU** — Snowball-stemmaus + prefix-matching otettu käyttöön search.py:ssä. aliases.json poistettu. ydinvoima: 2 → 5 tulosta. Nato-haku puhdistui täysin.

---

## H4 — Korpuksen sisältöaukko: kadunvarsikyltit

**Testitapaus:** "Olen laittamassa kadunvarsikylttejä, anna vinkkejä"

**Havainto:** Ehdokasopas käsittelee katukampanjointia mutta ei käsittele kadunvarsikylttejä, julisteita tai banderolleja lainkaan. Opas keskittyy esitteenjakoon ja ihmiskohtaamisiin. Hakutulos oli relevantti (katukampanja-osio löytyi), mutta varsinainen kysytty tieto puuttuu korpuksesta kokonaan.

**Ehdotettu korjaus:** Ei koodiongelma — sisältöaukko lähdeaineistossa. MCP-palvelimen pitää pystyä ilmaisemaan selkeästi "löysin aiheeseen liittyvää mutta en tarkalleen tätä". Ei vaadi pipeline-muutoksia.

**Päätös:** Lisätään aineistopankki korpukseen. Sivusto renderöi sisällön JavaScriptillä, joten nykyinen `scrape_sites.py` ei toimi — tarvitaan Playwright tai vastaava. Lisätty backlogiin.

**Prioriteetti:** Korkea — sisältää suoraan relevanttia materiaalia jota ei ole muualla korpuksessa

---

## H5 — Taivutusmuodot eivät osu hakuun: ydinvoima-tapaus

**Testitapaus:** "Mitä Vihreät ajattelevat ydinvoimasta?"

**Havainto:** FTS palauttaa vain 2 chunkkia sanalle "ydinvoima", vaikka raakadatassa on 18 osumaa. Syy: teksteissä sana esiintyy taivutusmuodoissa (`ydinvoiman`, `ydinvoimaa`, `ydinvoimalle`) jotka unicode61-tokenizer käsittelee eri tokeneina. `ydin*` palauttaisi 88 chunkkia. Sama ongelma kuin H3 mutta konkreettisesti todistettuna Vihreiden keskeisellä kannalla.

**Ehdotettu korjaus:** Snowball-stemmaus (H3) tai väliaikaisesti prefix-matching (`ydinvoima*`) search.py:ssä automaattisesti yksisanaisille hakutermeille.

**Prioriteetti:** ~~Korkea~~ **KORJATTU** — sama korjaus kuin H3.

---

## H6 — Alias-laajennus tuo epärelevantteja tuloksia yleissanoilla

**Testitapaus:** "Nato puolustusliitto jäsenyys" → `jäsenyys`-termi osuu yhdistyksen jäsenasioihin

**Havainto:** `jäsenyys` on yleinen sana joka esiintyy myös täysin eri konteksteissa (yhdistyksen jäsenluettelo). Tuloksissa 3 ja 4 oli epärelevantti yhdistysopas-sivu. Hakutermi ei kerro kontekstia, joten laajennus toimii liian laajasti.

**Ehdotettu korjaus:** Ei helppoa yleisratkaisua — osa yleissanoista on väistämättä monitulkintaisia. MCP-palvelimen LLM voi suodattaa epärelevantteja tuloksia vastausta muodostaessaan. Vaihtoehtoisesti `is_current`-suodatus voisi rajata lähdetyypeittäin jos käyttäjän konteksti on selkeä.

**Prioriteetti:** ~~Matala~~ **KORJATTU** — aliases.json poistettu, joten yleissanat eivät enää laajene hallitsemattomasti.

---
