import { describe, expect, it } from "vitest";
import { translate } from "../i18n";
import { deviceLabel } from "./device";

const FIREFOX_LINUX = "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0";
const SAFARI_IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const CHROME_ANDROID =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36";
const EDGE_WINDOWS =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0";
const CHROME_MAC =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
const CHROME_IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0 Mobile/15E148 Safari/604.1";

describe("deviceLabel", () => {
  it("names the browser and the system", () => {
    expect(deviceLabel(FIREFOX_LINUX)).toBe("Firefox on Linux");
    expect(deviceLabel(SAFARI_IPHONE)).toBe("Safari on iPhone");
    expect(deviceLabel(CHROME_ANDROID)).toBe("Chrome on Android");
    expect(deviceLabel(EDGE_WINDOWS)).toBe("Edge on Windows");
    expect(deviceLabel(CHROME_MAC)).toBe("Chrome on macOS");
    expect(deviceLabel(CHROME_IPHONE)).toBe("Chrome on iPhone");
  });

  it("says A browser for anything else", () => {
    expect(deviceLabel("")).toBe("A browser");
    expect(deviceLabel("curl/8.5.0")).toBe("A browser");
  });

  it("speaks the reader's language", () => {
    const nl = (key: string, vars?: Record<string, string>) => translate("nl", key, vars);
    expect(deviceLabel(FIREFOX_LINUX, nl)).toBe("Firefox op Linux");
    expect(deviceLabel("", nl)).toBe("Een browser");
  });
});
