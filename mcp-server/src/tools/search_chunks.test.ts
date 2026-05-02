import { describe, test, expect } from "vitest";
import { formatHeaderBlock, formatResultBlock } from "./search_chunks.js";
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

describe("formatHeaderBlock", () => {
  test("0 tulosta → ilmoittaa että ei löytynyt", () => {
    const out = formatHeaderBlock("perustulo", 1, 0);
    expect(out).toBe(`Korpuksesta ei löytynyt osumia haulle "perustulo".`);
  });

  test("0 tulosta + uudelleenyritys → mainitsee yritysnumeron", () => {
    const out = formatHeaderBlock("perustulo", 2, 0);
    expect(out).toBe(`Korpuksesta ei löytynyt osumia haulle "perustulo" (yritys 2/3).`);
  });

  test("1 tulos → singulaari 'osuma'", () => {
    const out = formatHeaderBlock("ydinvoima", 1, 1);
    expect(out).toContain("Löytyi 1 osuma haulle");
    expect(out).not.toContain("osumaa");
  });

  test("useita tuloksia → plural 'osumaa'", () => {
    expect(formatHeaderBlock("perustulo", 1, 8)).toContain("Löytyi 8 osumaa");
    expect(formatHeaderBlock("perustulo", 1, 10)).toContain("Löytyi 10 osumaa");
  });

  test("tulokset > 0 → ei mainitse yritysnumeroa edes uudelleenyrityksellä", () => {
    // Koska onnistunut tulos puhuu puolestaan; attempt-tieto on melua.
    const out = formatHeaderBlock("perustulo", 3, 5);
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
