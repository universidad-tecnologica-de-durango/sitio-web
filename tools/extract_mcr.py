"""Extract the official curriculum maps (MCR PDFs) into content/programas/*.yaml.

Each MCR is one TSU exit of a licenciatura/ingeniería. Exits of the same
program (and modality: regular or BIS) are merged into one YAML file:
subjects shared by every exit go in `mapa`; the rest go under each exit in
`salidas_tsu[].asignaturas`.

Keys not generated here (campo_laboral, puestos, descripcion, ...) are kept
when the YAML already exists, so hand-written content survives re-runs; so is
`activa: false` on a TSU exit (authorized but not currently offered: not published)
`predeterminada: true` (the exit shown first) and `optativas` (real names of
Optativa I–III for that exit, taken from its PES).

Usage:
  python tools/extract_mcr.py ~/sistemaUTD/referencia [--out content/programas]
"""

import argparse
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pdfplumber
import yaml

ROW_TYPES = {1: "ingles", 2: "formacion", 3: "ciencias"}  # grid row -> subject type

# First cuatrimestre of every program, as defined by the university (overrides the MCR).
PRIMER_CUATRIMESTRE = [
    ["Introducción a la Lengua Inglesa", 225, "ingles"],
    ["Taller de Inglés", 150, "ingles"],
    ["Introducción a la Carrera", 45, "formacion"],
    ["Tutorías", 30, "formacion"],
]
PRIMER_CUATRIMESTRE_BIS = [
    ["Introducción a la Lengua Inglesa", 225, "ingles"],
    ["Taller de Inglés", 150, "ingles"],
    ["Desarrollo Sostenible", 60, "formacion"],
    ["Competencias Globales", 60, "formacion"],
    ["Tutorías", 30, "formacion"],
]

# Official names, keyed by the area folder in ~/sistemaUTD/referencia. The MCR
# title blocks are unreliable (some still say "XXXXXX"), so names live here.
PROGRAMS = {
    "ComercioExterior": "Licenciatura en Comercio Internacional y Aduanas",
    "DesarrolloDeNegocios": "Licenciatura en Negocios y Mercadotecnia",
    "DisenoDigitalYProduccionAudivisual": "Licenciatura en Diseño Digital y Producción Audiovisual",
    "Educacion": "Licenciatura en Educación",
    "EnergiaRenovable": "Ingeniería en Energía y Desarrollo Sostenible",
    "IngenieriaIndustrial": "Ingeniería Industrial",
    "LogisticaInternacion": "Ingeniería en Logística Internacional",
    "MantenimientoIndustrial": "Ingeniería en Mantenimiento Industrial",
    "Mecatronica": "Ingeniería Mecatrónica",
    "TecnologiasDeLaInformacion": "Ingeniería en Tecnologías de la Información e Innovación Digital",
}
# TSU exits, matched against the file's folder path.
TSU_NAMES = [
    ("CLASIFICACION", "Clasificación Arancelaria y Despacho Aduanero"),
    ("MERCADOTECNIA", "Mercadotecnia"),
    ("ANIMACION", "Diseño y Animación Digital"),
    ("IDIOMAINGLES", "Enseñanza del Idioma Inglés"),
    ("EDUCACION", "Enseñanza del Idioma Inglés"),
    ("TURBOSOLAR", "Energía Turbo Solar"),
    ("PROCESOSPRODUCTIVOS", "Procesos Productivos"),
    ("SISTEMASYTECNOLOGIAS", "Sistemas y Tecnologías Industriales"),
    ("MAQUINADOS", "Maquinados de Precisión"),
    ("OPERACIONESLOGISTICAS", "Operaciones Logísticas y Comercio Exterior"),
    ("SOLDADURA", "Mantenimiento en Soldadura"),
    ("MANTENIMIENTOINDUSTRIAL", "Mantenimiento Industrial"),
    ("ROBOTICA", "Robótica"),
    ("MANUFACTURAFLEXIBLE", "Sistemas de Manufactura Flexible"),
    ("SOFTWARE", "Desarrollo de Software Multiplataforma"),
    ("CIENCIADEDATOS", "Ciencia de Datos"),
    ("INTELIGENCIAARTIFICIAL", "Inteligencia Artificial"),
]


