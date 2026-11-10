"""The help's pictures as WebP (DEL-212): each PNG `make help-shots` took in web/e2e/screenshots/help/, at most 1600
pixels wide, as web/public/help/<name>.webp, which the help topics show.

    uv run python scripts/help_images.py
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "web" / "e2e" / "screenshots" / "help"
OUT = ROOT / "web" / "public" / "help"
WIDEST = 1600


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for png in sorted(SHOTS.glob("*.png")):
        with Image.open(png) as picture:
            picture = picture.convert("RGB")
            if picture.width > WIDEST:
                picture = picture.resize((WIDEST, round(picture.height * WIDEST / picture.width)), Image.LANCZOS)
            target = OUT / f"{png.stem}.webp"
            picture.save(target, "WEBP", quality=82, method=6)
        print(f"{target.relative_to(ROOT)}  {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
