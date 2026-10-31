// Vite bundles the HTML that build.py writes into .site/ (CSS via Tailwind +
// FlyonUI, JS components) and emits the final site into dist/.
//
//   npm run dev    → runs `build.py --watch` and the Vite dev server together
//   npm run build  → expects build.py to have run first (CI does both)
import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

const SITE = resolve(import.meta.dirname, ".site");
const VENV = resolve(import.meta.dirname, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const PYTHON = process.env.PYTHON ?? (existsSync(VENV) ? VENV : process.platform === "win32" ? "python" : "python3");

// Every generated page is an entry point: .site/**/index.html (+ 404.html).
function pages() {
  const input = {};
  for (const f of readdirSync(SITE, { recursive: true })) {
    if (f.endsWith(".html") && !f.startsWith("public")) input[f.replace(/\.html$/, "")] = join(SITE, f);
  }
  return input;
}

// In dev, keep .site/ fresh: rerun build.py whenever content or templates change.
function pythonBuild() {
  let child;
  return {
    name: "python-build",
    apply: "serve",
    configureServer(server) {
      child = spawn(PYTHON, ["build.py", "--watch"], { cwd: import.meta.dirname, stdio: "inherit" });
      server.httpServer?.on("close", () => child.kill());
    },
  };
}

export default defineConfig(({ command }) => ({
  root: SITE,
  publicDir: join(SITE, "public"),
  plugins: [tailwindcss(), pythonBuild()],
  build: {
    outDir: resolve(import.meta.dirname, "dist"),
    emptyOutDir: true,
    rollupOptions: command === "build" ? { input: pages() } : undefined,
  },
}));