def tsu_name(path: Path) -> str:
    key = squash(str(path))
    return next((n for k, n in TSU_NAMES if k in key), "")
LOWER = {"y", "e", "o", "u", "de", "del", "la", "las", "el", "los", "en", "a", "al", "para", "por", "con", "sin", "su", "sus"}
UPPER = {"TI", "ID", "IA", "TPM", "RCM", "CAD", "CAM", "CNC", "PLC", "BIS", "TSU", "MIPYMES", "UX", "UI", "3D", "2D", "IOT", "ERP", "CRM", "SQL"}
ROMAN = re.compile(r"^(I{1,3}|IV|V|VI{0,3}|IX|X)$")


def squash(s: str) -> str:
    s = unicodedata.normalize("NFD", s.upper())
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def title_es(s: str) -> str:
    words = s.lower().split()
    out = []
    for i, w in enumerate(words):
        up = w.upper()
        if up in UPPER or ROMAN.match(up):
            out.append(up)
        elif i > 0 and w in LOWER:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def known_subjects(root: Path) -> dict[str, str]:
    """Subject names from the PROGRAMAS DE ASIGNATURA file names, keyed by squash()."""
    names = {}
    for f in root.rglob("*.pdf"):
        if "ASIGNATURA" in str(f.parent.parent).upper() or "ASIGNATURA" in str(f.parent).upper():
            n = re.sub(r"\s+", " ", f.stem).strip()
            names.setdefault(squash(n), n)
    return names


def hours_of(words, i) -> int | None:
    """Hours for the HRS token at index i: '75 HRS', '75HRS', '1,575 HRS.'."""
    w = words[i]
    m = re.match(r"^([\d,]+)\s*H\.?R?S", w["text"])
    if m:
        return int(m.group(1).replace(",", ""))
    # number token immediately to the left on the same line
    best = None
    for o in words:
        if abs(o["top"] - w["top"]) < 3 and o["x1"] <= w["x0"] + 1 and re.fullmatch(r"[\d,]+", o["text"]):
            if best is None or o["x1"] > best["x1"]:
                best = o
    return int(best["text"].replace(",", "")) if best else None


def text_in(page, x0, top, x1, bottom) -> str:
    """Text fully inside a box, one line per row, hyphen-split words left as-is."""
    box = page.within_bbox((max(0, x0), max(0, top), min(page.width, x1), min(page.height, bottom)))
    return re.sub(r"[ \t]+", " ", box.extract_text() or "").strip()


# Typos in the source PDFs and words split by line breaks inside the cells.
FIXES = [
    (r"\bDesarrolo\b", "Desarrollo"),
    (r"\bDel\s*pensamient\s*o\b", "del Pensamiento"),
    (r"\bDelpensamiento\b", "del Pensamiento"),
    (r"^RATADOS\b", "TRATADOS"),
    (r"\bINTERNACIONALE\b(?!\s+S\b)", "INTERNACIONALES"),
    (r"^CIENCIAS DE LOS MATERIALES$", "CIENCIA DE LOS MATERIALES"),
    (r"\bSOCIOEMOCIONA\s+LES\b", "SOCIOEMOCIONALES"),
    (r"\b(\w{4,}) (S|LES|DAD)\b", r"\1\2"),  # INTERNACIONALE S, PROCEDIMIENTO S, MULTICULTURALI DAD
]


def clean_name(raw: str, known) -> str:
    one = re.sub(r"\s+", " ", raw).strip()
    if squash(one) in known:
        return known[squash(one)]
    for pattern, repl in FIXES:
        one = re.sub(pattern, repl, one, flags=re.I)
    return known.get(squash(one), one)


