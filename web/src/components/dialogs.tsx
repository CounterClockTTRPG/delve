// Delve's own confirm and prompt, instead of the browser's: built on Radix, styled with Delve's tokens.
// `useConfirm()` and `usePrompt()` return a function that opens the dialog and answers a promise, so each
// call site of the browser's confirm or prompt changes one for one. Escape and Cancel answer false / null.
import * as AlertDialog from "@radix-ui/react-alert-dialog";
import * as Dialog from "@radix-ui/react-dialog";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { useT } from "../i18n";

export type ConfirmOptions = { title: string; body?: string; confirm: string; danger?: boolean };
export type PromptOptions = { title: string; label: string; initial?: string; confirm: string };

type Confirm = (options: ConfirmOptions) => Promise<boolean>;
type Prompt = (options: PromptOptions) => Promise<string | null>;

type Request =
  | { kind: "confirm"; options: ConfirmOptions; answer: (value: boolean) => void }
  | { kind: "prompt"; options: PromptOptions; answer: (value: string | null) => void };
/** A request on screen: its number keys the dialog, and the focus goes back to its opener when it closes. */
type Shown = { id: number; request: Request; opener: HTMLElement | null };

const missing = () => Promise.reject(new Error("dialogs need a <DialogsProvider>"));
const DialogsContext = createContext<{ confirm: Confirm; prompt: Prompt }>({ confirm: missing, prompt: missing });

export function useConfirm(): Confirm {
  return useContext(DialogsContext).confirm;
}

export function usePrompt(): Prompt {
  return useContext(DialogsContext).prompt;
}

/** Shows one dialog at a time; a new one answers the one still open as cancelled. */
export function DialogsProvider({ children }: { children: ReactNode }) {
  const [shown, setShown] = useState<Shown | null>(null);
  const current = useRef<Shown | null>(null);
  const count = useRef(0);

  const show = useCallback((request: Request) => {
    if (current.current) cancel(current.current.request);
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    current.current = { id: ++count.current, request, opener };
    setShown(current.current);
  }, []);
  // A promise answers once, so a confirm's true wins over the close that follows it.
  const settle = useCallback((done: Shown, value: boolean | string | null) => {
    (done.request.answer as (value: boolean | string | null) => void)(value);
    if (current.current === done) {
      current.current = null;
      setShown(null);
    }
  }, []);

  const value = useMemo(
    () => ({
      confirm: (options: ConfirmOptions) => new Promise<boolean>((answer) => show({ kind: "confirm", options, answer })),
      prompt: (options: PromptOptions) => new Promise<string | null>((answer) => show({ kind: "prompt", options, answer })),
    }),
    [show],
  );

  const request = shown?.request;
  const restoreFocus = (e: Event) => {
    e.preventDefault();
    shown?.opener?.focus();
  };
  return (
    <DialogsContext.Provider value={value}>
      {children}
      {shown && request?.kind === "confirm" && (
        <ConfirmDialog
          key={shown.id}
          options={request.options}
          onAnswer={(ok) => settle(shown, ok)}
          onClosed={restoreFocus}
        />
      )}
      {shown && request?.kind === "prompt" && (
        <PromptDialog
          key={shown.id}
          options={request.options}
          onAnswer={(text) => settle(shown, text)}
          onClosed={restoreFocus}
        />
      )}
    </DialogsContext.Provider>
  );
}

function cancel(request: Request) {
  if (request.kind === "confirm") request.answer(false);
  else request.answer(null);
}

type DialogProps<O, A> = { options: O; onAnswer: (value: A) => void; onClosed: (e: Event) => void };

function ConfirmDialog({ options, onAnswer, onClosed }: DialogProps<ConfirmOptions, boolean>) {
  const t = useT();
  return (
    <AlertDialog.Root open onOpenChange={(isOpen) => isOpen || onAnswer(false)}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="dialog-overlay" />
        <AlertDialog.Content
          className="dialog"
          onCloseAutoFocus={onClosed}
          {...(options.body ? {} : { "aria-describedby": undefined })}
        >
          <AlertDialog.Title className="dialog-title">{options.title}</AlertDialog.Title>
          {options.body && <AlertDialog.Description className="dialog-body">{options.body}</AlertDialog.Description>}
          <div className="dialog-actions">
            <AlertDialog.Cancel asChild>
              <button type="button">{t("dialog.cancel")}</button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button type="button" className={options.danger ? "danger solid" : "primary"} onClick={() => onAnswer(true)}>
                {options.confirm}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

function PromptDialog({ options, onAnswer, onClosed }: DialogProps<PromptOptions, string | null>) {
  const t = useT();
  const [text, setText] = useState(options.initial ?? "");
  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onAnswer(null)}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog" aria-describedby={undefined} onCloseAutoFocus={onClosed}>
          <Dialog.Title className="dialog-title">{options.title}</Dialog.Title>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onAnswer(text);
            }}
          >
            <div className="field">
              <label htmlFor="dialog-prompt">{options.label}</label>
              <input id="dialog-prompt" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" />
            </div>
            <div className="dialog-actions">
              <Dialog.Close asChild>
                <button type="button">{t("dialog.cancel")}</button>
              </Dialog.Close>
              <button type="submit" className="primary">
                {options.confirm}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
