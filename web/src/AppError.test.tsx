import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import AppError from "./AppError";

function Broken(): never {
  throw new Error("Cannot read the map");
}

describe("AppError", () => {
  it("says a screen failed, with what went wrong and Reload", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const router = createMemoryRouter([{ path: "/", element: <Broken />, errorElement: <AppError /> }]);
    render(<RouterProvider router={router} />);
    expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeTruthy();
    expect(screen.getByText("Cannot read the map")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});