def parse_grid(page, known):
    words = page.extract_words(use_text_flow=False)
    hrs = [i for i, w in enumerate(words) if re.search(r"H\.?R?S\.?$", w["text"])]
    rows = defaultdict(list)
    for i in hrs:
        rows[round(words[i]["top"] / 4)].append(i)  # 4 pt buckets
    heads = sorted((w for w in words if w["text"] in ("cuatrimestre", "Propedéutico")), key=lambda w: w["x0"])
    has_prop = any(w["text"] == "Propedéutico" for w in heads)
    header_y = max(w["bottom"] for w in words if "cuatrimestre" in w["text"].lower()) + 2

    # Term totals row: the HRS row with the most tokens, all >= 300 h.
    big = [k for k in rows if all((hours_of(words, i) or 0) >= 300 for i in rows[k]) and len(rows[k]) >= 2]
    tot_key = max(big, key=lambda k: (len(rows[k]), -k))
    totals = sorted(rows[tot_key], key=lambda i: words[i]["x0"])
    valor = sorted((w for w in words if "VALOR!" in w["text"]), key=lambda w: w["x0"])
    tot_y = min([words[i]["top"] for i in totals] + [w["top"] for w in valor])
    # Column centers from the totals row; a "#¡VALOR!" cell (spreadsheet error
    # in the source PDF) stands in for a missing total.
    # A total ("525 HRS") is centered near the start of "HRS"; an error cell on its own midpoint.
    cells = sorted([(words[i]["x0"] + 3, hours_of(words, i)) for i in totals] + [((w["x0"] + w["x1"]) / 2, None) for w in valor])
    centers = [x for x, _ in cells]
    term_hours = [h for _, h in cells]
    bounds = [0] + [(centers[j] + centers[j + 1]) / 2 for j in range(len(centers) - 1)] + [page.width]

    terms = []
    for c in range(len(centers)):
        # Read the whole column and split it at every "N HRS": the text before
        # each marker is one subject (estadía columns have no markers).
        text = text_in(page, bounds[c], header_y, bounds[c + 1], tot_y - 1)
        parts = re.split(r"([\d,]+)\s*H\.?R?S\b\.?", text)
        subjects = []
        for r, k in enumerate(range(1, len(parts), 2), start=1):
            raw = parts[k - 1].strip()
            raw = re.sub(r"(?s)^.*\bESTAD[IÍ]A\b", "", raw).strip() if "ESTAD" in raw else raw
            subjects.append({"name": title_es(clean_name(raw, known)), "raw": raw.replace("\n", " / "),
                             "hours": int(parts[k].replace(",", "")), "row": r})
        total = term_hours[c] if term_hours[c] is not None else sum(x["hours"] for x in subjects)
        terms.append({"numero": c if has_prop else c + 1, "hours": total, "subjects": subjects,
                      "total_leido": term_hours[c] is not None})

    # Cycles: 1 = up to the 3rd cuatrimestre (incl. propedéutico), 2 = up to the
    # first estadía (TSU), 3 = the rest. 1 crédito = 16 h in every map.
    first_est = next(t["numero"] for t in terms if not t["subjects"])
    groups = [[t for t in terms if t["numero"] <= 3], [t for t in terms if 3 < t["numero"] <= first_est],
              [t for t in terms if t["numero"] > first_est]]
    credits = [(sum(t["hours"] for t in g), round(sum(t["hours"] for t in g) / 16, 2)) for g in groups]
    return terms, credits


def layout_columns(lines, starts):
    """Slice fixed-width layout lines into columns starting at the given offsets."""
    cols = [[] for _ in starts]
    for ln in lines:
        for j, x in enumerate(starts):
            end = starts[j + 1] if j + 1 < len(starts) else None
            cols[j].append(ln[max(0, x - 2):end - 2 if end else None].strip())
    return [re.sub(r"\s+", " ", " ".join(c)).strip() for c in cols]


def parse_page2(path: Path):
    """TSU and licenciatura names and the cycle competencies, from the layout text of page 2."""
    out = subprocess.run(["pdftotext", "-layout", "-f", "2", "-l", "2", str(path), "-"],
                         capture_output=True, text=True).stdout
    lines = out.splitlines()
    tsu = lic = ""
    for i, ln in enumerate(lines):
        m = re.search(r"T[ÉE]CNICO SUPERIOR UNIVERSITARIO", ln)
        if m:
            right = re.search(r"(LICENCIATURA|INGENIER[ÍI]A)", ln[m.end():])
            split = m.end() + right.start() if right else len(ln)
            block = [l for l in lines[i:i + 4] if l.strip() and "Ciclo" not in l]
            tsu, lic = layout_columns(block, [m.start(), split])
            break
    cycles = []
    for i, ln in enumerate(lines):
        starts = [m.start() for m in re.finditer(r"Espec[ií]fica:", ln)]
        if len(starts) >= 2:
            end = next((k for k in range(i + 1, len(lines)) if re.search(r"^\s*(Base|Formaci[oó]n integral):", lines[k])), len(lines))
            for col in layout_columns(lines[i:end], starts):
                m = re.search(r"Espec[ií]fica:\s*(.+?)(?:Segunda Lengua:|$)", col)
                lvl = re.search(r"nivel\s+(A1\+?|A2\+?|B1\+?|B2|C1)", col)
                cycles.append({"competencia": m.group(1).strip() if m else None, "ingles": lvl.group(1) if lvl else None})
            break
    tsu = re.sub(r"^T[ÉE]CNICO SUPERIOR UNIVERSITARIO\s*", "TÉCNICO SUPERIOR UNIVERSITARIO ", tsu).strip()
    return tsu, lic, cycles


