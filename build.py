"""Build the UTD website: content/ + templates/ -> .site/ (then `vite build` -> dist/).

    python build.py           build once; exits 1 if any content file is invalid
    python build.py --watch   rebuild on every change (used by `npm run dev`)

Content lives in content/ (see README.md). Every file is validated; all errors
are reported together so an intranet pull request shows everything wrong at once.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from email.utils import format_datetime
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

import frontmatter
import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
TEMPLATES = ROOT / "templates"
PUBLIC = ROOT / "public"
SITE = ROOT / ".site"      # what Vite serves and bundles
OUT = ROOT / ".site-tmp"   # each build writes here; only changed files are then synced into SITE

NEWS_PER_PAGE = 12
DAYS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO"]
SUBJECT_TYPES = {
    "ingles": "Inglés",
    "formacion": "Formación integral",
    "ciencias": "Ciencias básicas",
    "especifica": "Formación específica",
    "proyecto": "Proyecto integrador",
    "estadia": "Estadía en empresa",
}


# ---------------------------------------------------------------- models

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Link(Model):
    titulo: str
    url: str
    hijos: list[Link] = []
    imagen: str | None = None  # for menu sections: shown on the generated section page


class Site(Model):
    nombre: str
    nombre_corto: str
    url: str
    descripcion: str
    telefono: str
    direccion: str
    redes: dict[str, str]
    menu: list[Link]
    pie: list[Link]
    pie_legal: list[Link] = []
    sellos: list[Link] = []  # footer logo strip; each needs imagen


class Contacto(Model):
    area: str
    nombre: str = ""
    cargo: str = ""
    telefono: str = ""
    correo: str | None = None
    programas: list[str] = []  # program slugs (content/programas/<slug>.yaml)
    foto: str | None = None  # with a photo the contact is shown as a wide featured card
    enlace: Link | None = None

    @property
    def tel(self) -> str:  # "(618) 137-30-50" -> "+526181373050"
        return "+52" + re.sub(r"\D", "", self.telefono)[-10:]


class GrupoContactos(Model):
    grupo: str
    contactos: list[Contacto]


class Pagina(Model):
    titulo: str
    descripcion: str = ""
    imagen: str | None = None
    orden: int = 0
    directorio: list[GrupoContactos] = []  # contact cards, rendered after the page body


class Noticia(Model):
    titulo: str
    fecha: dt.date
    categoria: str
    resumen: str = ""
    imagen: str | None = None
    borrador: bool = False


class Clase(Model):
    dia: str
    hora: int = Field(ge=6, le=22)
    materia: str
    profesor: str = ""
    aula: str = ""

    @field_validator("dia")
    @classmethod
    def dia_valido(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in DAYS:
            raise ValueError(f"día desconocido {v!r}; usa {', '.join(DAYS)}")
        return v


class Grupo(Model):
    clave: str
    carrera: str
    grupo: str
    cuatrimestre: int = Field(ge=0, le=11)
    modalidad: str = ""


class DocumentoConac(Model):
    titulo: str
    url: HttpUrl


class PeriodoConac(Model):
    nombre: str  # "Primer trimestre" … "Cuarto trimestre" or "Documentos anuales"
    documentos: list[DocumentoConac]


class EjercicioConac(Model):
    anio: int = Field(ge=2000, le=2100)
    periodos: list[PeriodoConac]


class Conac(Model):
    ejercicios: list[EjercicioConac]


class HorarioPdf(Model):
    nombre: str
    clasica: HttpUrl | None = None
    bis: HttpUrl | None = None


class HorariosPdf(Model):
    programas: list[HorarioPdf]


class Proyecto(Model):
    titulo: str
    periodo: str = ""


class Cuerpo(Model):
    nombre: str
    tipo: Literal["Cuerpo académico", "Grupo disciplinar"]
    grado: Literal["En formación", "En consolidación", "Consolidado"] | None = None
    area: str = ""
    responsable: str = ""
    integrantes: list[str] = []  # full names; linked to investigadores/<slug(nombre)>.md when it exists
    colaboradores: list[str] = []
    lineas: list[str] = []
    proyectos: list[Proyecto] = []


class Investigador(Model):
    nombre: str
    grado: str = ""
    cuerpo: str | None = None  # slug of a cuerpo
    rol: Literal["Responsable", "Integrante", "Colaborador"] = "Integrante"
    programa: str = ""
    sni: str | None = None
    sei: bool = False
    prodep: bool = False
    correo: str | None = None
    orcid: str | None = None
    foto: str | None = None
    perfiles: list[Link] = []  # external profiles (Google Scholar, SNII, ResearchGate…)


# ---------------------------------------------------------------- helpers

class Errors(list):
    def check(self, path: Path, fn):
        try:
            return fn()
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"]) or "(archivo)"
                self.append(f"{path.relative_to(ROOT)}: {loc}: {err['msg']}")
        except (ValueError, KeyError, yaml.YAMLError) as e:
            self.append(f"{path.relative_to(ROOT)}: {e}")
        return None


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


MD = markdown.Markdown(extensions=["extra", "sane_lists", "toc", "smarty"])


def render_md(text: str) -> str:
    MD.reset()
    return MD.convert(text)


def read_md(path: Path):
    post = frontmatter.load(path)
    return post.metadata, render_md(post.content), post.content


def url(path: str = "") -> str:
    path = path.strip("/")
    return "/" if not path else f"/{path}/"


# ---------------------------------------------------------------- loaders

def load_paginas(errors: Errors):
    pages = []
    for f in sorted((CONTENT / "paginas").rglob("*.md")):
        meta, html, _ = read_md(f)
        p = errors.check(f, lambda: Pagina(**meta))
        if p:
            rel = f.relative_to(CONTENT / "paginas").with_suffix("")
            pages.append({"meta": p, "html": html, "path": rel.as_posix().removesuffix("/index")})
    return pages


def load_noticias(errors: Errors):
    news = []
    for f in sorted((CONTENT / "noticias").rglob("*.md")):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)", f.stem)
        if not m:
            errors.append(f"{f.relative_to(ROOT)}: el nombre debe ser AAAA-MM-DD-titulo.md")
            continue
        meta, html, raw = read_md(f)
        n = errors.check(f, lambda: Noticia(**meta))
        if not n or n.borrador:
            continue
        slug = m.group(2)
        assets = f.with_suffix("")  # folder with the same name holds its images
        path = f"noticias/{n.fecha.year}/{slug}"
        if n.imagen and not (assets / n.imagen).exists():
            errors.append(f"{f.relative_to(ROOT)}: no existe la imagen {assets.name}/{n.imagen}")
        resumen = n.resumen or re.sub(r"\s+", " ", re.sub(r"[#*_>\[\]()!]", "", raw)).strip()[:220]
        news.append({"meta": n, "html": html, "path": path, "slug": slug, "assets": assets,
                     "resumen": resumen, "imagen": url(path) + n.imagen if n.imagen else None})
    news.sort(key=lambda x: x["meta"].fecha, reverse=True)
    return news


def load_programas(errors: Errors):
    programs = {}
    for f in sorted((CONTENT / "programas").glob("*.yaml")):
        data = errors.check(f, lambda: yaml.safe_load(f.read_text(encoding="utf-8")))
        if not data:
            continue
        try:
            for key in ("slug", "nombre", "nivel", "mapa", "salidas_tsu", "ciclos"):
                data[key]
        except KeyError as e:
            errors.append(f"{f.relative_to(ROOT)}: falta la clave {e}")
            continue
        # Exits flagged `activa: false` stay in the YAML (the UTD is authorized to offer them) but aren't published.
        data["salidas_tsu"] = [s for s in data["salidas_tsu"] or [] if s.get("activa", True)]
        data["salidas_tsu"].sort(key=lambda s: not s.get("predeterminada", False))  # `predeterminada: true` is shown first
        md = f.with_suffix(".md")
        data["descripcion_html"] = ""
        if md.exists():
            meta, html, _ = read_md(md)
            data.update(meta)
            data["descripcion_html"] = html
        data["vista"] = programa_vista(data)
        # Electives with a catalog of options (e.g. Energía): list them below the map, with the term they fall in.
        terms = {a["nombre"]: t["numero"] for t in data["vista"][0]["cuatrimestres"] for a in t["asignaturas"]}
        data["optativas"] = [{"nombre": k, "cuatrimestre": terms.get(k), "opciones": v}
                             for k, v in (data.get("optativas_catalogo") or {}).items()]
        used = {a["tipo"] for t in data["vista"][0]["cuatrimestres"] for a in t["asignaturas"]}
        labels = {**SUBJECT_TYPES, "estadia": "Proyecto de investigación"} if data["nivel"] == "Maestría" else SUBJECT_TYPES
        data["leyenda"] = [(k, v) for k, v in labels.items() if k in used]
        programs[data["slug"]] = data
    # Pair each program with its BIS version: /oferta-educativa/<slug>/ and .../<slug>/bis/
    for slug, p in programs.items():
        base = slug.removesuffix("-bis")
        p["base"] = base
        p["path"] = f"oferta-educativa/{base}" + ("/bis" if p["bis"] else "")
        p["gemelo"] = programs.get(base if p["bis"] else f"{slug}-bis")
    for p in programs.values():  # a BIS program without its own photos uses the regular one's
        if p["gemelo"]:
            p.setdefault("imagen", p["gemelo"].get("imagen"))
            p.setdefault("galeria", p["gemelo"].get("galeria", []))
        for img in [p.get("imagen")] + [g["src"] for g in p.get("galeria", [])]:
            if img and not (PUBLIC / img.lstrip("/")).exists():
                errors.append(f"content/programas/{p['slug']}.md: no existe la imagen public{img}")
    return programs


def programa_vista(p):
    """Per TSU exit: the full map with that exit's subjects filled in."""
    last = max(int(k) for k in p["mapa"])
    offset = 1 if 0 in {int(k) for k in p["mapa"]} else 0
    exits = []
    # A master's degree has no TSU exits: render its single plan as one "exit".
    for s in p["salidas_tsu"] or [{"slug": "plan", "nombre": p["nombre"], "competencia": None, "asignaturas": {}}]:
        terms = []
        for num in sorted(p["mapa"], key=int):
            subjects = []
            for item in p["mapa"][num]:
                if item == "salida":
                    for name, hours, kind in s["asignaturas"].get(num, s["asignaturas"].get(int(num), [])):
                        subjects.append({"nombre": name, "horas": hours, "tipo": kind, "salida": True, "etiqueta": None})
                else:
                    name, hours, kind = item
                    real = (s.get("optativas") or {}).get(name)  # "Optativa I" → this exit's elective (from its PES)
                    subjects.append({"nombre": real or name, "horas": hours, "tipo": kind, "salida": bool(real),
                                     "etiqueta": name if real else None})
            n = int(num)
            shown = n + offset  # the MCR's "propedéutico" (0) is shown as the 1º cuatrimestre
            label = f"{shown}º cuatrimestre"
            estadia = all(x["tipo"] == "estadia" for x in subjects)
            terms.append({"numero": shown, "etiqueta": f"{shown}º" if estadia else label, "asignaturas": subjects, "estadia": estadia,
                          "horas": sum(x["horas"] for x in subjects), "final": n == last})
            if estadia and "tsu_cuatrimestre" not in p and n != last:
                p["tsu_cuatrimestre"] = shown
        # Estadía columns are slim (rotated text); subject columns share the rest.
        cols = ["3.25rem" if t["estadia"] else "minmax(7.5rem, 1fr)" for t in terms]
        min_width = sum(52 if t["estadia"] else 120 for t in terms) + 8 * (len(terms) - 1)
        exits.append({**s, "cuatrimestres": terms, "columnas": " ".join(cols), "ancho_min": min_width})
    return exits


