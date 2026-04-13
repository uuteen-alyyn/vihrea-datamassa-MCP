import { describe, test, expect } from "vitest";
import { buildFtsQuery } from "./search.js";

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
