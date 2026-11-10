/** The tag of a module made here rather than from a published book (DEL-226, `delve.domain.modules.HOMEBREW`). */
export const HOMEBREW = "homebrew";

export const isHomebrewTag = (tag: string) => tag.trim().toLowerCase() === HOMEBREW;

/** Whether the module's tags say it is homebrew. */
export const isHomebrew = (tags: readonly string[] | undefined) => (tags ?? []).some(isHomebrewTag);
