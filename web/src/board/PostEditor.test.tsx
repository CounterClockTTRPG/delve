import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import PostEditor, { POST_LIMIT, formatted, type Insert } from "./PostEditor";

// The board's post editor (DEL-297): Markdown buttons over the selection, a preview, the count against the limit,
// quotes put in, and pictures only where the zone takes them.

function renderEditor(props: Partial<Parameters<typeof PostEditor>[0]> = {}) {
  const onSubmit = vi.fn();
  const view = render(
    <I18nProvider language="en">
      <PostEditor onSubmit={onSubmit} pictures={false} busy={false} {...props} />
    </I18nProvider>,
  );
  const box = () => screen.getByRole("textbox", { name: "Your post" }) as HTMLTextAreaElement;
  return { onSubmit, box, view };
}

function paste(target: HTMLElement, files: File[]) {
  const event = createEvent.paste(target);
  Object.defineProperty(event, "clipboardData", { value: { files } });
  fireEvent(target, event);
  return event;
}

describe("formatted", () => {
  it("wraps a selection in bold or italic, and makes it a link's words", () => {
    expect(formatted("a word here", 2, 6, "bold")).toEqual({ text: "a **word** here", start: 4, end: 8 });
    expect(formatted("a word", 2, 6, "italic").text).toBe("a *word*");
    const link = formatted("see this", 4, 8, "link");
    expect(link.text).toBe("see [this](https://)");
    expect(link.text.slice(link.start, link.end)).toBe("https://");
  });

  it("puts a heading, a list or a quote before each whole line of the selection", () => {
    expect(formatted("one\ntwo\nthree", 1, 5, "bullets").text).toBe("- one\n- two\nthree");
    expect(formatted("one\ntwo", 0, 7, "numbers").text).toBe("1. one\n2. two");
    expect(formatted("intro\ntitle", 7, 7, "heading").text).toBe("intro\n## title");
    expect(formatted("said", 0, 0, "quote").text).toBe("> said");
  });
});

describe("PostEditor", () => {
  it("bolds the selection with its button, and sends the words stripped", () => {
    const { box, onSubmit } = renderEditor();
    fireEvent.change(box(), { target: { value: " make this loud " } });
    box().setSelectionRange(6, 10);
    fireEvent.click(screen.getByRole("button", { name: "Bold" }));
    expect(box().value).toBe(" make **this** loud ");
    fireEvent.click(screen.getByRole("button", { name: "Post" }));
    expect(onSubmit).toHaveBeenCalledWith("make **this** loud", null);
  });

  it("previews the post as it will show", () => {
    const { box } = renderEditor();
    fireEvent.change(box(), { target: { value: "## Morale\n\n<script>x</script>" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    const shown = screen.getByTestId("board-preview");
    expect(shown.querySelector("h2")?.textContent).toBe("Morale");
    expect(shown.querySelector("script")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Write" }));
    expect(box().value).toBe("## Morale\n\n<script>x</script>");
  });

  it("counts the characters against the limit, and sends nothing past it", () => {
    const { box, onSubmit } = renderEditor();
    expect(screen.getByTestId("board-count").textContent).toBe("0 / 20,000 characters");
    fireEvent.change(box(), { target: { value: "x".repeat(POST_LIMIT + 1) } });
    expect(screen.getByTestId("board-count").className).toContain("over");
    expect((screen.getByRole("button", { name: "Post" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(box().form!);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("adds a quote at the end of what is written, each time it is sent", async () => {
    const { box, view } = renderEditor({ initial: "My words." });
    const quote = (n: number): Insert => ({ text: "> **Ana wrote:**\n> Hi\n\n", n });
    view.rerender(
      <I18nProvider language="en">
        <PostEditor onSubmit={vi.fn()} pictures={false} busy={false} initial="My words." insert={quote(1)} />
      </I18nProvider>,
    );
    await waitFor(() => expect(box().value).toBe("My words.\n\n> **Ana wrote:**\n> Hi\n\n"));
  });

  it("takes a pasted picture only where the zone allows pictures", () => {
    const picture = new File(["png"], "map.png", { type: "image/png" });
    const closed = renderEditor();
    expect(paste(closed.box(), [picture]).defaultPrevented).toBe(false);
    expect(screen.queryByText("Picture: map.png")).toBeNull();
    expect(screen.queryByLabelText("Add a picture")).toBeNull();
    closed.view.unmount();

    const { box, onSubmit } = renderEditor({ pictures: true });
    expect(paste(box(), [picture]).defaultPrevented).toBe(true);
    expect(screen.getByText("Picture: map.png")).toBeTruthy();
    fireEvent.change(box(), { target: { value: "The map." } });
    fireEvent.click(screen.getByRole("button", { name: "Post" }));
    expect(onSubmit).toHaveBeenCalledWith("The map.", picture);
  });
});