def parse_mcr(path: Path, known):
    with pdfplumber.open(path) as pdf:
        terms, credits = parse_grid(pdf.pages[0], known)
        tsu, lic, cycles = parse_page2(path)
        if not lic:
            lic = re.sub(r"\s+", " ", text_in(pdf.pages[0], 0, 0, pdf.pages[0].width, 60))
    return {"file": str(path), "bis": " BIS " in f" {path.name.upper()} ", "program": lic,
            "tsu": tsu, "terms": terms, "cycles": cycles, "credits": credits}


def subject_type(s):
    n = squash(s["name"])
    if n.startswith(("INGLES", "ENGLISH")):
        return "ingles"
    if n.startswith("PROYECTOINTEGRADOR"):
        return "proyecto"
    return ROW_TYPES.get(s["row"], "especifica")


def merge(maps, area):
    """Merge the exits of one program into the YAML structure."""
    first = maps[0]
    common, specific = {}, [defaultdict(list) for _ in maps]
    last = first["terms"][-1]["numero"]
    for t, term in enumerate(first["terms"]):
        num = term["numero"]
        sets = [[(s["name"], s["hours"]) for s in m["terms"][t]["subjects"]] for m in maps]
        shared = set(sets[0]).intersection(*map(set, sets[1:])) if len(sets) > 1 else set(sets[0])
        row = []
        placed = False
        for s in term["subjects"]:
            if (s["name"], s["hours"]) in shared:
                row.append([s["name"], s["hours"], subject_type(s)])
            elif not placed:
                row.append("salida")
                placed = True
        if num == 0:  # propedéutico: English plus BIS transversal courses
            row = [r if r == "salida" or r[2] == "ingles" else [r[0], r[1], "formacion"] for r in row]
        if not term["subjects"]:
            title = "Título de TSU" if num != last else f"Título de {'Ingeniería' if PROGRAMS[area].startswith('Ingenier') else 'Licenciatura'}"
            row = [[f"Estadía · {title}", term["hours"], "estadia"]]
        common[num] = row
        for k, m in enumerate(maps):
            for s in m["terms"][t]["subjects"]:
                if (s["name"], s["hours"]) not in shared:
                    specific[k][num].append([s["name"], s["hours"], subject_type(s)])
    total = sum(t["hours"] or 0 for t in first["terms"])
    credits = first["credits"]
    cycles = []
    for j, (h, c) in enumerate(credits):
        cy = first["cycles"][j] if j < len(first["cycles"]) else {}
        comp = cy.get("competencia")
        if len(maps) > 1 and j == 1:
            comp = "por_salida"
        cycles.append({"numero": j + 1, "horas": h, "creditos": c, "competencia": comp, "ingles": cy.get("ingles")})
    exits = []
    for k, m in enumerate(maps):
        exits.append({
            "slug": slugify(tsu_name(Path(m["file"]))) or f"salida-{k + 1}",
            "nombre": f"TSU en {tsu_name(Path(m['file']))}",
            "competencia": m["cycles"][1]["competencia"] if len(m["cycles"]) > 1 else None,
            "asignaturas": {t: v for t, v in specific[k].items()},
            "fuente": Path(m["file"]).name,
        })
    name = PROGRAMS[area]
    return {
        "slug": slugify(re.sub(r"^Licenciatura en ", "", name)) + ("-bis" if first["bis"] else ""),
        "nombre": re.sub(r"^Licenciatura en ", "", name),
        "nivel": "Ingeniería" if name.startswith("Ingenier") else "Licenciatura",
        "modelo": "Competencias profesionales",
        "plan": 2024,
        "bis": first["bis"],
        "cuatrimestres": sum(1 for t in first["terms"] if t["numero"] > 0),
        "propedeutico": any(t["numero"] == 0 for t in first["terms"]),
        "horas_totales": total,
        "creditos_totales": round(sum(c for _, c in credits), 2),
        "ciclos": cycles,
        "mapa": common,
        "salidas_tsu": exits,
    }