def load_horarios(errors: Errors):
    """content/horarios/<periodo>/grupos.csv + one <clave>.csv per group."""
    periods = []
    for d in sorted((CONTENT / "horarios").glob("*/"), reverse=True):
        gfile = d / "grupos.csv"
        if not gfile.exists():
            errors.append(f"{d.relative_to(ROOT)}: falta grupos.csv")
            continue
        groups = []
        with gfile.open(encoding="utf-8") as fh:
            for i, row in enumerate(csv.DictReader(fh), start=2):
                g = errors.check(gfile, lambda: Grupo(**row))
                if not g:
                    continue
                cfile = d / f"{g.clave}.csv"
                if not cfile.exists():
                    errors.append(f"{gfile.relative_to(ROOT)}: línea {i}: falta {cfile.name}")
                    continue
                with cfile.open(encoding="utf-8") as ch:
                    clases = [c for c in (errors.check(cfile, lambda r=r: Clase(**r)) for r in csv.DictReader(ch)) if c]
                groups.append({"g": g, "clases": clases, "path": f"alumnos/horarios/{d.name}/{g.clave}"})
        periods.append({"periodo": d.name, "grupos": groups})
    return periods


def load_investigacion(errors: Errors):
    people = {}
    for f in sorted(f for f in (CONTENT / "investigacion" / "investigadores").glob("*.md") if f.name != "README.md"):
        meta, html, _ = read_md(f)
        p = errors.check(f, lambda: Investigador(**meta))
        if p:
            people[f.stem] = {"meta": p, "html": html, "slug": f.stem, "path": f"investigacion/investigadores/{f.stem}"}
    bodies = {}
    for f in sorted((CONTENT / "investigacion" / "cuerpos").glob("*.md")):
        meta, html, _ = read_md(f)
        c = errors.check(f, lambda: Cuerpo(**meta))
        if c:
            member = lambda m, rol: {**(people.get(slugify(m)) or {"meta": Investigador(nombre=m), "path": None}),
                                     "rol": "Responsable" if m == c.responsable else rol}
            members = [member(m, "Integrante") for m in c.integrantes] + [member(m, "Colaborador") for m in c.colaboradores]
            bodies[f.stem] = {"meta": c, "html": html, "slug": f.stem, "integrantes": members,
                              "path": f"investigacion/cuerpos-academicos/{f.stem}"}
    for p in people.values():
        if p["meta"].cuerpo and p["meta"].cuerpo not in bodies:
            errors.append(f"content/investigacion/investigadores/{p['slug']}.md: cuerpo desconocido {p['meta'].cuerpo!r}")
        p["cuerpo"] = bodies.get(p["meta"].cuerpo)
    for b in bodies.values():  # a body's area defaults to its leader's academic direction
        lead = people.get(slugify(b["meta"].responsable))
        b["area"] = b["meta"].area or (lead["meta"].programa if lead else "")
    return bodies, people


