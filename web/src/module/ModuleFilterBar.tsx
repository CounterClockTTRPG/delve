import { useQuery } from "@tanstack/react-query";
import { listModuleCategories, queryKeys, type ModuleSummary } from "../api";
import { useT } from "../i18n";
import { NO_CATEGORY, NO_FILTER, NO_SETTING, filterOptions, isFiltering, type ModuleFilter } from "./filter";
import { isHomebrewTag } from "./homebrew";

/**
 * The module filter's fields over `modules` (backlog 37): Title (any part), Setting (each in use, and No setting),
 * Starting level, Tag and Category (DEL-114, once there are categories), with Clear while one is used. `idPrefix` keeps the field ids apart where two bars could
 * meet. A setting or tag in the filter that no module has any more stays offered, so the bar says what it shows.
 * `inForm` names the fields "Module title", "Module setting"…: in New campaign, the campaign has a Setting of its own.
 */
export default function ModuleFilterBar({
  modules,
  value,
  onChange,
  idPrefix = "module-filter",
  inForm = false,
}: {
  modules: ModuleSummary[];
  value: ModuleFilter;
  onChange: (filter: ModuleFilter) => void;
  idPrefix?: string;
  inForm?: boolean;
}) {
  const t = useT();
  const label = (key: string) => t(inForm ? `moduleFilter.module.${key}` : `moduleFilter.${key}`);
  const options = filterOptions(modules);
  const settings = value.setting && value.setting !== NO_SETTING && !options.settings.includes(value.setting)
    ? [value.setting, ...options.settings]
    : options.settings;
  const tags = value.tag && !options.tags.includes(value.tag) ? [value.tag, ...options.tags] : options.tags;
  const set = (key: keyof ModuleFilter) => (next: string) => onChange({ ...value, [key]: next });
  const categories = useQuery({ queryKey: queryKeys.moduleCategories, queryFn: listModuleCategories }).data ?? [];
  return (
    <div className="module-filter" role="search" aria-label={t("moduleFilter.label")}>
      <div className="field module-filter-title">
        <label htmlFor={`${idPrefix}-title`}>{label("title")}</label>
        <input id={`${idPrefix}-title`} type="search" value={value.title} onChange={(e) => set("title")(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-setting`}>{label("setting")}</label>
        <select id={`${idPrefix}-setting`} value={value.setting} onChange={(e) => set("setting")(e.target.value)}>
          <option value="">{t("moduleFilter.any")}</option>
          {settings.map((setting) => (
            <option key={setting} value={setting}>
              {setting}
            </option>
          ))}
          {(options.noSetting || value.setting === NO_SETTING) && <option value={NO_SETTING}>{t("moduleFilter.noSetting")}</option>}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-level`}>{label("level")}</label>
        <input
          id={`${idPrefix}-level`}
          type="number"
          min={1}
          step={1}
          inputMode="numeric"
          value={value.level}
          onChange={(e) => set("level")(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-tag`}>{label("tag")}</label>
        <select id={`${idPrefix}-tag`} value={value.tag} onChange={(e) => set("tag")(e.target.value)}>
          <option value="">{t("moduleFilter.any")}</option>
          {tags.map((tag) => (
            <option key={tag} value={tag}>
              {tag}
            </option>
          ))}
        </select>
      </div>
      {(categories.length > 0 || value.category) && (
        <div className="field">
          <label htmlFor={`${idPrefix}-category`}>{label("category")}</label>
          <select id={`${idPrefix}-category`} value={value.category} onChange={(e) => set("category")(e.target.value)}>
            <option value="">{t("moduleFilter.any")}</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
            <option value={NO_CATEGORY}>{t("moduleCategories.none")}</option>
          </select>
        </div>
      )}
      {isFiltering(value) && (
        <button type="button" className="module-filter-clear" onClick={() => onChange(NO_FILTER)}>
          {t("moduleFilter.clear")}
        </button>
      )}
    </div>
  );
}

/** A module's setting, level range and tags as a line of its own under the row's title (nothing when it has none); a tag is a button that filters on it when `onTag`. */
export function ModuleFacets({ module, onTag }: { module: ModuleSummary; onTag?: (tag: string) => void }) {
  const t = useT();
  const levels = module.levels;
  // The homebrew tag is the card's own (DEL-226), beside Draft.
  const tags = (module.tags ?? []).filter((tag) => !isHomebrewTag(tag));
  if (!module.setting && !levels && !tags.length) return null;
  return (
    <span className="module-facets">
      {module.setting && <span className="row-meta">{module.setting}</span>}
      {levels && (
        <span className="row-meta">
          {levels.min === levels.max
            ? t("moduleFilter.levelOne", { level: String(levels.min) })
            : t("moduleFilter.levels", { min: String(levels.min), max: String(levels.max) })}
        </span>
      )}
      {tags.length > 0 && (
        <span className="module-tags">
          {tags.map((tag) =>
            onTag ? (
              <button
                key={tag}
                type="button"
                className="tag tag-button"
                aria-label={t("moduleFilter.byTag", { tag })}
                onClick={() => onTag(tag)}
              >
                {tag}
              </button>
            ) : (
              <span key={tag} className="tag">
                {tag}
              </span>
            ),
          )}
        </span>
      )}
    </span>
  );
}