def check(m) -> list[str]:
    errs = []
    for t in m["terms"]:
        i = t["numero"]
        s = sum(x["hours"] or 0 for x in t["subjects"])
        if t["subjects"] and s != t["hours"]:
            errs.append(f"cuatrimestre {i}: asignaturas suman {s} h, total del mapa {t['hours']} h")
        for x in t["subjects"]:
            if x["hours"] is None or not x["raw"]:
                errs.append(f"cuatrimestre {i}: celda incompleta {x}")
    if m["terms"][-1]["subjects"]:
        errs.append("el último cuatrimestre no es la estadía")
    return errs


class Dumper(yaml.SafeDumper):
    """Subjects ([nombre, horas, tipo]) on one line each."""


Dumper.add_representer(list, lambda d, v: d.represent_sequence(
    "tag:yaml.org,2002:seq", v, flow_style=all(not isinstance(x, (list, dict)) for x in v)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "content" / "programas")
    args = ap.parse_args()

    known = known_subjects(args.root)
    files = sorted(f for f in args.root.rglob("*.pdf") if re.search(r"\bMCR\b", f.name) and not f.name.lower().startswith("copia"))
    groups, failed = defaultdict(list), 0
    for f in files:
        m = parse_mcr(f, known)
        errs = check(m)
        status = "OK " if not errs else "ERR"
        failed += bool(errs)
        print(f"{status} {f.relative_to(args.root)}")
        for e in errs:
            print(f"      {e}")
        groups[(f.relative_to(args.root).parts[0], m["bis"])].append(m)

    args.out.mkdir(parents=True, exist_ok=True)
    merged = {key: merge(maps, key[0]) for key, maps in groups.items()}
    for (area, bis), data in merged.items():
        # The first cuatrimestre is set by the university, not taken from the MCR
        # (the regular maps don't list it; the BIS maps list it as "propedéutico").
        rest = {k: v for k, v in data["mapa"].items() if k != 0}
        data["mapa"] = {0: [list(s) for s in (PRIMER_CUATRIMESTRE_BIS if bis else PRIMER_CUATRIMESTRE)], **rest}
        data.pop("propedeutico", None)
        hours = {n: sum(s[1] for s in subjects if isinstance(s, list)) +
                 max((sum(x[1] for x in e["asignaturas"].get(n, [])) for e in data["salidas_tsu"]), default=0)
                 for n, subjects in data["mapa"].items()}
        data["cuatrimestres"] = len(hours)
        data["ciclos"][0]["horas"] = sum(h for n, h in hours.items() if n <= 3)
        data["ciclos"][0]["creditos"] = round(data["ciclos"][0]["horas"] / 16, 2)
        data["horas_totales"] = sum(hours.values())
        data["creditos_totales"] = round(sum(c["creditos"] for c in data["ciclos"]), 2)
    for (area, bis), data in merged.items():
        maps = groups[(area, bis)]
        out = args.out / f"{data['slug']}.yaml"
        if out.exists():
            old = yaml.safe_load(out.read_text(encoding="utf-8")) or {}
            data = {**{k: v for k, v in old.items() if k not in data}, **data}
            flags = {e["slug"]: {k: e[k] for k in ("activa", "predeterminada", "optativas") if k in e} for e in old.get("salidas_tsu") or []}
            for e in data["salidas_tsu"]:  # per-exit flags set by hand (activa: false, predeterminada: true) survive
                e.update(flags.get(e["slug"], {}))
        header = "# Generado por tools/extract_mcr.py desde:\n" + "".join(f"#   {Path(m['file']).relative_to(args.root)}\n" for m in maps)
        out.write_text(header + yaml.dump(data, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")
        print(f"-> {out.name}: {len(maps)} salida(s) TSU")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
