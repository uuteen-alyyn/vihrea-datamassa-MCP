import { describe, test, expect } from "vitest";
import {
  formatHeaderBlock,
  formatResultBlock,
  truncateChunkText,
} from "./search_chunks.js";
import type { ChunkResult } from "../types.js";

const sampleResult: ChunkResult = {
  chunk_id: "60d9ea0a",
  document_id: "a9ae35dd3fc7",
  title: "Vihreä perustulomalli",
  source_url: "https://www.vihreat.fi/ohjelmat/perustulomalli2014/",
  heading_path: ["Vihreä perustulomalli", "Sisällys:"],
  score: -5.61388812,
  text: "Vihreä perustulomalli > Sisällys:\n\nPerustulomalli on aika päivittää.",
};

describe("truncateChunkText", () => {
  test("alle rajan oleva teksti palautuu sellaisenaan", () => {
    const out = truncateChunkText("Lyhyt teksti");
    expect(out.text).toBe("Lyhyt teksti");
    expect(out.truncated).toBe(false);
  });

  test("tasan rajalla oleva teksti palautuu sellaisenaan", () => {
    const text = "a".repeat(800);
    const out = truncateChunkText(text);
    expect(out.text).toBe(text);
    expect(out.truncated).toBe(false);
  });

  test("rajan ylittävä teksti katkaistaan ja merkitään ellipsillä", () => {
    const text = "a".repeat(801);
    const out = truncateChunkText(text);
    expect(out.text).toBe("a".repeat(800) + "…");
    expect(out.truncated).toBe(true);
    // Stripped text on tasan 800 + ellipsi
    expect(out.text.length).toBe(801);
  });

  test("paljon rajan ylittävä teksti katkaistaan 800 merkkiin", () => {
    const text = "abc".repeat(1000); // 3000 chars
    const out = truncateChunkText(text);
    expect(out.text.endsWith("…")).toBe(true);
    expect(out.text.slice(0, -1).length).toBe(800);
    expect(out.truncated).toBe(true);
  });

  test("tyhjä teksti palautuu sellaisenaan", () => {
    expect(truncateChunkText("")).toEqual({ text: "", truncated: false });
  });
});

describe("formatHeaderBlock", () => {
  test("0 tulosta → ilmoittaa että ei löytynyt", () => {
    const out = formatHeaderBlock("perustulo", 1, 0, 0, 0, false);
    expect(out).toBe(`Korpuksesta ei löytynyt osumia haulle "perustulo".`);
  });

  test("0 tulosta + uudelleenyritys → mainitsee yritysnumeron", () => {
    const out = formatHeaderBlock("perustulo", 2, 0, 0, 0, false);
    expect(out).toBe(`Korpuksesta ei löytynyt osumia haulle "perustulo" (yritys 2/3).`);
  });

  test("1 tulos kaikki näytetään → singulaari 'osuma', ei mainitse kokorajaa", () => {
    const out = formatHeaderBlock("ydinvoima", 1, 1, 1, 0, false);
    expect(out).toContain("Löytyi 1 osuma haulle");
    expect(out).not.toContain("osumaa");
    expect(out).not.toContain("kokoraja");
  });

  test("kaikki tulokset näytetään → ei mainitse kokorajaa", () => {
    const out = formatHeaderBlock("perustulo", 1, 8, 8, 0, false);
    expect(out).toContain("Löytyi 8 osumaa");
    expect(out).not.toContain("kokoraja");
    expect(out).not.toContain("Näytetään");
  });

  test("dropped > 0 → mainitsee kokorajan ja kehottaa tarkennukseen", () => {
    const out = formatHeaderBlock("perustulo", 1, 8, 4, 4, false);
    expect(out).toContain("Löytyi 8 osumaa");
    expect(out).toContain("Näytetään 4 ensimmäistä");
    expect(out).toContain("kokoraja");
    expect(out).toContain("tarkennetulla hakutermillä");
  });

  test("anyTruncated → mainitsee chunk-tekstien katkaisun ja get_document:in", () => {
    const out = formatHeaderBlock("perustulo", 1, 4, 4, 0, true);
    expect(out).toContain("katkaistu");
    expect(out).toContain("corpus_get_document");
  });

  test("dropped > 0 JA anyTruncated → molemmat huomautukset näkyvät", () => {
    const out = formatHeaderBlock("perustulo", 1, 8, 4, 4, true);
    expect(out).toContain("Näytetään 4 ensimmäistä");
    expect(out).toContain("kokoraja");
    expect(out).toContain("katkaistu");
    expect(out).toContain("corpus_get_document");
  });

  test("tulokset > 0 → ei mainitse yritysnumeroa edes uudelleenyrityksellä", () => {
    // Koska onnistunut tulos puhuu puolestaan; attempt-tieto on melua.
    const out = formatHeaderBlock("perustulo", 3, 5, 5, 0, false);
    expect(out).not.toContain("yritys");
  });
});

describe("formatResultBlock", () => {
  test("sisältää tulosnumeron, otsikon, lähteen, polun, chunk-ID:n ja tekstin", () => {
    const out = formatResultBlock(sampleResult, 0, 8);
    expect(out).toContain("Tulos 1/8");
    expect(out).toContain("(osuvuus -5.61)");
    expect(out).toContain("Otsikko: Vihreä perustulomalli");
    expect(out).toContain("Lähde: https://www.vihreat.fi/ohjelmat/perustulomalli2014/");
    expect(out).toContain("Polku: Vihreä perustulomalli > Sisällys:");
    expect(out).toContain("Chunk ID: 60d9ea0a");
    expect(out).toContain("Perustulomalli on aika päivittää.");
  });

  test("ohittaa Polku-rivin kun heading_path on tyhjä", () => {
    const out = formatResultBlock({ ...sampleResult, heading_path: [] }, 0, 1);
    expect(out).not.toContain("Polku:");
    // Mutta sisältää silti muut metadatat
    expect(out).toContain("Otsikko:");
    expect(out).toContain("Chunk ID:");
  });

  test("pyöristää score:n kahteen desimaaliin", () => {
    const out = formatResultBlock(
      { ...sampleResult, score: -5.5321805 },
      0,
      8,
    );
    expect(out).toContain("(osuvuus -5.53)");
  });

  test("erottaa metadata- ja tekstilohkot tyhjällä rivillä", () => {
    const out = formatResultBlock(sampleResult, 0, 1);
    // Etsitään kaksoisrivinvaihto Chunk ID -rivin jälkeen mutta ennen tekstiä
    const idx = out.indexOf("Chunk ID:");
    const after = out.slice(idx);
    expect(after).toMatch(/Chunk ID:[^\n]*\n\nVihreä perustulomalli/);
  });

  test("monella heading_path-elementillä yhdistää '>' -merkillä", () => {
    const out = formatResultBlock(
      {
        ...sampleResult,
        heading_path: ["A", "B", "C"],
      },
      0,
      1,
    );
    expect(out).toContain("Polku: A > B > C");
  });

  test("tulosnumero on 1-indeksoitu (ei 0-indeksoitu)", () => {
    expect(formatResultBlock(sampleResult, 0, 3)).toContain("Tulos 1/3");
    expect(formatResultBlock(sampleResult, 1, 3)).toContain("Tulos 2/3");
    expect(formatResultBlock(sampleResult, 2, 3)).toContain("Tulos 3/3");
  });
});
