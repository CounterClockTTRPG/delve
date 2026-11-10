import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { apiFetch } from "../api";
import { useT } from "../i18n";

/** The time zones the server knows (DEL-239). Not the browser's list: its names are ICU's, and some of them
 * (Africa/Asmera, Asia/Calcutta) are aliases the server's tz database no longer has. */
export const getTimeZones = () => apiFetch<string[]>("/api/time-zones");

/** The server's time zones, with `keep` (a stored one) added when it isn't one of them; empty until they're read. */
export function useTimeZones(keep = ""): string[] {
  const { data } = useQuery({ queryKey: ["time-zones"], queryFn: getTimeZones, staleTime: Infinity });
  return useMemo(() => {
    const zones = data ?? [];
    return keep && zones.length && !zones.includes(keep) ? [keep, ...zones] : zones;
  }, [data, keep]);
}

/** A zone's offset from UTC on `at`, as Intl writes it ("GMT+05:30"); empty for a zone this browser doesn't know. */
function offsetOn(zone: string, at: Date): string {
  try {
    const parts = new Intl.DateTimeFormat("en", { timeZone: zone, timeZoneName: "longOffset" }).formatToParts(at);
    return parts.find((part) => part.type === "timeZoneName")?.value ?? "";
  } catch {
    return "";
  }
}

/**
 * `own` (the browser's zone) as one of `zones`: itself when it is one, else a zone of its region keeping its clock in
 * winter and in summer (Asia/Calcutta becomes Asia/Kolkata), else any zone that does, else UTC. `own` itself while
 * `zones` is still empty.
 */
export function closestZone(own: string, zones: string[]): string {
  if (!zones.length || zones.includes(own)) return own;
  const year = new Date().getUTCFullYear();
  const days = [new Date(Date.UTC(year, 0, 15)), new Date(Date.UTC(year, 6, 15))];
  const clock = (zone: string) => days.map((day) => offsetOn(zone, day)).join();
  const wanted = clock(own);
  const same = zones.filter((zone) => clock(zone) === wanted);
  return same.find((zone) => regionOf(zone) === regionOf(own)) ?? same[0] ?? "UTC";
}

/** The region a zone sits in, its name's first part ("Europe" of "Europe/Brussels"); "other" for one without ("UTC"). */
export function regionOf(zone: string): string {
  const slash = zone.indexOf("/");
  return slash > 0 ? zone.slice(0, slash) : "other";
}

/** A zone's city as read: what follows the region, "America/Argentina/Buenos_Aires" as "Argentina / Buenos Aires". */
export function cityOf(zone: string): string {
  const slash = zone.indexOf("/");
  return (slash > 0 ? zone.slice(slash + 1) : zone).replaceAll("_", " ").replaceAll("/", " / ");
}

/** `zones` by region, the regions and each one's zones in alphabetical order, "other" last. */
export function byRegion(zones: string[]): [string, string[]][] {
  const groups = new Map<string, string[]>();
  for (const zone of zones) {
    const region = regionOf(zone);
    groups.set(region, [...(groups.get(region) ?? []), zone]);
  }
  const rank = (region: string) => (region === "other" ? "￿" : region);
  return [...groups]
    .sort(([a], [b]) => rank(a).localeCompare(rank(b)))
    .map(([region, list]) => [region, [...list].sort((a, b) => cityOf(a).localeCompare(cityOf(b)))]);
}

/**
 * A time zone chosen in two steps (DEL-239): the region, then the city in it. Picking a region picks `preferred` when
 * it lies there (the viewer's own zone), else the region's first city. With `none`, the region menu starts with that
 * choice, which empties the value. `id` goes on the region menu, for the field's label; the city menu is labelled
 * on its own.
 */
export default function TimeZonePicker({
  id,
  testId,
  zones,
  value,
  onChange,
  preferred,
  none,
}: {
  id: string;
  testId?: string;
  zones: string[];
  value: string;
  onChange: (zone: string) => void;
  preferred?: string;
  none?: string;
}) {
  const t = useT();
  const regions = useMemo(() => byRegion(zones), [zones]);
  const region = value ? regionOf(value) : "";
  const cities = regions.find(([name]) => name === region)?.[1] ?? [];

  const pickRegion = (next: string) => {
    if (!next) return onChange("");
    const list = regions.find(([name]) => name === next)?.[1] ?? [];
    onChange(preferred && list.includes(preferred) ? preferred : (list[0] ?? ""));
  };

  return (
    <div className="time-zone-picker">
      <select
        id={id}
        data-testid={testId && `${testId}-region`}
        value={region}
        onChange={(e) => pickRegion(e.target.value)}
      >
        {none !== undefined && <option value="">{none}</option>}
        {regions.map(([name]) => (
          <option key={name} value={name}>
            {t(`timeZone.region.${name}`) === `timeZone.region.${name}` ? name : t(`timeZone.region.${name}`)}
          </option>
        ))}
      </select>
      {value && (
        <select
          aria-label={t("timeZone.city")}
          data-testid={testId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          {cities.map((zone) => (
            <option key={zone} value={zone}>
              {cityOf(zone)}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