# ---------------------------------------------------------------- build

class Writer:
    def __init__(self, env, site):
        self.env, self.site, self.urls = env, site, []

    def page(self, path: str, template: str, **ctx):
        out = OUT / path / "index.html" if path else OUT / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.env.get_template(template).render(path=url(path), **ctx), encoding="utf-8")
        self.urls.append(url(path))


def build() -> list[str]:
    errors = Errors()
    site = errors.check(CONTENT / "site.yaml", lambda: Site(**yaml.safe_load((CONTENT / "site.yaml").read_text(encoding="utf-8"))))
    paginas = load_paginas(errors)
    noticias = load_noticias(errors)
    programas = load_programas(errors)
    horarios = load_horarios(errors)
    cuerpos, investigadores = load_investigacion(errors)
    for p in paginas:
        for g in p["meta"].directorio:
            for c in g.contactos:
                for slug in c.programas:
                    if slug not in programas:
                        errors.append(f"content/paginas/{p['path']}.md: programa desconocido {slug!r}")
    if errors or not site:
        return errors

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "src", OUT / "src")
    shutil.copytree(PUBLIC, OUT / "public") if PUBLIC.exists() else (OUT / "public").mkdir(parents=True)

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True)
    # "Oferta educativa" menu: regular programs grouped by level, one link each.
    niveles = {"Ingeniería": "Ingenierías", "Licenciatura": "Licenciaturas", "Maestría": "Maestrías"}
    oferta_menu = [(plural, [{"titulo": ("Licenciatura en " if p["nivel"] == "Licenciatura" else "") + p["nombre"], "url": url(p["path"])}
                             for p in sorted(programas.values(), key=lambda p: p["nombre"]) if p["nivel"] == nivel and not p["bis"]])
                   for nivel, plural in niveles.items()]
    env.globals.update(site=site, url=url, programas_por_slug=programas, oferta_menu=[g for g in oferta_menu if g[1]], year=dt.date.today().year, tipos=SUBJECT_TYPES, dias=DAYS)
    env.filters["fecha"] = lambda d: f"{d.day} {['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'][d.month - 1]} {d.year}"
    env.filters["miles"] = lambda n: f"{n:,}"
    env.filters["slug"] = slugify
    w = Writer(env, site)

    regulares = [p for p in programas.values() if not p["bis"]]
    w.page("", "inicio.html", noticias=noticias[:3], programas=regulares)

    for p in paginas:
        w.page(p["path"], "pagina.html", pagina=p)

    # Section landing pages (/alumnos/, /vinculacion/…) for menu entries without their own page.
    by_url = {url(p["path"]): p["meta"] for p in paginas}
    for item in site.menu:
        if item.hijos and item.url.startswith("/") and item.url not in by_url:
            cards = [{"titulo": h.titulo, "url": h.url, "externo": not h.url.startswith("/"),
                      "descripcion": by_url[h.url].descripcion if h.url in by_url else ""} for h in item.hijos]
            w.page(item.url.strip("/"), "seccion.html", seccion=item, tarjetas=cards)

    w.page("oferta-educativa", "programas.html", programas=sorted(regulares, key=lambda p: (p["nivel"], p["nombre"])))
    for p in programas.values():
        w.page(p["path"], "programa.html", p=p)

    pages = [noticias[i:i + NEWS_PER_PAGE] for i in range(0, len(noticias), NEWS_PER_PAGE)] or [[]]
    for i, chunk in enumerate(pages, start=1):
        w.page("noticias" if i == 1 else f"noticias/pagina/{i}", "noticias.html",
               noticias=chunk, pagina=i, paginas=len(pages), categoria=None)
    by_cat = defaultdict(list)
    for n in noticias:
        by_cat[n["meta"].categoria].append(n)
    for cat, items in by_cat.items():
        w.page(f"noticias/categoria/{slugify(cat)}", "noticias.html", noticias=items, pagina=1, paginas=1, categoria=cat)
    for n in noticias:
        w.page(n["path"], "noticia.html", n=n, recientes=[x for x in noticias if x is not n][:3])
        if n["assets"].is_dir():
            shutil.copytree(n["assets"], OUT / "public" / n["path"], dirs_exist_ok=True)

    pdfs_file = CONTENT / "horarios" / "pdfs.yaml"
    pdfs = errors.check(pdfs_file, lambda: HorariosPdf(**yaml.safe_load(pdfs_file.read_text(encoding="utf-8")))) if pdfs_file.exists() else None
    conac_file = CONTENT / "transparencia" / "conac.yaml"
    conac = errors.check(conac_file, lambda: Conac(**yaml.safe_load(conac_file.read_text(encoding="utf-8"))))
    if errors:
        return errors
    w.page("alumnos/horarios", "horarios.html", pdfs=pdfs.programas if pdfs else [])
    if conac:
        w.page("conac", "conac.html", ejercicios=sorted(conac.ejercicios, key=lambda e: e.anio, reverse=True))
    # Per-group pages (horario.html, from content/horarios/<periodo>/*.csv) are disabled for now;
    # the CSVs are still validated. Re-enable by rendering each g["path"] with tabla_horario(g["clases"]).

    w.page("investigacion", "investigacion.html", cuerpos=list(cuerpos.values()), investigadores=list(investigadores.values()))
    for c in cuerpos.values():
        w.page(c["path"], "cuerpo.html", c=c)
    for p in investigadores.values():
        w.page(p["path"], "investigador.html", inv=p)

    # Internal menu/footer links without a page yet: warn, don't fail.
    links = [l for item in site.menu + site.pie + site.pie_legal for l in [item, *item.hijos]]
    missing = sorted({l.url for l in links if l.url.startswith("/") and l.url not in w.urls})
    for m in missing:
        print(f"  aviso: el menú enlaza a {m}, que aún no tiene página", file=sys.stderr)

    (OUT / "404.html").write_text(env.get_template("404.html").render(path="/404/"), encoding="utf-8")
    write_sitemap(site, w.urls)
    write_feed(site, noticias)
    return []


