import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import Avatar from "./Avatar";
import type { ProfileSummary } from "./api";

const ana: ProfileSummary = {
  account_id: "acc_00000000000a",
  display_name: "Ana",
  pronouns: "she/her",
  avatar: { emblem: "stag" },
  colour: "ember",
};

function renderAvatar(profile: ProfileSummary | null, onClick?: () => void) {
  return render(
    <I18nProvider language="en">
      <Avatar profile={profile} onClick={onClick} />
    </I18nProvider>,
  );
}

describe("Avatar", () => {
  it("shows the picture", () => {
    const { container } = renderAvatar({ ...ana, avatar: { picture: "0123456789ab" } });
    const img = container.querySelector("img")!;
    expect(img.getAttribute("src")).toBe("/api/profiles/acc_00000000000a/avatar?v=0123456789ab");
    expect(img.getAttribute("alt")).toBe("Ana");
    expect(container.querySelector("svg")).toBeNull();
    expect((container.firstChild as HTMLElement).dataset.colour).toBe("ember");
  });

  it("shows the emblem in the colour", () => {
    const { container } = renderAvatar(ana);
    const avatar = container.firstChild as HTMLElement;
    expect(avatar.dataset.colour).toBe("ember");
    expect(avatar.dataset.emblem).toBe("stag");
    expect(avatar.style.getPropertyValue("--avatar-colour")).toBe("#e08a3c");
    expect(avatar.querySelector("svg title")?.textContent).toBe("Ana");
    expect(avatar.style.width).toBe("32px");
  });

  it("a seat without a profile", () => {
    const { container } = renderAvatar(null);
    const avatar = container.firstChild as HTMLElement;
    expect(avatar.classList.contains("avatar-none")).toBe(true);
    expect(avatar.querySelector("svg, img")).toBeNull();
  });

  it("opens with a click when it may", () => {
    const onClick = vi.fn();
    renderAvatar(ana, onClick);
    fireEvent.click(screen.getByRole("button", { name: "Ana" }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});
