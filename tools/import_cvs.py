"""Create researcher profiles from the teacher CVs (HTML) for members of research bodies.

  python tools/import_cvs.py ~/Dropbox/SEAES_2026_DA/reporte_2026/perfiles_docentes

Reads the members of every content/investigacion/cuerpos/*.md (responsable,
integrantes, colaboradores), finds each one's "CV <clave> <NOMBRE>.html" and writes
content/investigacion/investigadores/<slug>.md. Files are regenerated on every run.

Only the public academic profile is published: education (without cédula or
thesis notes) and research output. Languages, certifications, CONOCER standards,
professional experience, employee numbers, folios, courses, committees and the
list of supervised student reports are left out.

A photo at public/media/investigadores/<slug>.jpg is picked up as the profile's foto.
Hand-added foto, orcid and perfiles (external profile links) are kept on re-import, and
hand-written profiles of members without a CV are left untouched.
"""

import argparse
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import frontmatter
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CUERPOS = ROOT / "content" / "investigacion" / "cuerpos"
OUT = ROOT / "content" / "investigacion" / "investigadores"
FOTOS = ROOT / "public" / "media" / "investigadores"
MANUAL = ("foto", "orcid", "perfiles")  # front-matter keys edited by hand, not from the CVs

DIRECCIONES = {
    "MITI": "Mantenimiento Industrial y Tecnologías de la Información",
    "DN-DD": "Desarrollo de Negocios y Diseño Digital",
    "MT-LI-ENRE": "Mecatrónica, Lengua Inglesa y Energías Renovables",
    "OLCE-CADA-LOG-PI-IND": "Operaciones Logísticas, Comercio Internacional e Ingeniería Industrial",
    "CADA-OLCE-PP": "Operaciones Logísticas, Comercio Internacional e Ingeniería Industrial",
    "OLCE-CADA-LOG": "Operaciones Logísticas, Comercio Internacional e Ingeniería Industrial",
}
TITLES = {"DR", "DRA", "MTRO", "MTRA", "ING", "LIC", "MATSI", "MTI", "DADE", "MC", "ME"}
LOWER = {"y", "e", "o", "u", "de", "del", "la", "las", "el", "los", "en", "a", "al", "para", "por", "con", "sin"}
LEVELS = [("Posdoctorado", 6), ("Doctorado", 5), ("Maestr", 4), ("Especialidad", 3)]


def tokens(name: str) -> set[str]:
    s = unicodedata.normalize("NFD", name.upper())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return set(re.findall(r"[A-Z]+", s)) - TITLES


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def tidy(s: str) -> str:
    """Collapse whitespace; sentence-case text written in ALL CAPS."""
    s = re.sub(r"\s+", " ", s or "").strip().strip('"“”').strip()
    letters = [c for c in s if c.isalpha()]
    if letters and len(s.split()) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        words = s.lower().split()
        s = " ".join(w if i and w in LOWER else w[:1].upper() + w[1:] for i, w in enumerate(words))
    return s


def year(s: str) -> str:
    m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", s or "")
    return m.group(1) if m else ""


def sections(soup):
    """{section title: [{izq, anio, t, s}]} from the h2 + table layout of the CVs."""
    out = {}
    for h in soup.find_all("h2"):
        table = h.find_next_sibling()
        if not table or table.name != "table":
            continue
        rows = []
        for tr in table.find_all("tr"):
            izq = tr.select_one(".izq")
            row = {"izq": tidy(izq.get_text(" ", strip=True)) if izq else ""}
            for span in tr.select(".der span[class]"):
                row[span["class"][0]] = span.get_text(" ", strip=True)
            rows.append(row)
        out[re.sub(r"\s*\(\d+\)$", "", h.get_text(strip=True))] = rows
    return out


