#!/usr/bin/env python3
"""Compara visualmente, slide a slide, las decks que cambiaron en un commit.

Levanta en local una página con la versión anterior (izquierda) y la nueva
(derecha), una lista de slides marcadas como igual / modificada / nueva /
eliminada / movida, y el diff del HTML de cada slide.

Ejemplos:
  python3 tools/comparar_decks.py                      # último commit (HEAD)
  python3 tools/comparar_decks.py--autor <texto> # último commit de esa persona
  python3 tools/comparar_decks.py --commit b497b65
  python3 tools/comparar_decks.py --base main~5 --commit main   # un rango
  python3 tools/comparar_decks.py --actual              # HEAD vs lo que tienes sin commitear
  python3 tools/comparar_decks.py --autor erick --solo-resumen   # sin servidor
"""
import argparse
import difflib
import html
import http.server
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NO_DECKS = {"shared", "_plantilla"}

TOKEN_RE = re.compile(r"<!--.*?-->|<section\s+class=\"slide[^\"]*\"[^>]*>.*?</section>", re.S)
LABEL_RE = re.compile(r"<!--\s*={10,}\s*(.*?)\s*-->", re.S)
TITLE_RE = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def git(*args, cwd=REPO):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def resolver_commit(args):
    if args.autor:
        sha = git("log", "-1", "-i", f"--author={args.autor}", "--format=%H")
        if not sha:
            autores = git("shortlog", "-sne", "--all")
            sys.exit(f"No hay commits de un autor que coincida con '{args.autor}'.\nAutores del repo:\n{autores}")
        return sha
    return git("rev-parse", args.commit)


def slides_de(texto):
    """Slides visibles (las comentadas no cuentan, igual que en deck.js)."""
    slides, etiqueta = [], ""
    for m in TOKEN_RE.finditer(texto):
        bloque = m.group(0)
        if bloque.startswith("<!--"):
            lab = LABEL_RE.fullmatch(bloque)
            if lab:
                etiqueta = lab.group(1)
            continue
        t = TITLE_RE.search(bloque)
        titulo = html.unescape(TAG_RE.sub("", t.group(1))).strip() if t else ""
        slides.append({
            "etiqueta": etiqueta,
            "titulo": re.sub(r"\s+", " ", titulo),
            "html": "\n".join(l.rstrip() for l in bloque.strip().splitlines()),
        })
        etiqueta = ""
    return slides


def normal(s):
    return re.sub(r"\s+", " ", s)


