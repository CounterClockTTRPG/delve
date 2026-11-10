import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, sent, stubFetch } from "../play/testing";
import { SetPasswordRoot } from "./SetPassword";

const TOKEN = "link-abc";
const ana = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false };

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderLink() {
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  render(
    <MemoryRouter initialEntries={[`/account/link/${TOKEN}`]}>
      <Routes>
        <Route path="/account/link/:token" element={<SetPasswordRoot />} />
      </Routes>
    </MemoryRouter>,
  );
  return assign;
}

function choose(password: string, again: string) {
  fireEvent.change(screen.getByTestId("link-password"), { target: { value: password } });
  fireEvent.change(screen.getByTestId("link-password-again"), { target: { value: again } });
  fireEvent.click(screen.getByTestId("link-submit"));
}

describe("SetPassword", () => {
  it("sets the password", async () => {
    const fetchMock = stubFetch({
      [`GET /api/account-links/${TOKEN}`]: () => json(200, { username: "ana", kind: "set-password" }),
      [`POST /api/account-links/${TOKEN}`]: () => json(200, { account: ana }),
    });
    const assign = renderLink();
    expect(await screen.findByRole("heading", { level: 1, name: "Choose your password" })).toBeTruthy();
    expect(await screen.findByText("ana")).toBeTruthy();
    choose("correct horse battery", "correct horse battery");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/home"));
    expect(sent(fetchMock, "POST", `/api/account-links/${TOKEN}`)).toEqual([{ password: "correct horse battery" }]);
  });

  it("refuses two different passwords", async () => {
    const fetchMock = stubFetch({
      [`GET /api/account-links/${TOKEN}`]: () => json(200, { username: "ana", kind: "reset-password" }),
    });
    renderLink();
    await screen.findByTestId("link-password");
    choose("correct horse battery", "correct horse batterY");
    expect((await screen.findByRole("alert")).textContent).toBe("The passwords differ.");
    expect(sent(fetchMock, "POST", `/api/account-links/${TOKEN}`)).toEqual([]);
  });

  it("says a used link doesn't work", async () => {
    stubFetch({
      [`GET /api/account-links/${TOKEN}`]: () => json(404, { error: "This link doesn't work: ask for a new one." }),
    });
    renderLink();
    expect((await screen.findByRole("alert")).textContent).toBe("This link doesn't work: ask for a new one.");
    expect(screen.queryByTestId("link-password")).toBeNull();
  });
});
