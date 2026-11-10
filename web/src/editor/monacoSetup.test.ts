import { afterEach, describe, expect, it, vi } from "vitest";

const config = vi.fn();

vi.mock("@monaco-editor/react", () => ({ loader: { config } }));
// The real package needs a browser with workers; the bundle is what's under test here.
vi.mock("monaco-editor", () => ({ editor: {}, languages: {}, isFakeMonaco: true }));
vi.mock("monaco-editor/esm/vs/editor/editor.worker?worker", () => ({
  default: class FakeEditorWorker {},
}));

afterEach(() => {
  vi.resetModules();
  config.mockClear();
});

describe("monacoSetup", () => {
  it("hands the bundled monaco to the loader, with no CDN path", async () => {
    await import("./monacoSetup");

    expect(config).toHaveBeenCalledTimes(1);
    const arg = config.mock.calls[0][0] as Record<string, unknown>;
    expect((arg.monaco as { isFakeMonaco?: boolean }).isFakeMonaco).toBe(true);
    expect(arg.paths).toBeUndefined();
    const { monaco: _bundled, ...rest } = arg;
    expect(JSON.stringify(rest)).not.toMatch(/https?:|cdn|jsdelivr/i);
  });

  it("serves the editor worker from the bundle", async () => {
    await import("./monacoSetup");
    const env = (self as unknown as { MonacoEnvironment: { getWorker: (id: string, label: string) => unknown } })
      .MonacoEnvironment;
    expect((env.getWorker("x", "editorWorkerService") as object).constructor.name).toBe("FakeEditorWorker");
  });
});
