import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { MoreHorizontal } from "lucide-react";
import { useNavigate } from "react-router-dom";
import Tip from "./Tip";

export type RowAction = {
  label: string;
  /** A screen of Delve's to open, a file to download, or something to do. */
  to?: string;
  download?: string;
  onSelect?: () => void;
  danger?: boolean;
  disabled?: boolean;
};

/** A row's actions behind one "…" button: opened with a click, Enter or Space, and walked with the arrow keys. */
export default function RowMenu({ label, actions }: { label: string; actions: RowAction[] }) {
  const navigate = useNavigate();
  return (
    <DropdownMenu.Root modal={false}>
      <Tip label={label}>
        <DropdownMenu.Trigger asChild>
          <button type="button" className="icon row-menu" aria-label={label}>
            <MoreHorizontal size={18} aria-hidden="true" />
          </button>
        </DropdownMenu.Trigger>
      </Tip>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={4}>
          {actions.map((action) =>
            action.download ? (
              <DropdownMenu.Item key={action.label} asChild disabled={action.disabled}>
                <a className="menu-item" href={action.download} download>
                  {action.label}
                </a>
              </DropdownMenu.Item>
            ) : (
              <DropdownMenu.Item
                key={action.label}
                className={action.danger ? "menu-item danger" : "menu-item"}
                disabled={action.disabled}
                onSelect={() => (action.to ? navigate(action.to) : action.onSelect?.())}
              >
                {action.label}
              </DropdownMenu.Item>
            ),
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
