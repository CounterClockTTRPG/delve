import { fireEvent, screen } from "@testing-library/react";

/** Opens the row menu of `name` from the keyboard (jsdom has no pointer events) and answers its item `item`. */
export async function rowMenuItem(name: string, item: string): Promise<HTMLElement> {
  fireEvent.keyDown(await screen.findByRole("button", { name: `Actions for ${name}` }), { key: "Enter" });
  return screen.findByRole("menuitem", { name: item });
}

export async function chooseFromRowMenu(name: string, item: string): Promise<void> {
  fireEvent.click(await rowMenuItem(name, item));
}