def tabla_horario(clases):
    """Rows by hour, columns by day; consecutive identical classes merge (rowspan)."""
    used_days = [d for d in DAYS if any(c.dia == d for c in clases)] or DAYS[:5]
    hours = range(min(c.hora for c in clases), max(c.hora for c in clases) + 1) if clases else []
    cell = {(c.dia, c.hora): c for c in clases}
    rows, skip = [], set()
    for h in hours:
        row = []
        for d in used_days:
            if (d, h) in skip:
                continue
            c = cell.get((d, h))
            span = 1
            while c and (n := cell.get((d, h + span))) and (n.materia, n.profesor, n.aula) == (c.materia, c.profesor, c.aula):
                skip.add((d, h + span))
                span += 1
            row.append({"c": c, "span": span})
        rows.append({"hora": h, "celdas": row})
    return {"dias": used_days, "filas": rows}


def write_sitemap(site, urls):
    body = "".join(f"<url><loc>{escape(site.url.rstrip('/') + u)}</loc></url>" for u in urls)
    (OUT / "public" / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        encoding="utf-8")


def write_feed(site, noticias):
    items = "".join(
        f"<item><title>{escape(n['meta'].titulo)}</title><link>{site.url.rstrip('/')}{url(n['path'])}</link>"
        f"<guid>{site.url.rstrip('/')}{url(n['path'])}</guid>"
        f"<pubDate>{format_datetime(dt.datetime.combine(n['meta'].fecha, dt.time(12), dt.timezone.utc))}</pubDate>"
        f"<description>{escape(n['resumen'])}</description></item>" for n in noticias[:20])
    (OUT / "public" / "feed.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{escape(site.nombre)} · Noticias</title>'
        f"<link>{site.url}</link><description>{escape(site.descripcion)}</description><language>es-mx</language>{items}</channel></rss>",
        encoding="utf-8")


