import "./main.css";
import "flyonui/dist/collapse.mjs";

// A hello for whoever opens the browser console.
console.log(
  "%c¡Hola, curioso! %c\n\nSi abriste la consola, tienes lo que se necesita para estudiar en la UTD.\nTecnologías de la Información, Mecatrónica, Diseño Digital y más.\n\nOferta educativa: %s\nPreinscríbete:    %s",
  "font: 800 22px/1.4 sans-serif; color: #0b6b58",
  "font: 14px/1.5 sans-serif",
  `${location.origin}/oferta-educativa/`,
  `${location.origin}/aspirantes/preinscripcion/`,
);

// CONAC page: show one fiscal year at a time; searching filters documents across all years.
for (const root of document.querySelectorAll("[data-conac]")) {
  const years = root.querySelectorAll("[data-conac-ejercicio]");
  const buttons = root.querySelectorAll("[data-conac-anio]");
  const search = root.querySelector("[data-conac-buscar]");
  const status = root.querySelector("[data-conac-estado]");
  const empty = root.querySelector("[data-conac-vacio]");
  const fold = (s) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
  let year = buttons[0]?.dataset.conacAnio;
  const render = () => {
    const q = fold(search.value.trim());
    let found = 0;
    for (const y of years) {
      let inYear = 0;
      for (const p of y.querySelectorAll("[data-conac-periodo]")) {
        let inPeriod = 0;
        for (const li of p.querySelectorAll("[data-conac-doc]")) {
          const hit = !q || fold(li.textContent).includes(q);
          li.hidden = !hit;
          inPeriod += hit;
        }
        p.hidden = q && !inPeriod;
        if (q) p.open = inPeriod > 0;
        p.querySelector("[data-conac-cuenta]").textContent = `${inPeriod} documento${inPeriod === 1 ? "" : "s"}`;
        inYear += inPeriod;
      }
      y.hidden = q ? !inYear : y.dataset.conacEjercicio !== year;
      found += inYear;
    }
    for (const b of buttons) b.setAttribute("aria-pressed", String(!q && b.dataset.conacAnio === year));
    for (const b of buttons) {
      const on = !q && b.dataset.conacAnio === year;
      b.classList.toggle("btn-primary", on);
      b.classList.toggle("btn-outline", !on);
    }
    status.textContent = q ? `${found} documento${found === 1 ? "" : "s"} en todos los ejercicios` : "";
    empty.classList.toggle("hidden", !q || found > 0);
  };
  for (const b of buttons) b.addEventListener("click", () => { year = b.dataset.conacAnio; search.value = ""; render(); });
  search.addEventListener("input", render);
  if (location.hash && root.querySelector(`[data-conac-anio="${location.hash.slice(1)}"]`)) year = location.hash.slice(1);
  search.value = new URLSearchParams(location.search).get("q") ?? "";  // /conac/?q=actividades links to a search
  root.querySelector("[data-conac-controles]").hidden = false;
  render();
}

// Program pages: switch the curriculum map between TSU exits.
for (const group of document.querySelectorAll("[data-salidas]")) {
  const buttons = group.querySelectorAll("[data-salida-btn]");
  const panels = document.querySelectorAll(`[data-salida-panel="${group.dataset.salidas}"]`);
  const show = (slug) => {
    for (const b of buttons) b.setAttribute("aria-pressed", String(b.dataset.salidaBtn === slug));
    for (const p of panels) p.hidden = p.dataset.salida !== slug;
  };
  for (const b of buttons) b.addEventListener("click", () => show(b.dataset.salidaBtn));
}

// Galleries: open photos in a lightbox (←/→ to browse, Esc or click to close).
const lightbox = Object.assign(document.createElement("dialog"), { className: "lightbox" });
lightbox.innerHTML = '<img alt="">';
document.body.append(lightbox);
let current = [];
let index = 0;
const show = (i) => {
  index = (i + current.length) % current.length;
  lightbox.querySelector("img").src = current[index].href;
  lightbox.querySelector("img").alt = current[index].querySelector("img")?.alt ?? "";
};
for (const gallery of document.querySelectorAll(".galeria")) {
  const links = [...gallery.querySelectorAll("a")];
  links.forEach((a, i) => a.addEventListener("click", (e) => {
    e.preventDefault();
    current = links;
    show(i);
    lightbox.showModal();
  }));
}
lightbox.addEventListener("click", () => lightbox.close());
lightbox.addEventListener("keydown", (e) => {
  if (e.key === "ArrowRight") show(index + 1);
  if (e.key === "ArrowLeft") show(index - 1);
});

// Video buttons (<a data-video="YouTube id">): play in a modal instead of leaving the site.
// The player is only created on click and removed on close, which also stops the video.
const videoDialog = Object.assign(document.createElement("dialog"), { className: "video-modal" });
videoDialog.innerHTML = '<button type="button" class="video-close" aria-label="Cerrar video">✕</button><div class="video-frame"></div>';
document.body.append(videoDialog);
const closeVideo = () => videoDialog.close();
videoDialog.addEventListener("close", () => { videoDialog.querySelector(".video-frame").innerHTML = ""; });
videoDialog.querySelector(".video-close").addEventListener("click", closeVideo);
videoDialog.addEventListener("click", (e) => { if (e.target === videoDialog) closeVideo(); });
for (const link of document.querySelectorAll("[data-video]")) {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    const iframe = document.createElement("iframe");
    iframe.src = `https://www.youtube-nocookie.com/embed/${link.dataset.video}?autoplay=1&rel=0&modestbranding=1`;
    iframe.title = link.dataset.videoTitle || "Video";
    iframe.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    iframe.allowFullscreen = true;
    videoDialog.querySelector(".video-frame").append(iframe);
    videoDialog.showModal();
  });
}

// Lists with a search box: <input data-filter="#id"> filters [data-q] items inside #id.
for (const input of document.querySelectorAll("[data-filter]")) {
  const target = document.querySelector(input.dataset.filter);
  const norm = (s) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
  input.addEventListener("input", () => {
    const q = norm(input.value.trim());
    for (const el of target.querySelectorAll("[data-q]")) el.hidden = q && !norm(el.dataset.q).includes(q);
    for (const sec of target.querySelectorAll("[data-filter-group]")) {
      sec.hidden = ![...sec.querySelectorAll("[data-q]")].some((el) => !el.hidden);
    }
  });
}
