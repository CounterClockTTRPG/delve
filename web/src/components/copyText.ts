// Copying to the clipboard, the one way every Copy button does it (DEL-174).

/**
 * Copies `text`: true once it is on the clipboard, false when the browser wouldn't, so the button says so rather than
 * "Copied". Without `navigator.clipboard` (a page on plain http at a LAN address) it tries the old selection copy.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    return false;
  }
  return selectionCopy(text);
}

function selectionCopy(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  try {
    area.select();
    return typeof document.execCommand === "function" && document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
  }
}
