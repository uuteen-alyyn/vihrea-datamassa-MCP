import { describe, test, expect } from "vitest";
import { buildFtsQuery, stripMarkdown } from "./search.js";

describe("buildFtsQuery", () => {
  test("yksisanainen hakutermi stemmataan ja saa prefix-tähden", () => {
    expect(buildFtsQuery("ydinvoimasta")).toBe("ydinvoim*");
  });

  test("monisanainen saa fraasiosuuden + yksittäiset termit", () => {
    // "lapin" → vartalo "lap" (3 merkkiä) → ei tähteä
    // "käsivarsi" → vartalo "käsivar" (7 merkkiä) → käsivar*
    expect(buildFtsQuery("Lapin käsivarsi")).toBe(
      '"Lapin käsivarsi" OR lapin OR käsivar*'
    );
  });

  test("lyhyt vartalo (< 4 merkkiä) ei saa prefix-tähteä", () => {
    const q = buildFtsQuery("se");
    expect(q).not.toContain("*");
    expect(q).toBe("se");
  });

  test("stemmaus toimii taivutetuille muodoille", () => {
    // "ilmastonmuutos" pysyy pitkänä → saa tähden
    expect(buildFtsQuery("ilmastonmuutos")).toBe("ilmastonmuutos*");
    // "koulutuksessa" → "koulutuks*"
    expect(buildFtsQuery("koulutuksessa")).toBe("koulutuks*");
  });

  test("duplikaatit poistetaan", () => {
    // Jos stemmaus tuottaa saman vartalon kahdelle sanalle, se esiintyy vain kerran
    const q = buildFtsQuery("koulu koulun");
    const parts = q.split(" OR ");
    const unique = new Set(parts);
    expect(unique.size).toBe(parts.length);
  });

  test("tyhjä syöte palauttaa tyhjän merkkijonon", () => {
    expect(buildFtsQuery("   ")).toBe("");
  });
});

describe("stripMarkdown", () => {
  test("muuntaa [label](url) muotoon 'label (url)'", () => {
    expect(stripMarkdown("Katso [perustulomalli](https://example.com/p)")).toBe(
      "Katso perustulomalli (https://example.com/p)"
    );
  });

  test("käsittelee linkin URL:ssa hash-ankkurin", () => {
    expect(
      stripMarkdown("[**Perustulomalli**](https://www.vihreat.fi/perustulomalli2014#paivittaa)")
    ).toBe("Perustulomalli (https://www.vihreat.fi/perustulomalli2014#paivittaa)");
  });

  test("strippaa **bold** -korostuksen", () => {
    expect(stripMarkdown("Tämä on **lihavoitu** sana")).toBe("Tämä on lihavoitu sana");
  });

  test("strippaa *italic* -korostuksen", () => {
    expect(stripMarkdown("Tämä on *kursivoitu* sana")).toBe("Tämä on kursivoitu sana");
  });

  test("käsittelee monta linkkiä samassa rivissä", () => {
    const input =
      "[**A**](https://a.example#x)\n\n[**B**](https://b.example#y)\n\n[**C**](https://c.example)";
    const expected =
      "A (https://a.example#x)\n\nB (https://b.example#y)\n\nC (https://c.example)";
    expect(stripMarkdown(input)).toBe(expected);
  });

  test("säilyttää newline:t ja muun tekstin sellaisenaan", () => {
    const input = "Otsikko\n\nEnsimmäinen kappale.\n\nToinen kappale.";
    expect(stripMarkdown(input)).toBe(input);
  });

  test("ei kaadu tyhjään merkkijonoon", () => {
    expect(stripMarkdown("")).toBe("");
  });

  test("ei riko URL:ja jotka eivät ole linkkisyntaksissa", () => {
    expect(stripMarkdown("Lähde: https://example.com/page#frag")).toBe(
      "Lähde: https://example.com/page#frag"
    );
  });

  test("ei tunnista yksittäistä * kursivoinniksi rivinvaihdon yli", () => {
    // Säilyttää asteriskit kun ne eivät muodosta paritettua syntaksia.
    const input = "* Bullet 1\n* Bullet 2";
    // MD_ITALIC_RE = /\*([^*\n]+)\*/g — ei matchaa rivinvaihdon yli, joten
    // bulletit pysyvät. (Jos haluttaisiin strippaa bulletit, lisättäisiin
    // erillinen sääntö, mutta nyt halutaan minimaalinen muutos.)
    expect(stripMarkdown(input)).toBe(input);
  });

  test("käsittelee linkin jossa on **bold** label-osana", () => {
    const input = "[**Otsikko**](https://example.com)";
    // Linkki muunnetaan ensin (label säilyy boldina), sitten bold strippaa.
    expect(stripMarkdown(input)).toBe("Otsikko (https://example.com)");
  });
});
