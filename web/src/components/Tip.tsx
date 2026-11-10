import * as Tooltip from "@radix-ui/react-tooltip";
import type { ReactElement } from "react";

/**
 * A short label shown beside a control under the pointer or the keyboard's focus: for buttons that show only an icon
 * or a swatch. The control keeps its own accessible name, which the tip repeats for the eye.
 */
export default function Tip({ label, children, side = "top" }: { label: string; children: ReactElement; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    // Its own provider, so a tip works on any screen and in a component's tests alike.
    <Tooltip.Provider delayDuration={400} skipDelayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="tip" side={side} sideOffset={6}>
            {label}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
