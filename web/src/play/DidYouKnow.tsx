import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { getLore, playKeys } from "./api";

/** How long each fact stays. */
export const FACT_EVERY_MS = 8000;

/**
 * "Did you know": while the DM thinks, a fact of the campaign's setting, a new one every 8 s (plan 6, Decision 8).
 * The facts are the setting's only, never the campaign's own, and are read once; without any, it shows nothing.
 */
export default function DidYouKnow({ campaignId }: { campaignId: string }) {
  const t = useT();
  const lore = useQuery({ queryKey: playKeys.lore(campaignId), queryFn: () => getLore(campaignId), staleTime: Infinity });
  const [index, setIndex] = useState(0);
  const facts = lore.data?.facts ?? [];
  const count = facts.length;

  useEffect(() => {
    if (count < 2) return;
    const timer = setInterval(() => setIndex((i) => (i + 1) % count), FACT_EVERY_MS);
    return () => clearInterval(timer);
  }, [count]);

  if (count === 0) return null;
  return (
    <p className="did-you-know" data-testid="did-you-know">
      <span className="did-you-know-label">{t("play.didYouKnow")}</span> <span>{facts[index % count].text}</span>
    </p>
  );
}
