// What kind of thing each DM tool does, for its row in the story (DEL-117): one fixed icon per kind, and a tone, the
// semantic colour of its meaning. docs/style-guide.md says how to use them; tests/web/test_tool_kinds.py checks that
// every tool the table sees has a kind here.
import {
  BookOpen,
  Clock,
  Coins,
  Dices,
  HeartPulse,
  Map as MapIcon,
  MessageSquare,
  Sparkles,
  Swords,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";

/** The semantic colours (docs/style-guide.md), each a token every look defines. */
export type Tone = "danger" | "chance" | "magic" | "wealth" | "world" | "people" | "knowledge" | "plain";

export interface ToolKind {
  icon: LucideIcon;
  tone: Tone;
}

export const TOOL_KINDS = {
  chance: { icon: Dices, tone: "chance" },
  combat: { icon: Swords, tone: "danger" },
  body: { icon: HeartPulse, tone: "danger" },
  magic: { icon: Sparkles, tone: "magic" },
  wealth: { icon: Coins, tone: "wealth" },
  place: { icon: MapIcon, tone: "world" },
  time: { icon: Clock, tone: "world" },
  party: { icon: Users, tone: "people" },
  story: { icon: MessageSquare, tone: "people" },
  lookup: { icon: BookOpen, tone: "knowledge" },
  other: { icon: Wrench, tone: "plain" },
} as const satisfies Record<string, ToolKind>;

export type ToolKindName = keyof typeof TOOL_KINDS;

/** Each tool the table sees, by its kind. A new tool goes in one of these lists. */
const BY_KIND: Record<Exclude<ToolKindName, "other">, string[]> = {
  chance: [
    "roll",
    "ability_check",
    "skill_check",
    "saving_throw",
    "surprise_check",
    "morale_check",
    "reaction",
    "system_shock",
    "resurrection_check",
    "turning_undead",
    "weather_check",
    "door",
    "adjudicate",
  ],
  combat: [
    "setup_combat",
    "combat_round",
    "resolve_attack",
    "throw_missile",
    "add_combatant",
    "update_combatant",
    "remove_combatant",
    "end_combat",
    "combat_status",
    "interrupt",
  ],
  body: ["apply_damage", "apply_heal", "add_condition", "remove_condition", "rest"],
  magic: ["cast_spell", "memorize_spells", "set_spell_loadout", "spell_status", "apply_effect", "remove_effect"],
  wealth: [
    "award_treasure",
    "claim_loot",
    "loot_pile",
    "add_item",
    "remove_item",
    "inventory",
    "encumbrance",
    "transfer",
    "update_coin",
    "buy_magic_item",
    "magic_merchant",
    "add_possession",
    "remove_possession",
    "update_possession",
    "possessions",
  ],
  place: [
    "move_party",
    "place_party",
    "travel",
    "distance",
    "nearest",
    "reveal_place",
    "scout",
    "set_marching_order",
  ],
  time: ["advance_time", "advance_days", "set_time", "calendar", "new_session", "end_session"],
  party: [
    "create_character",
    "get_character",
    "update_character",
    "party_status",
    "award_xp",
    "drain_level",
    "leave_party",
    "rejoin_party",
    "portrait",
  ],
  story: [
    "say",
    "tell",
    "introduce_npc",
    "set_disposition",
    "council",
    "log_note",
    "add_quest",
    "update_quest",
    "paint_scene",
    "show_image",
  ],
  lookup: [
    "ability_lookup",
    "class_lookup",
    "item_lookup",
    "monster_lookup",
    "proficiency_lookup",
    "race_lookup",
    "rules_lookup",
    "rules_section",
    "spell_lookup",
    "setting_lookup",
    "setting_search",
    "house_rules",
  ],
};

const KIND_OF = new Map<string, ToolKindName>(
  Object.entries(BY_KIND).flatMap(([kind, names]) => names.map((name) => [name, kind as ToolKindName])),
);

/** The kind of the tool `name`: "other" for one not listed (a batch, a tool newer than this list). */
export const toolKind = (name: string | undefined): ToolKindName => (name ? (KIND_OF.get(name) ?? "other") : "other");
