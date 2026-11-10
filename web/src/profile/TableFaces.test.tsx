import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import TableFaces, { type TablePerson } from "./TableFaces";

afterEach(() => {
  vi.unstubAllGlobals();
});

const face = (id: string, name: string, role = "player"): TablePerson => ({
  seat_id: `seat_${id}`,
  name,
  role,
  profile: { account_id: `acc_${id}`, display_name: name, pronouns: "", avatar: { emblem: "lion" }, colour: "teal" },
});

function renderFaces(props: Parameters<typeof TableFaces>[0]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter>
          <TableFaces {...props} />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("TableFaces", () => {
  it("shows a face for each person, a blank for each open place, and the places taken", () => {
    renderFaces({ people: [face("a", "Raf", "host"), face("b", "Ana"), face("c", "Bo")], slots: 4, taken: 2 });
    const faces = screen.getByTestId("table-faces");
    expect(screen.getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Raf", "Ana", "Bo"]);
    expect(faces.querySelectorAll(".face-open")).toHaveLength(2);
    expect(faces.textContent).toContain("2/4 seats taken");
  });

  it("counts the people at a table without a limit, and shows nothing for a host alone", () => {
    const { unmount } = renderFaces({ people: [face("a", "Raf", "host"), face("b", "Ana")], slots: null, taken: 1 });
    expect(screen.getByTestId("table-faces").textContent).toContain("2 at the table");
    expect(document.querySelectorAll(".face-open")).toHaveLength(0);
    unmount();
    renderFaces({ people: [face("a", "Raf", "host")], slots: null, taken: 0 });
    expect(screen.queryByTestId("table-faces")).toBeNull();
  });

  it("opens a person's card; your own card offers to edit your profile", async () => {
    stubFetch({
      "GET /api/profiles/acc_b": () => json(200, { ...face("b", "Ana").profile, about: "likes maps" }),
      "GET /api/profiles/acc_a": () => json(200, { ...face("a", "Raf").profile, about: "", language: "en" }),
    });
    renderFaces({ people: [face("a", "Raf", "host"), face("b", "Ana")], slots: null, taken: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Ana" }));
    expect(await screen.findByText("likes maps")).toBeTruthy();
    expect(screen.queryByTestId("card-edit")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Raf" }));
    expect((await screen.findByTestId("card-edit")).getAttribute("href")).toBe("/preferences");
  });
});
