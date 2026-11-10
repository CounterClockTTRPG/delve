import { fireEvent, render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "../i18n";
import SettingText from "./SettingText";

const href = (title: string) => `/pages/${encodeURIComponent(title)}`;

function renderText(text: string, dmMarked = true) {
  const router = createMemoryRouter(
    [
      { path: "/", element: <SettingText text={text} pageHref={href} dmMarked={dmMarked} /> },
      { path: "/pages/:title", element: <p>Opened</p> },
    ],
    { initialEntries: ["/"] },
  );
  const view = render(
    <I18nProvider language="en">
      <RouterProvider router={router} />
    </I18nProvider>,
  );
  return { router, container: view.container };
}

describe("SettingText", () => {
  it("renders the Markdown, and each link opens its page through the router", async () => {
    const { router, container } = renderText("## History\n\nSee **[[Old Town]]** and [[River Gate|the gate]].");
    expect(container.querySelector("h4")?.textContent).toBe("History");
    expect(container.querySelector("strong a")?.textContent).toBe("Old Town");
    const gate = screen.getByRole("link", { name: "the gate" });
    expect(gate.getAttribute("href")).toBe("/pages/River%20Gate");
    fireEvent.click(gate);
    expect(await screen.findByText("Opened")).toBeTruthy();
    expect(router.state.location.pathname).toBe("/pages/River%20Gate");
  });

  it("escapes a title holding markup", () => {
    const { container } = renderText('[[<script>alert(1)</script>|<img src=x onerror="boom">]] & more');
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByRole("link");
    expect(link.textContent).toBe('<img src=x onerror="boom">');
    expect(link.getAttribute("href")).toBe(href("<script>alert(1)</script>"));
    expect(container.textContent).toContain("& more");
  });

  it("keeps a link's target whole when it holds Markdown marks", () => {
    renderText("[[Ready_Made_Hall]] and [[*Star*]]");
    expect(screen.getByRole("link", { name: "Ready_Made_Hall" }).getAttribute("href")).toBe(href("Ready_Made_Hall"));
    expect(screen.getByRole("link", { name: "*Star*" }).getAttribute("href")).toBe(href("*Star*"));
  });

  it("marks a DM-only section, closed or running to the end", () => {
    const { container } = renderText("Open.\n\n::: dm\nOne.\n:::\n\nMiddle.\n\n::: dm\nTwo.");
    const asides = container.querySelectorAll("aside.dm-only");
    expect(asides).toHaveLength(2);
    expect(asides[0].textContent).toContain("DM only");
    expect(asides[0].textContent).toContain("One.");
    expect(asides[1].textContent).toContain("Two.");
    expect(screen.getByText("Middle.").closest("aside")).toBeNull();
    expect(container.textContent).not.toContain(":::");
  });

  it("without dmMarked, a section is plain text", () => {
    const { container } = renderText("::: dm\nOne.\n:::", false);
    expect(container.querySelector("aside")).toBeNull();
    expect(screen.getByText("One.")).toBeTruthy();
  });
});
