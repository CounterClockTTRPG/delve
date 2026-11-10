import * as Dialog from "@radix-ui/react-dialog";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { useEffect, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { useNavigate } from "react-router-dom";
import { listCampaigns, listModules, queryKeys } from "../api";
import { AREAS } from "../components/Nav";
import { useDebounce } from "../editor/useDebounce";
import { useT } from "../i18n";
import { LOOKS, useLook, type Look } from "../looks/looks";
import { listRulesets, rulesetKeys, searchRuleset } from "../rulesets/api";
import { entryHref, sectionLabel } from "../rulesets/parts";
import { listSettings, settingKeys } from "../setting/api";
import { GO_TO, SHORTCUTS } from "./shortcuts";

const LOOK_NAMES: Record<Look, string> = { delve: "look.delve", "gold-wood": "look.goldWood", "dark-dungeon": "look.darkDungeon" };

/** A key typed into a text field is the field's, apart from the shortcuts that say otherwise. */
const typing = { enableOnFormTags: false, enableOnContentEditable: false } as const;

/**
 * The keyboard's way around Delve, beside every screen: the shortcuts, their help (`?`), and for the owner the
 * command palette (Ctrl K, ⌘ K on a Mac) and the `g` sequences that go to an area. A seat gets the help and `/`.
 */
export default function Desktop({ owner }: { owner: boolean }) {
  const navigate = useNavigate();
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);

  useHotkeys("mod+k", () => setPalette((open) => !open), {
    enabled: owner,
    preventDefault: true,
    enableOnFormTags: true,
    enableOnContentEditable: true,
  });
  // By the character typed, whatever the keyboard's layout (on AZERTY "?" and "/" are other keys than on QWERTY).
  const byCharacter = { ...typing, useKey: true, ignoreModifiers: true, ignoreEventWhen: withCtrlOrAlt } as const;
  useHotkeys("?", () => setHelp(true), { ...byCharacter, preventDefault: true });
  useHotkeys("/", focusComposer, { ...byCharacter, preventDefault: () => composer() !== null });
  useGoTo(owner, navigate);

  return (
    <>
      {owner && <Palette open={palette} onOpenChange={setPalette} onHelp={() => setHelp(true)} />}
      <Help open={help} onOpenChange={setHelp} owner={owner} />
    </>
  );
}

function withCtrlOrAlt(e: KeyboardEvent): boolean {
  return e.ctrlKey || e.metaKey || e.altKey;
}

/** In a text field, a contenteditable (the module text editor) or Monaco, a key is text. */
function inField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * The `g` sequences: `g`, then an area's letter within a second. Kept here rather than in react-hotkeys-hook, whose
 * sequences registered together share one buffer of keys, so that only the first of them would ever match.
 */
function useGoTo(owner: boolean, navigate: (to: string) => void) {
  useEffect(() => {
    if (!owner) return;
    let armed = 0;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || withCtrlOrAlt(e) || inField(e.target)) return;
      const key = e.key.toLowerCase();
      if (armed && Date.now() - armed < 1000) {
        armed = 0;
        const to = GO_TO.find((s) => s.keys === `g>${key}`)?.to;
        if (to) {
          e.preventDefault();
          navigate(to);
        }
        return;
      }
      armed = key === "g" ? Date.now() : 0;
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [owner, navigate]);
}

function composer(): HTMLTextAreaElement | null {
  return document.querySelector<HTMLTextAreaElement>("[data-testid='composer'] textarea");
}

function focusComposer() {
  composer()?.focus();
}

