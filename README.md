# utd.edu.mx

Sitio web de la Universidad Tecnológica de Durango: sitio estático generado con
**Python** (Jinja2 + Markdown) y empaquetado con **Vite** (Tailwind CSS + FlyonUI).
Se publica en GitHub Pages con `actions/deploy-pages`.

```
content/ + templates/ ──build.py──▶ .site/ ──vite build──▶ dist/ ──▶ GitHub Pages (utd.edu.mx)
```

## Desarrollo

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npm install
PYTHON=.venv/bin/python npm run dev     # build.py --watch + servidor Vite en http://localhost:5173
```

Compilación completa (lo mismo que hace CI):

```bash
.venv/bin/python build.py && npm run build && npm run preview
```

`build.py` valida todo el contenido y termina con error si algo está mal (lista
todos los errores juntos). Los enlaces del menú que aún no tienen página solo
generan un aviso.

## Contenido (`content/`)

| Ruta | Qué es | Quién lo edita |
|---|---|---|
| `site.yaml` | Nombre, contacto, redes, menú y pie de página | A mano |
| `paginas/**/*.md` | Páginas institucionales; la ruta del archivo es la URL | A mano |
| `programas/<slug>.yaml` | Planes de estudio (mapa curricular, ciclos, salidas TSU) | `tools/extract_mcr.py` |
| `programas/<slug>.md` | Descripción e imagen del programa | A mano |
| `noticias/<año>/<AAAA-MM-DD-slug>.md` | Noticias; imágenes en la carpeta con el mismo nombre | Intranet (pull request) |
| `investigacion/cuerpos/*.md` | Cuerpos académicos y grupos de investigación | A mano |
| `investigacion/investigadores/*.md` | Perfil de cada investigador | Intranet (pull request) |
| `transparencia/conac.yaml` | Documentos CONAC por ejercicio y trimestre (página `/conac/`) | A mano |

`public/` se copia tal cual (CNAME, logo, fotos optimizadas).

### Noticia

```markdown
---
titulo: Convocatoria ELAP 2026-2027
fecha: 2026-10-30
categoria: Internacionalización
imagen: portada.jpg          # opcional, dentro de la carpeta 2026-10-30-convocatoria-elap/
resumen: Texto corto para tarjetas y RSS   # opcional
borrador: false              # true = no se publica
---

Cuerpo en Markdown…
```

## Herramientas (`tools/`, requieren `pip install -r requirements-tools.txt`)

- `extract_mcr.py ~/sistemaUTD/referencia`: extrae los mapas curriculares (MCR) a `content/programas/`.
- `logos.py`: genera los logotipos web y favicons (`public/media/logo-utd*.svg`, `favicon.*`, `apple-touch-icon.png`) a partir de `media-src/marca/logo-utd-completo.svg`.

## Publicación

`.github/workflows/deploy.yml`: los pull requests solo compilan (validan el
contenido); cada push a `main` compila y publica.

Configuración única en GitHub: **Settings → Pages → Source: GitHub Actions**, y
dominio personalizado `utd.edu.mx` (el archivo `public/CNAME` ya lo declara).
