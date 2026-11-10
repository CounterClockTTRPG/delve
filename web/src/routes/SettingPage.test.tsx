import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, sent, stubFetch, type Handler } from "../play/testing";
import { page, renderArea, settingInfo } from "../setting/testing";

const base = "/api/settings/greyhawk";
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof stubFetch>;

beforeEach(() => {
  routes = { [`GET ${base}`]: () => json(200, settingInfo("greyhawk", "Greyhawk")) };
  fetchMock = stubFetch(routes);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SettingPage", () => {
  it("shows the page: its kind, its fields, its text and its links", async () => {
    routes[`GET ${base}/pages/Hardby`] = () =>
      json(200, page("Hardby", { fields: { ruler: "Despotrix" }, text: "A town south of [[Greyhawk City|the city]]." }));
    const router = renderArea("/settings/greyhawk/pages/Hardby");
    expect(await screen.findByRole("heading", { level: 1, name: "Hardby" })).toBeTruthy();
    expect(screen.getByText("settlements")).toBeTruthy();
    expect(screen.getByText("ruler")).toBeTruthy();
    expect(screen.getByText("Despotrix")).toBeTruthy();
    const link = screen.getByRole("link", { name: "the city" });
    expect(link.getAttribute("href")).toBe("/settings/greyhawk/pages/Greyhawk%20City");
    routes[`GET ${base}/pages/Greyhawk%20City`] = () => json(200, page("Greyhawk City"));
    fireEvent.click(link);
    expect(await screen.findByRole("heading", { level: 1, name: "Greyhawk City" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/settings/greyhawk/pages/Greyhawk%20City");
  });

  it("says which title it was redirected from, and where the page came from", async () => {
    routes[`GET ${base}/pages/Mordy`] = () =>
      json(200, page("Mordenkainen", { origin: "addition", dm_only: true, redirected_from: "Mordy" }));
    renderArea("/settings/greyhawk/pages/Mordy");
    expect(await screen.findByRole("heading", { level: 1, name: "Mordenkainen" })).toBeTruthy();
    expect(screen.getByText("Redirected from Mordy")).toBeTruthy();
    expect(screen.getByText("Added on this install")).toBeTruthy();
    expect(screen.getByText("DM only")).toBeTruthy();
  });

  it("marks a DM-only section", async () => {
    routes[`GET ${base}/pages/Hardby`] = () => json(200, page("Hardby", { text: "Open.\n\n::: dm\nThe mayor is a doppelganger.\n:::\n\nAfter." }));
    renderArea("/settings/greyhawk/pages/Hardby");
    const aside = (await screen.findByText("The mayor is a doppelganger.")).closest("aside")!;
    expect(aside.className).toContain("dm-only");
    expect(within(aside).getByText("DM only")).toBeTruthy();
    expect(screen.getByText("After.").closest("aside")).toBeNull();
  });

  it("Revert asks first, then deletes the override and shows the book's page", async () => {
    let reverted = false;
    routes[`GET ${base}/pages/Hardby`] = () =>
      json(200, reverted ? page("Hardby", { text: "The book's." }) : page("Hardby", { origin: "override", revertible: true, text: "Ours." }));
    routes[`DELETE ${base}/pages/Hardby`] = () => {
      reverted = true;
      return new Response(null, { status: 204 });
    };
    renderArea("/settings/greyhawk/pages/Hardby");
    expect(await screen.findByText("Changed on this install")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Revert to the book's page" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Revert to the book's page" }));
    expect(await screen.findByText("The book's.")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([p, init]) => p === `${base}/pages/Hardby` && init?.method === "DELETE")).toHaveLength(1);
  });

  it("Delete removes an addition after the confirm and goes back to the setting", async () => {
    routes[`GET ${base}/pages/Hob%20Hill`] = () => json(200, page("Hob Hill", { origin: "addition" }));
    routes[`DELETE ${base}/pages/Hob%20Hill`] = () => new Response(null, { status: 204 });
    const router = renderArea("/settings/greyhawk/pages/Hob%20Hill");
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/settings/greyhawk"));
  });

  it("Edit opens the form, prefilled, and Save puts the page with its fields", async () => {
    let overridden = false;
    const ours = page("Hardby", { origin: "override", revertible: true, text: "A port." });
    routes[`GET ${base}/pages/Hardby`] = () =>
      json(200, overridden ? ours : page("Hardby", { fields: { ruler: "Despotrix" }, text: "A town." }));
    routes[`PUT ${base}/pages/Hardby`] = () => {
      overridden = true;
      return json(200, ours);
    };
    renderArea("/settings/greyhawk/pages/Hardby");
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const title = screen.getByLabelText("Title") as HTMLInputElement;
    expect(title.value).toBe("Hardby");
    expect(title.readOnly).toBe(true);
    expect((screen.getByLabelText("Kind") as HTMLSelectElement).value).toBe("settlements");
    expect((screen.getByLabelText("Text") as HTMLTextAreaElement).value).toBe("A town.");
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "A port." } });
    fireEvent.click(screen.getByRole("button", { name: "Add a field" }));
    const keys = screen.getAllByLabelText("Field name");
    const values = screen.getAllByLabelText("Field value");
    fireEvent.change(keys[1], { target: { value: "population" } });
    fireEvent.change(values[1], { target: { value: "4,000" } });
    fireEvent.click(screen.getByLabelText("DM only"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Changed on this install")).toBeTruthy();
    expect(sent(fetchMock, "PUT", `${base}/pages/Hardby`)).toEqual([
      { kind: "settlements", fields: { ruler: "Despotrix", population: "4,000" }, text: "A port.", dm_only: true },
    ]);
    expect(screen.queryByLabelText("Text")).toBeNull();
  });

  it("a page that doesn't exist offers to write it", async () => {
    routes[`GET ${base}/pages/Hob%20Hill`] = () => json(404, { error: "There is no page 'Hob Hill'." });
    const router = renderArea("/settings/greyhawk/pages/Hob%20Hill");
    expect(await screen.findByText("No page Hob Hill.")).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "Write it" }));
    const title = (await screen.findByLabelText("Title")) as HTMLInputElement;
    expect(router.state.location.pathname).toBe("/settings/greyhawk/new-page");
    expect(title.value).toBe("Hob Hill");
    expect(title.readOnly).toBe(false);
  });

  it("New page saves under its title and opens it; a title with a slash round-trips", async () => {
    const title = "Ready'reat / Patchwall?";
    const path = `${base}/pages/${encodeURIComponent(title)}`;
    routes[`PUT ${path}`] = () => json(201, page(title, { origin: "addition", kind: "", text: "Two towns." }));
    routes[`GET ${path}`] = () => json(200, page(title, { origin: "addition", kind: "", text: "Two towns." }));
    const router = renderArea("/settings/greyhawk/new-page");
    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: title } });
    expect((screen.getByLabelText("Kind") as HTMLSelectElement).value).toBe("");
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "Two towns." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeTruthy();
    expect(router.state.location.pathname).toBe(`/settings/greyhawk/pages/${encodeURIComponent(title)}`);
    expect(sent(fetchMock, "PUT", path)).toEqual([{ kind: "", fields: {}, text: "Two towns.", dm_only: false }]);
  });

  it("a refused save shows the server's message", async () => {
    routes[`PUT ${base}/pages/X`] = () => json(422, { error: "A page needs a text." });
    renderArea("/settings/greyhawk/new-page?title=X");
    fireEvent.change(await screen.findByLabelText("Text"), { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Not saved: A page needs a text.")).toBeTruthy();
  });
});
