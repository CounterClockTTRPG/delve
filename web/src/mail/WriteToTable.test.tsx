import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN, base, hostSeat, json, renderWith, seat, sent, stubFetch } from "../play/testing";
import WriteToTable from "./WriteToTable";

afterEach(() => vi.unstubAllGlobals());

const ana = seat("seat_00000000000a", "Ana");
const bob = seat("seat_00000000000b", "Bob");
const cy = seat("seat_00000000000c", "Cy", { role: "cohost" });
const obs = seat("seat_00000000000o", "Obs", { role: "observer" });
const table = [hostSeat, ana, bob, cy, obs];

function mailRoutes(extra = {}) {
  return stubFetch({
    "GET /api/mail/status": () => json(200, { enabled: true }),
    [`GET ${base}/mail/count`]: () => json(200, { count: 3 }),
    [`POST ${base}/mail`]: () => json(200, { sent: 3 }),
    ...extra,
  });
}

async function open() {
  renderWith(<WriteToTable campaignId={CAMPAIGN} seats={table} mySeatId={hostSeat.id} />);
  fireEvent.click(await screen.findByRole("button", { name: "Write to the table" }));
  return screen.findByRole("dialog");
}

describe("WriteToTable (DEL-314)", () => {
  it("is hidden while Delve sends no mail", async () => {
    const fetchMock = stubFetch({ "GET /api/mail/status": () => json(200, { enabled: false }) });
    renderWith(<WriteToTable campaignId={CAMPAIGN} seats={table} mySeatId={hostSeat.id} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Write to the table" })).toBeNull();
  });

  it("writes to everyone at the table, says how many get it, and how many it went to", async () => {
    const fetchMock = mailRoutes();
    const dialog = await open();
    expect((await within(dialog).findByTestId("write-count")).textContent).toBe("3 of them will get it by email");
    expect((within(dialog).getByLabelText("Everyone at the table") as HTMLInputElement).checked).toBe(true);
    const send = within(dialog).getByRole("button", { name: "Send" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText("Subject"), { target: { value: " Your character " } });
    fireEvent.change(within(dialog).getByLabelText("Message"), { target: { value: "A question\nfor you" } });
    fireEvent.click(send);
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/mail`)).toEqual([
        { subject: "Your character", message: "A question\nfor you", reply_to_me: false },
      ]),
    );
    expect((await screen.findByTestId("write-sent")).textContent).toBe("Sent by email to 3.");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("writes to the ticked players only, never the observers or the host, without a count, and lets them reply", async () => {
    const fetchMock = mailRoutes({ [`POST ${base}/mail`]: () => json(200, { sent: null }) });
    const dialog = await open();
    fireEvent.click(within(dialog).getByLabelText("Only the ones I tick"));
    expect(within(dialog).queryByLabelText("Obs")).toBeNull();
    expect(within(dialog).queryByLabelText("Raf")).toBeNull();
    expect(within(dialog).queryByTestId("write-count")).toBeNull();
    fireEvent.click(within(dialog).getByLabelText("Ana"));
    fireEvent.click(within(dialog).getByLabelText("Cy"));
    expect(within(dialog).queryByTestId("write-count")).toBeNull();
    fireEvent.click(within(dialog).getByLabelText("Let them reply to my address"));
    fireEvent.change(within(dialog).getByLabelText("Subject"), { target: { value: "Hi" } });
    fireEvent.change(within(dialog).getByLabelText("Message"), { target: { value: "Just you" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/mail`)).toEqual([
        { subject: "Hi", message: "Just you", seats: [ana.id, cy.id], reply_to_me: true },
      ]),
    );
    expect((await screen.findByTestId("write-sent")).textContent).toBe("Sent.");
    const counts = fetchMock.mock.calls.filter(([path]) => String(path).startsWith(`${base}/mail/count`));
    expect(counts.map(([path]) => path)).toEqual([`${base}/mail/count`]);
  });

  it("shows a refusal in the dialog and keeps the words", async () => {
    mailRoutes({ [`POST ${base}/mail`]: () => json(422, { error: "Add and confirm your own address first." }) });
    const dialog = await open();
    fireEvent.change(within(dialog).getByLabelText("Subject"), { target: { value: "Hi" } });
    fireEvent.change(within(dialog).getByLabelText("Message"), { target: { value: "Hello" } });
    fireEvent.click(within(dialog).getByLabelText("Let them reply to my address"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Send" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("Add and confirm your own address first.");
    expect((within(dialog).getByLabelText("Message") as HTMLTextAreaElement).value).toBe("Hello");
  });
});
