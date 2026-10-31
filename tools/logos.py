"""Generate the web logos and favicons from the vector source.

  python tools/logos.py

Source: media-src/marca/logo-utd-completo.svg (full logo: UTD mark + "Universidad
Tecnológica de Durango", lettering already outlined). Writes to public/:

  media/logo-utd-completo.svg   full logo (404 page)
  media/logo-utd.svg            mark only (header, footer)
  media/favicon.svg             "UT" on a white rounded square
  media/favicon.png             64 px fallback
  media/apple-touch-icon.png    180 px (iOS home screen)
  favicon.ico                   16/32/48 px, for tools that only ask for /favicon.ico

Needs inkscape and ImageMagick (convert) for the raster files.
"""

import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "media-src" / "marca" / "logo-utd-completo.svg"
MEDIA = ROOT / "public" / "media"

MARK_BOX = (186, 172, 482, 184)  # viewBox of the mark (the lettering sits below y = 360)
UT_BOX = (187.8, 173.9, 573.1, 354.6)  # extent of the U and T, without the gold D
D_FILLS = ("d37e18", "d3a113")  # the D and its highlight; its shadow is the multiply group


def optimize(svg: str) -> str:
    """Hex colors, 2–3 stops per gradient, 2-decimal coordinates, no whitespace."""
    def hexc(m):
        r, g, b = (round(float(x) * 2.55) for x in m.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    svg = re.sub(r"rgb\(([\d.]+)%,\s*([\d.]+)%,\s*([\d.]+)%\)", hexc, svg)

    def thin(m):  # the gradients are straight ramps: keep the ends and where a flat run starts sloping
        stops = re.findall(r'<stop offset="([\d.]+)" stop-color="(#[0-9a-f]{6})" stop-opacity="1"/>', m.group(2))
        keep = [stops[0]]
        for i in range(2, len(stops) - 1):
            if stops[i][1] != stops[i - 1][1] and stops[i - 1][1] == keep[-1][1] == stops[i - 2][1]:
                keep.append(stops[i - 1])
        keep.append(stops[-1])
        return m.group(1) + "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in keep) + m.group(3)
    svg = re.sub(r"(<linearGradient[^>]*>\n?)(.*?)(</linearGradient>)", thin, svg, flags=re.S)
    svg = re.sub(r"(\d+\.\d{2})\d+", r"\1", svg)
    svg = svg.replace(' fill-opacity="1"', "").replace(' fill-rule="nonzero"', "")
    svg = svg.replace('<?xml version="1.0" encoding="UTF-8"?>\n', "")
    return re.sub(r">\s+<", "><", svg).strip() + "\n"


def without_lettering(svg: str) -> str:
    def drop(m):
        y = float(re.search(r'd="M\s*[\d.]+\s+([\d.]+)', m.group(0)).group(1))
        return "" if y > 360 else m.group(0)
    svg = re.sub(r'<path fill-rule="nonzero" fill="rgb\([^"]+\)" fill-opacity="1" d="M[^"]*"/>\n', drop, svg)
    x, y, w, h = MARK_BOX
    return re.sub(r'width="\d+" height="\d+" viewBox="[^"]*"', f'width="{w}" height="{h}" viewBox="{x} {y} {w} {h}"', svg, count=1)


def ut_tile(mark: str, side: int = 440, radius: int = 88) -> str:
    svg = re.sub(r'<path fill="#(%s)"[^>]*/>' % "|".join(D_FILLS), "", mark)
    svg = re.sub(r'<g style="mix-blend-mode:multiply".*?</g></g></g>', "", svg, flags=re.S)
    x1, y1, x2, y2 = UT_BOX
    x0, y0 = (x1 + x2) / 2 - side / 2, (y1 + y2) / 2 - side / 2
    svg = re.sub(r"<svg [^>]*>", f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" '
                 f'viewBox="{x0:.1f} {y0:.1f} {side} {side}">', svg, count=1)
    return svg.replace("</defs>", f'</defs><rect x="{x0:.1f}" y="{y0:.1f}" width="{side}" height="{side}" rx="{radius}" fill="#fff"/>', 1)


def png(svg: Path, out: Path, width: int):
    subprocess.run(["inkscape", str(svg), "--export-type=png", f"--export-width={width}", "-o", str(out)],
                   check=True, capture_output=True)


def main():
    source = SOURCE.read_text(encoding="utf-8")
    files = {
        MEDIA / "logo-utd-completo.svg": optimize(source),
        MEDIA / "logo-utd.svg": optimize(without_lettering(source)),
    }
    files[MEDIA / "favicon.svg"] = ut_tile(files[MEDIA / "logo-utd.svg"])
    for path, svg in files.items():
        path.write_text(svg, encoding="utf-8")
        print(f"✓ {path.relative_to(ROOT)} ({len(svg.encode()) / 1024:.1f} KB)")

    fav = MEDIA / "favicon.svg"
    png(fav, MEDIA / "favicon.png", 64)
    png(fav, MEDIA / "apple-touch-icon.png", 180)
    with tempfile.TemporaryDirectory() as tmp:
        sizes = [Path(tmp) / f"{n}.png" for n in (16, 32, 48)]
        for p, n in zip(sizes, (16, 32, 48)):
            png(fav, p, n)
        subprocess.run(["convert", *map(str, sizes), str(ROOT / "public" / "favicon.ico")], check=True)
    print("✓ public/media/favicon.png, public/media/apple-touch-icon.png, public/favicon.ico")


if __name__ == "__main__":
    main()
