import { describe, expect, it } from "vitest";
import { translate, type Translate } from "./index";
import { classTerms, term } from "./terms";

const en: Translate = (key, vars) => translate("en", key, vars);
const nl: Translate = (key, vars) => translate("nl", key, vars);

describe("term", () => {
  it("names the PHB races and classes in Dutch, whatever their case and hyphens", () => {
    expect(term(nl, "race", "Half-Elf")).toBe("Halfelf");
    expect(term(nl, "race", "half elf")).toBe("Halfelf");
    expect(term(nl, "class", "Fighter")).toBe("Krijger");
    expect(term(nl, "gender", "female")).toBe("Vrouw");
    expect(term(nl, "alignment", "Lawful Good")).toBe("Wettig goed");
  });

  it("falls back to the value as written for a term it doesn't know", () => {
    expect(term(nl, "race", "Half-ogre")).toBe("Half-ogre");
    expect(term(nl, "class", "")).toBe("");
    expect(term(nl, "alignment", "?")).toBe("?");
    expect(term(nl, "gender", undefined as unknown as string)).toBe("");
    expect(classTerms(nl, null as unknown as string)).toBe("");
  });

  it("names them in English too", () => {
    expect(term(en, "class", "fighter")).toBe("Fighter");
    expect(term(en, "race", "HALFLING")).toBe("Halfling");
  });

  it("names each class of a multi-class", () => {
    expect(classTerms(nl, "Fighter/Thief")).toBe("Krijger/Dief");
    expect(classTerms(nl, "Fighter / Psionicist")).toBe("Krijger/Psionicist");
  });
});
