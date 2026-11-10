import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Banner from "./Banner";

afterEach(cleanup);

describe("Banner", () => {
  it("shows the picture in a frame of the look's card edge, sized by its variant", () => {
    for (const variant of ["campaign", "thumb"] as const) {
      const { unmount } = render(<Banner src="/api/campaigns/cmp_1/banner" alt="Tuesday's banner" variant={variant} />);
      const img = screen.getByRole("img", { name: "Tuesday's banner" }) as HTMLImageElement;
      expect(img.getAttribute("src")).toBe("/api/campaigns/cmp_1/banner");
      const frame = img.closest(".banner")!;
      expect(frame.className).toBe(`banner banner-${variant}`);
      unmount();
    }
  });

  it("enlarges the campaign page's banner in a lightbox, and leaves the module page's small one to its link (DEL-234)", () => {
    const { unmount } = render(<Banner src="/api/campaigns/cmp_1/banner" alt="Tuesday's banner" variant="campaign" />);
    fireEvent.click(screen.getByRole("button", { name: "Tuesday's banner" }));
    const dialog = screen.getByRole("dialog", { name: "Tuesday's banner" });
    expect(dialog.querySelector("img")?.getAttribute("src")).toBe("/api/campaigns/cmp_1/banner");
    unmount();
    render(<Banner src="/x" alt="Small" variant="thumb" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