def alinear(antes, despues):
    """Devuelve filas {estado, a, d} con posiciones 1-based (None si no existe)."""
    na, nd = [normal(s["html"]) for s in antes], [normal(s["html"]) for s in despues]
    par_a, par_d = {}, {}
    for blk in difflib.SequenceMatcher(None, na, nd, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            par_a[blk.a + k], par_d[blk.b + k] = blk.b + k, blk.a + k
    libres_a = [i for i in range(len(antes)) if i not in par_a]
    libres_d = [j for j in range(len(despues)) if j not in par_d]
    candidatos = []
    for i in libres_a:
        for j in libres_d:
            r = difflib.SequenceMatcher(None, na[i], nd[j], autojunk=False).ratio()
            if antes[i]["titulo"] and antes[i]["titulo"] == despues[j]["titulo"]:
                r += 0.3
            if r >= 0.5:
                candidatos.append((r, i, j))
    for _, i, j in sorted(candidatos, reverse=True):
        if i not in par_a and j not in par_d:
            par_a[i], par_d[j] = j, i

    filas, ultima_a = [], -1
    for j in range(len(despues)):
        i = par_d.get(j)
        if i is not None:
            # eliminadas que estaban antes de esta slide en la versión anterior
            for k in range(ultima_a + 1, i):
                if k not in par_a:
                    filas.append({"estado": "eliminada", "a": k + 1, "d": None})
            if na[i] == nd[j]:
                estado = "igual" if i >= ultima_a else "movida"
            else:
                estado = "modificada" if i >= ultima_a else "movida y modificada"
            filas.append({"estado": estado, "a": i + 1, "d": j + 1})
            ultima_a = max(ultima_a, i)
        else:
            filas.append({"estado": "nueva", "a": None, "d": j + 1})
    for k in range(ultima_a + 1, len(antes)):
        if k not in par_a:
            filas.append({"estado": "eliminada", "a": k + 1, "d": None})
    for f in filas:
        sa = antes[f["a"] - 1] if f["a"] else None
        sd = despues[f["d"] - 1] if f["d"] else None
        ref = sd or sa
        f["etiqueta"], f["titulo"] = ref["etiqueta"], ref["titulo"]
        f["diff"] = "" if f["estado"] in ("igual", "movida") else "\n".join(difflib.unified_diff(
            (sa["html"] if sa else "").splitlines(), (sd["html"] if sd else "").splitlines(),
            "antes", "después", n=1, lineterm=""))
    return filas


def leer(raiz, rel):
    p = raiz / rel
    return p.read_text(encoding="utf-8") if p.exists() else None


def decks_cambiadas(base, commit, actual):
    rango = [base] if actual else [base, commit]
    ficheros = git("diff", "--name-only", *rango, "--", "presentaciones/").splitlines()
    if actual:
        ficheros += git("ls-files", "--others", "--exclude-standard", "--", "presentaciones/").splitlines()
    decks, otros = [], []
    for f in sorted(set(ficheros)):
        partes = f.split("/")
        if len(partes) >= 3 and partes[1] not in NO_DECKS:
            if partes[1] not in decks:
                decks.append(partes[1])
        else:
            otros.append(f)
    return decks, otros


PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Comparar decks</title>
<style>
*{box-sizing:border-box}
body{margin:0;font:13px system-ui,sans-serif;background:#1d1d1f;color:#eee;height:100vh;display:grid;grid-template-columns:300px 1fr;grid-template-rows:auto 1fr}
header{grid-column:1/3;padding:.5rem 1rem;border-bottom:1px solid #333;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
header b{color:#fff}header .m{color:#aaa}
select{background:#2a2a2d;color:#eee;border:1px solid #444;padding:.2rem}
aside{overflow:auto;border-right:1px solid #333}
aside .it{padding:.35rem .6rem;cursor:pointer;border-left:4px solid transparent;display:flex;gap:.5rem}
aside .it:hover{background:#2a2a2d}aside .it.sel{background:#34343a}
aside .n{color:#888;min-width:3.2rem;font-family:monospace}
aside .e{font-size:10px;text-transform:uppercase;letter-spacing:.05em}
.igual{border-color:#444!important}.igual .e{color:#777}
.modificada,.movida-y-modificada{border-color:#e3b341!important}.modificada .e,.movida-y-modificada .e{color:#e3b341}
.nueva{border-color:#3fb950!important}.nueva .e{color:#3fb950}
.eliminada{border-color:#f85149!important}.eliminada .e{color:#f85149}
.movida{border-color:#58a6ff!important}.movida .e{color:#58a6ff}
label.f{color:#aaa}
main{display:grid;grid-template-rows:1fr auto;overflow:hidden}
.vistas{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:6px;min-height:0}
.col{display:flex;flex-direction:column;min-height:0}.col h3{margin:0 0 4px;font-size:12px;color:#aaa;font-weight:500}
.marco{flex:1;position:relative;background:#000}
iframe{position:absolute;inset:0;width:100%;height:100%;border:0;background:#fff}
.vacio{position:absolute;inset:0;display:none;align-items:center;justify-content:center;color:#888;background:#111;font-size:15px}
pre{margin:0;max-height:32vh;overflow:auto;padding:.5rem 1rem;background:#111;border-top:1px solid #333;font-size:11.5px;white-space:pre-wrap}
pre .add{color:#3fb950}pre .del{color:#f85149}pre .hdr{color:#888}
</style></head><body>
<header>
  <b>Comparar decks</b>
  <span class="m" id="info"></span>
  <select id="deck"></select>
  <label class="f"><input type="checkbox" id="soloCambios" checked> solo cambios</label>
  <label class="f"><input type="checkbox" id="verDiff" checked> diff HTML</label>
  <span class="m">Navega con las flechas dentro de la derecha: la izquierda la sigue.</span>
</header>
<aside id="lista"></aside>
<main>
  <div class="vistas">
    <div class="col"><h3 id="tA"></h3><div class="marco"><iframe id="a"></iframe><div class="vacio" id="vA">No existe en la versión anterior</div></div></div>
    <div class="col"><h3 id="tB"></h3><div class="marco"><iframe id="b"></iframe><div class="vacio" id="vB">Eliminada en la versión nueva</div></div></div>
  </div>
  <pre id="diff"></pre>
</main>
<script>
const DATOS = __DATOS__;
const $ = (id) => document.getElementById(id);
const fa = $("a"), fb = $("b");
let deck = null, sel = null, ultimoHashB = "";

$("info").textContent = DATOS.titulo;
$("tA").textContent = "ANTES · " + DATOS.antes;
$("tB").textContent = "DESPUÉS · " + DATOS.despues;
DATOS.decks.forEach((d, i) => {
  const o = document.createElement("option");
  o.value = i; o.textContent = d.nombre + " (" + d.resumen + ")";
  $("deck").appendChild(o);
});

function cargarDeck(i) {
  deck = DATOS.decks[i];
  fa.src = deck.existeAntes ? "antes/presentaciones/" + (deck.dirAntes || deck.nombre) + "/index.html#1" : "about:blank";
  fb.src = deck.existeDespues ? "despues/presentaciones/" + (deck.dirDespues || deck.nombre) + "/index.html#1" : "about:blank";
  pintarLista();
  const primera = deck.filas.findIndex((f) => f.estado !== "igual");
  if (primera >= 0) setTimeout(() => elegir(primera), 400);
}

function pintarLista() {
  const cont = $("lista"); cont.innerHTML = "";
  deck.filas.forEach((f, k) => {
    if ($("soloCambios").checked && f.estado === "igual") return;
    const it = document.createElement("div");
    it.className = "it " + f.estado.replace(/ /g, "-") + (k === sel ? " sel" : "");
    const n = document.createElement("span"); n.className = "n";
    n.textContent = (f.a ?? "·") + "→" + (f.d ?? "·");
    const t = document.createElement("span");
    const e = document.createElement("div"); e.className = "e"; e.textContent = f.estado;
    const ti = document.createElement("div"); ti.textContent = f.titulo || f.etiqueta || "(sin titular)";
    t.append(e, ti); it.append(n, t);
    it.onclick = () => elegir(k);
    cont.appendChild(it);
  });
}

function ir(frame, n) {
  try { frame.contentWindow.location.hash = "#" + n; } catch (_) {}
}

function elegir(k) {
  sel = k;
  const f = deck.filas[k];
  $("vA").style.display = f.a ? "none" : "flex";
  $("vB").style.display = f.d ? "none" : "flex";
  if (f.a) ir(fa, f.a);
  if (f.d) { ir(fb, f.d); ultimoHashB = "#" + f.d; }
  pintarDiff(f.diff);
  pintarLista();
}

function pintarDiff(txt) {
  const pre = $("diff"); pre.innerHTML = "";
  pre.style.display = $("verDiff").checked && txt ? "block" : "none";
  (txt || "").split("\\n").forEach((l) => {
    const s = document.createElement("span");
    s.className = l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hdr" : "";
    s.textContent = l + "\\n";
    pre.appendChild(s);
  });
}

setInterval(() => {
  if (!deck || !deck.existeDespues) return;
  let h; try { h = fb.contentWindow.location.hash; } catch (_) { return; }
  if (!h || h === ultimoHashB) return;
  ultimoHashB = h;
  const n = parseInt(h.slice(1), 10);
  const k = deck.filas.findIndex((f) => f.d === n);
  if (k >= 0) elegir(k);
}, 250);

$("deck").onchange = (e) => cargarDeck(+e.target.value);
$("soloCambios").onchange = pintarLista;
$("verDiff").onchange = () => sel !== null && pintarDiff(deck.filas[sel].diff);
if (DATOS.decks.length) cargarDeck(0);
else $("lista").textContent = "Este cambio no toca ninguna deck.";
</script>
</body></html>
"""


def puerto_libre(preferido):
    for p in [preferido, 0]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return s.getsockname()[1]
            except OSError:
                continue


def comparar_carpetas(dir_a, dir_b, puerto, solo_resumen):
    rel = lambda d: f"presentaciones/{d}/index.html"
    ta, td = leer(REPO, rel(dir_a)), leer(REPO, rel(dir_b))
    if ta is None or td is None:
        sys.exit(f"No existe {rel(dir_a) if ta is None else rel(dir_b)}.")
    filas = alinear(slides_de(ta), slides_de(td))
    cuenta = {}
    for f in filas:
        cuenta[f["estado"]] = cuenta.get(f["estado"], 0) + 1
    resumen = ", ".join(f"{v} {k}" for k, v in cuenta.items() if k != "igual") or "sin cambios en slides"
    print(f"ANTES   {dir_a}\nDESPUÉS {dir_b}\n\n{resumen}")
    for f in filas:
        if f["estado"] != "igual":
            print(f"  {str(f['a'] or '·'):>3} → {str(f['d'] or '·'):<3} {f['estado']:<20} {f['titulo'] or f['etiqueta']}")
    if solo_resumen:
        return

    tmp = Path(tempfile.mkdtemp(prefix="comparar-decks-"))
    try:
        (tmp / "antes").symlink_to(REPO)
        (tmp / "despues").symlink_to(REPO)
        datos = {"titulo": f"{dir_a} → {dir_b}", "antes": dir_a, "despues": dir_b, "decks": [{
            "nombre": f"{dir_a} → {dir_b}", "dirAntes": dir_a, "dirDespues": dir_b,
            "existeAntes": True, "existeDespues": True, "filas": filas, "resumen": resumen}]}
        servir(tmp, datos, puerto)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def servir(tmp, datos, puerto):
    js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    (tmp / "index.html").write_text(PAGINA.replace("__DATOS__", js), encoding="utf-8")
    puerto = puerto_libre(puerto)
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp), **k)
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", puerto), handler)
    # el navegador corta los vídeos a medias al cambiar de slide: no es un error
    srv.handle_error = lambda *a: None
    print(f"\nComparador en http://127.0.0.1:{puerto}/  (Ctrl+C para cerrar y limpiar)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description="Compara visualmente las decks que cambió un commit.")
    ap.add_argument("--commit", default="HEAD", help="commit a revisar (por defecto HEAD)")
    ap.add_argument("--autor", help="usa el último commit cuyo autor (nombre o email) contenga este texto")
    ap.add_argument("--base", help="con qué comparar (por defecto, el padre del commit)")
    ap.add_argument("--actual", action="store_true", help="compara HEAD con tu copia de trabajo sin commitear")
    ap.add_argument("--deck", action="append", help="limita a esta deck (se puede repetir)")
    ap.add_argument("--puerto", type=int, default=8770)
    ap.add_argument("--solo-resumen", action="store_true", help="imprime el resumen y sale, sin servidor")
    ap.add_argument("--carpetas", nargs=2, metavar=("ANTES", "DESPUES"),
                    help="compara dos decks de la copia de trabajo (p. ej. dos versiones)")
    args = ap.parse_args()

    if args.carpetas:
        comparar_carpetas(*args.carpetas, args.puerto, args.solo_resumen)
        return

    if args.actual:
        commit, base = None, git("rev-parse", args.base or "HEAD")
    else:
        commit = resolver_commit(args)
        try:
            base = git("rev-parse", args.base or f"{commit}^")
        except subprocess.CalledProcessError:
            sys.exit("Ese commit no tiene padre: indica --base.")

    corto = lambda sha: git("log", "-1", "--format=%h %an · %ad · %s", "--date=short", sha)
    etiqueta_antes = corto(base)
    etiqueta_despues = "copia de trabajo (sin commitear)" if args.actual else corto(commit)

    decks, otros = decks_cambiadas(base, commit, args.actual)
    if args.deck:
        decks = [d for d in decks if d in args.deck]

    tmp = Path(tempfile.mkdtemp(prefix="comparar-decks-"))
    worktrees = []
    try:
        git("worktree", "add", "--detach", str(tmp / "antes"), base)
        worktrees.append(tmp / "antes")
        if args.actual:
            (tmp / "despues").symlink_to(REPO)
        else:
            git("worktree", "add", "--detach", str(tmp / "despues"), commit)
            worktrees.append(tmp / "despues")

        datos = {"titulo": "", "antes": etiqueta_antes, "despues": etiqueta_despues, "decks": []}
        print(f"ANTES   {etiqueta_antes}\nDESPUÉS {etiqueta_despues}\n")
        for d in decks:
            rel = f"presentaciones/{d}/index.html"
            ta, td = leer(tmp / "antes", rel), leer(tmp / "despues", rel)
            if ta is None and td is None:
                continue
            filas = alinear(slides_de(ta or ""), slides_de(td or ""))
            cuenta = {}
            for f in filas:
                cuenta[f["estado"]] = cuenta.get(f["estado"], 0) + 1
            resumen = ", ".join(f"{v} {k}" for k, v in cuenta.items() if k != "igual") or "sin cambios en slides"
            datos["decks"].append({"nombre": d, "existeAntes": ta is not None, "existeDespues": td is not None,
                                   "filas": filas, "resumen": resumen})
            print(f"{d}: {resumen}")
            for f in filas:
                if f["estado"] != "igual":
                    print(f"  {str(f['a'] or '·'):>3} → {str(f['d'] or '·'):<3} {f['estado']:<20} {f['titulo'] or f['etiqueta']}")
        if otros:
            print("\nOtros ficheros tocados en presentaciones/: " + ", ".join(otros))
        datos["titulo"] = f"{len(datos['decks'])} deck(s) con cambios"

        if args.solo_resumen:
            return
        servir(tmp, datos, args.puerto)
    finally:
        for w in worktrees:
            subprocess.run(["git", "worktree", "remove", "--force", str(w)], cwd=REPO, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=REPO, capture_output=True)


if __name__ == "__main__":
    main()
