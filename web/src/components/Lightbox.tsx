import * as Dialog from "@radix-ui/react-dialog";
import { useState, type ReactNode } from "react";

/**
 * A picture that enlarges on a click (backlog Interface 7): `children` is a button named `label` that opens `big` in a
 * dialog titled `title`, which a click inside it or Escape closes. The click stops at the button, and the dialog's
 * clicks stop in it, so a card around the picture (a party card opens a sheet) never sees them.
 */
export default function Lightbox({
  label,
  title,
  big,
  className,
  children,
}: {
  label: string;
  title: string;
  big: ReactNode;
  /** The button's class: the page styles it like the picture it holds. */
  className: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={className}
        aria-label={label}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
      >
        {children}
      </button>
      {open && (
        <Dialog.Root open onOpenChange={(isOpen) => isOpen || setOpen(false)}>
          <Dialog.Portal>
            <Dialog.Overlay className="dialog-overlay" />
            <Dialog.Content
              className="dialog lightbox"
              aria-describedby={undefined}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
              }}
            >
              <Dialog.Title className="visually-hidden">{title}</Dialog.Title>
              {big}
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      )}
    </>
  );
}