def sync(src: Path, dst: Path) -> int:
    """Make dst match src, touching only files that changed (keeps Vite's watcher calm)."""
    changed, keep = 0, set()
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        rel = f.relative_to(src)
        keep.add(rel)
        target = dst / rel
        if not target.exists() or target.read_bytes() != f.read_bytes():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            changed += 1
    if dst.exists():
        for f in sorted(dst.rglob("*"), reverse=True):
            rel = f.relative_to(dst)
            if f.is_file() and rel not in keep:
                f.unlink()
                changed += 1
            elif f.is_dir() and not any(f.iterdir()):
                f.rmdir()
    shutil.rmtree(src)
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watch", action="store_true", help="rebuild when content/, templates/, public/ or src/ change")
    args = ap.parse_args()

    def run() -> bool:
        errors = build()
        if errors:
            shutil.rmtree(OUT, ignore_errors=True)
            print(f"✗ {len(errors)} error(es) en el contenido:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return False
        changed = sync(OUT, SITE)
        print(f"✓ sitio generado en {SITE.relative_to(ROOT)}/ ({changed} archivo(s) actualizados)", flush=True)
        return True

    ok = run()
    if not args.watch:
        sys.exit(0 if ok else 1)
    from watchfiles import watch
    for _ in watch(CONTENT, TEMPLATES, PUBLIC, ROOT / "src", ROOT / "build.py"):
        run()


if __name__ == "__main__":
    main()