def profile(path: Path, member: str, cuerpo: str, rol: str):
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    name = member  # the research-body file spells names with accents; CVs often don't
    lema = tidy(soup.select_one(".lema").get_text(" ", strip=True)) if soup.select_one(".lema") else ""
    datos = [d.strip() for d in (soup.select_one(".datos").get_text(" ", strip=True) if soup.select_one(".datos") else "").split("·")]
    sec = sections(soup)

    degrees = [r for r in sec.get("Educación", []) if r.get("t") and r["izq"]]  # rows without status are notes
    grado = max(degrees, key=lambda r: next((v for k, v in LEVELS if tidy(r["t"]).startswith(k)), 1), default=None)
    sni = next((d for d in datos if d.startswith("SNI") and d.lower() != "sni no"), None)
    correo = next((d for d in datos if d.endswith("@utd.edu.mx")), None)
    meta = {
        "nombre": name,
        "grado": (tidy(grado["t"]) + (" (en curso)" if grado["izq"].lower().startswith("cursando") else "")) if grado else "",
        "cuerpo": cuerpo,
        "rol": rol,
        "programa": DIRECCIONES.get(datos[0], "") if datos else "",  # unknown codes/placeholders are dropped
        "sni": sni.replace("SNI ", "") if sni else None,
        "sei": "SEI" in datos,
        "prodep": any("PRODEP" in d for d in datos),
        "correo": correo,
    }

    # Public profiles show only academic background and research output.
    md = [lema, ""] if lema else []
    if degrees:
        md += ["## Formación académica", ""]
        for r in degrees:
            status = "" if r["izq"].lower().startswith("titulad") else f" ({r['izq'].lower()})"
            y = year(r.get("anio"))
            place = tidy(r.get("s", ""))
            md.append(f"- **{tidy(r['t'])}**" + "".join(f", {x}" for x in (place, y) if x) + status)
        md.append("")
    output = defaultdict(list)
    for r in sec.get("Investigación y producción académica", []):
        if r.get("t"):
            output[r["izq"] or "Otros"].append(r)
    if output:
        md += ["## Investigación y producción académica", ""]
        for kind, rows in output.items():
            md += [f"### {kind}", ""]
            for r in sorted(rows, key=lambda r: year(r.get("anio")), reverse=True):
                y = year(r.get("anio"))
                src = tidy(r.get("s", "")).rstrip(",")
                md.append(f"- {tidy(r['t'])}." + (f" *{src}*" if src else "") + (f", {y}." if y else ""))
            md.append("")
    supervised = sum(len(v) for k, v in sec.items() if k.startswith("Dirección de tesis"))
    if supervised:
        md += [f"Ha dirigido {supervised} memorias de estadía de estudiantes de la UTD.", ""]
    return name, meta, "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cvs", type=Path)
    args = ap.parse_args()

    cvs = {f: tokens(re.sub(r"^(Ejemplo - )?CV \d+ ", "", f.stem)) for f in args.cvs.glob("*.html")}
    OUT.mkdir(parents=True, exist_ok=True)
    manual = {}  # hand-added front matter that the CVs don't have, kept across runs
    previous = [f for f in OUT.glob("*.md") if f.name != "README.md"]
    for old in previous:
        meta = frontmatter.load(old).metadata
        manual[old.stem] = {k: meta[k] for k in MANUAL if k in meta}
        if meta.get("sni") not in (None, "Por confirmar"):
            manual[old.stem]["sni_previo"] = meta["sni"]
        if meta.get("sei"):  # SEI marked by hand stays even if the CV doesn't say it
            manual[old.stem]["sei"] = True
    written = set()
    missing = []
    for c in sorted(CUERPOS.glob("*.md")):
        meta = frontmatter.load(c).metadata
        members = [(m, "Responsable" if m == meta.get("responsable") else "Integrante") for m in meta.get("integrantes", [])]
        members += [(m, "Colaborador") for m in meta.get("colaboradores", [])]
        for member, rol in members:
            t = tokens(member)
            match = [f for f, ft in cvs.items() if t <= ft]
            if not match:
                missing.append(f"{member} ({meta['nombre']})")
                continue
            name, fm, body = profile(match[0], member, c.stem, rol)
            foto = FOTOS / f"{slugify(member)}.jpg"  # photos survive re-imports: drop one in public/media/investigadores/
            fm["foto"] = f"/media/investigadores/{foto.name}" if foto.exists() else None
            kept = dict(manual.get(slugify(member), {}))
            previo = kept.pop("sni_previo", None)
            if previo and fm.get("sni") in (None, "Por confirmar"):  # a level verified by hand beats an unconfirmed CV
                fm["sni"] = previo
            fm.update(kept)
            fm = {k: v for k, v in fm.items() if v not in (None, "", False)}
            out = OUT / f"{slugify(member)}.md"
            out.write_text("---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body, encoding="utf-8")
            written.add(out.stem)
            print(f"✓ {out.name:45} ← {match[0].name}")
    # Members without a CV keep their hand-written profile; people who left every body are removed.
    current = set()
    for c in CUERPOS.glob("*.md"):
        meta = frontmatter.load(c).metadata
        current |= {slugify(m) for m in [meta.get("responsable") or ""] + meta.get("integrantes", []) + meta.get("colaboradores", []) if m}
    for old in previous:
        if old.stem not in written and old.stem not in current:
            old.unlink()
            print(f"  eliminado: {old.name}")
    for m in missing:
        print(f"  sin CV: {m}")


if __name__ == "__main__":
    main()