function Palette({ open, onOpenChange, onHelp }: { open: boolean; onOpenChange: (open: boolean) => void; onHelp: () => void }) {
  const t = useT();
  const navigate = useNavigate();
  const [, setLook] = useLook();
  // Read when the palette opens, from the screens' own caches.
  const campaigns = useQuery({ queryKey: queryKeys.campaigns, queryFn: listCampaigns, enabled: open });
  const modules = useQuery({ queryKey: queryKeys.modules, queryFn: listModules, enabled: open });
  const settings = useQuery({ queryKey: settingKeys.list, queryFn: listSettings, enabled: open });
  // The rulesets' entries by name, asked from two characters typed (rulesets plan, Decision 10). The owner and
  // organisers alone have the palette, so the server's search may answer monsters too.
  const [search, setSearch] = useState("");
  useEffect(() => {
    if (!open) setSearch("");
  }, [open]);
  const query = useDebounce(search.trim(), 200);
  const rulesets = useQuery({ queryKey: rulesetKeys.list, queryFn: listRulesets, enabled: open });
  const lookups = query.length >= 2 ? (rulesets.data ?? []) : [];
  const found = useQueries({
    queries: lookups.map((r) => ({
      queryKey: rulesetKeys.search(r.id, query, null),
      queryFn: () => searchRuleset(r.id, query, null),
      enabled: open,
    })),
  });
  const hits = lookups.flatMap((r, i) => (found[i]?.data ?? []).map((hit) => ({ ruleset: r.id, ...hit })));
  const go = (to: string) => {
    onOpenChange(false);
    navigate(to);
  };
  const run = (action: () => void) => {
    onOpenChange(false);
    action();
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label={t("palette.title")}
      overlayClassName="dialog-overlay"
      contentClassName="palette"
      loop
    >
      <Command.Input placeholder={t("palette.placeholder")} value={search} onValueChange={setSearch} />
      <Command.List>
        <Command.Empty>{t("palette.none")}</Command.Empty>
        <Command.Group heading={t("palette.goTo")}>
          {AREAS.map((area) => (
            <Command.Item key={area.to} value={`area ${t(area.label)}`} onSelect={() => go(area.to)}>
              {t(area.label)}
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading={t("palette.actions")}>
          <Command.Item value={t("palette.newModule")} onSelect={() => go("/modules/new")}>
            {t("palette.newModule")}
          </Command.Item>
          <Command.Item value={t("palette.newCampaign")} onSelect={() => go("/campaigns#new-campaign")}>
            {t("palette.newCampaign")}
          </Command.Item>
          {LOOKS.map((look) => (
            <Command.Item key={look} value={`look ${t(LOOK_NAMES[look])}`} onSelect={() => run(() => setLook(look))}>
              {t("palette.look", { look: t(LOOK_NAMES[look]) })}
            </Command.Item>
          ))}
          <Command.Item value={t("palette.shortcuts")} onSelect={() => run(onHelp)}>
            {t("palette.shortcuts")}
          </Command.Item>
        </Command.Group>
        {(campaigns.data?.length ?? 0) > 0 && (
          <Command.Group heading={t("area.campaigns")}>
            {campaigns.data!.map((c) => [
              <Command.Item key={`play-${c.id}`} value={`play ${c.name} ${c.id}`} onSelect={() => go(`/play/${encodeURIComponent(c.id)}`)}>
                {t("palette.play", { name: c.name })}
              </Command.Item>,
              <Command.Item key={c.id} value={`campaign ${c.name} ${c.id}`} onSelect={() => go(`/campaigns/${encodeURIComponent(c.id)}`)}>
                {t("palette.campaign", { name: c.name })}
              </Command.Item>,
            ])}
          </Command.Group>
        )}
        {(modules.data?.length ?? 0) > 0 && (
          <Command.Group heading={t("area.modules")}>
            {modules.data!.map((m) => (
              <Command.Item key={m.id} value={`module ${m.title} ${m.id}`} onSelect={() => go(`/modules/${encodeURIComponent(m.id)}`)}>
                {m.title}
              </Command.Item>
            ))}
          </Command.Group>
        )}
        {hits.length > 0 && (
          <Command.Group heading={t("rulesets.title")}>
            {hits.map((hit) => (
              <Command.Item
                key={`${hit.ruleset}:${hit.section}:${hit.id}`}
                value={`ruleset ${hit.name} ${sectionLabel(t, hit.section)} ${hit.ruleset} ${hit.section} ${hit.id}`}
                onSelect={() => go(entryHref(hit.ruleset, hit.section, hit.id))}
              >
                <span>{hit.name}</span> <span className="row-meta">{sectionLabel(t, hit.section)}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}
        {(settings.data?.length ?? 0) > 0 && (
          <Command.Group heading={t("area.settings")}>
            {settings.data!.map((s) => (
              <Command.Item key={s.id} value={`setting ${s.title} ${s.id}`} onSelect={() => go(`/settings/${encodeURIComponent(s.id)}`)}>
                {s.title}
              </Command.Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
    </Command.Dialog>
  );
}

function Help({ open, onOpenChange, owner }: { open: boolean; onOpenChange: (open: boolean) => void; owner: boolean }) {
  const t = useT();
  const shown = (list: typeof SHORTCUTS) => list.filter((s) => owner || !s.owner);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog shortcuts-help" aria-describedby={undefined}>
          <Dialog.Title className="dialog-title">{t("shortcuts.title")}</Dialog.Title>
          <dl className="shortcuts">
            {shown(SHORTCUTS).map((s) => (
              <div key={s.shown}>
                <dt>
                  <kbd>{s.shown}</kbd>
                </dt>
                <dd>{t(s.label)}</dd>
              </div>
            ))}
          </dl>
          {owner && (
            <>
              <h3>{t("shortcuts.goTo")}</h3>
              <dl className="shortcuts">
                {GO_TO.map((s) => (
                  <div key={s.shown}>
                    <dt>
                      <kbd>{s.shown}</kbd>
                    </dt>
                    <dd>{t(s.label)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          <div className="actions">
            <Dialog.Close asChild>
              <button type="button">{t("dialog.close")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
