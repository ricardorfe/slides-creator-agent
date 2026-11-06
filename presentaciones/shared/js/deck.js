/* ============================================================
   deck.js — Navegador de slides minimalista (sin dependencias)
   ------------------------------------------------------------
   Funciones:
   - Una slide visible a la vez (.is-active)
   - Teclado: → / Espacio / ↓ avanzan · ← / ↑ retroceden
              Home / End saltan al principio / final
              f = pantalla completa · o = vista general
   - Fragmentos: elementos con class="fragment" se revelan por pasos
   - Sincroniza el nº de slide con el hash de la URL (#5)
   - Contador "actual / total"
   - Clic en la franja derecha (17 %) avanza, en la izquierda retrocede;
     el centro no navega
   - Botón de ojo por slide: respeta .slide--hidden del HTML y guarda
     excepciones locales en localStorage
   ============================================================ */
(function () {
  "use strict";

  const slides = Array.from(document.querySelectorAll(".slide"));
  const counterCurrent = document.querySelector(".slide-counter .current");
  const counterTotal = document.querySelector(".slide-counter .total");
  if (!slides.length) return;

  let current = 0; // índice de slide
  let step = 0;    // fragmento actual dentro de la slide

  function fragmentsOf(i) {
    return Array.from(slides[i].querySelectorAll(".fragment"));
  }

  function render() {
    slides.forEach((s, i) => s.classList.toggle("is-active", i === current));
    // Una slide oculta sigue reproduciendo audio: se pausa al salir
    slides.forEach((s, i) => {
      if (i !== current) s.querySelectorAll("video").forEach((v) => v.pause());
    });

    const frags = fragmentsOf(current);
    frags.forEach((f, idx) => f.classList.toggle("is-visible", idx < step));

    if (counterCurrent || counterTotal) {
      // En pantalla completa el contador solo cuenta las slides que se proyectan
      const shown = presenting() ? slides.filter((_, i) => !isSkipped(i) || i === current) : slides;
      if (counterCurrent) counterCurrent.textContent = String(shown.indexOf(slides[current]) + 1);
      if (counterTotal) counterTotal.textContent = String(shown.length);
    }

    const hash = "#" + (current + 1);
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }

  function goTo(i, opts) {
    current = Math.max(0, Math.min(slides.length - 1, i));
    // al entrar en una slide: por defecto sin fragmentos revelados;
    // si venimos hacia atrás, mostramos todos
    step = opts && opts.end ? fragmentsOf(current).length : 0;
    render();
  }

  function presenting() {
    return Boolean(document.fullscreenElement);
  }

  function isSkipped(i) {
    return slides[i].classList.contains("is-skipped");
  }

  // Siguiente slide en la dirección dir (+1/-1), saltando las ocultas si se está presentando
  function stepFrom(i, dir) {
    let j = i + dir;
    while (j >= 0 && j < slides.length && presenting() && isSkipped(j)) j += dir;
    return j;
  }

  function next() {
    const frags = fragmentsOf(current);
    if (step < frags.length) {
      step++;
      render();
    } else {
      const j = stepFrom(current, 1);
      if (j < slides.length) goTo(j);
    }
  }

  function prev() {
    if (step > 0) {
      step--;
      render();
    } else {
      const j = stepFrom(current, -1);
      if (j >= 0) goTo(j, { end: true });
    }
  }

  function toggleFullscreen() {
    const action = document.fullscreenElement
      ? document.exitFullscreen()
      : document.documentElement.requestFullscreen
        ? document.documentElement.requestFullscreen({ navigationUI: "hide" })
        : null;
    if (action && typeof action.catch === "function") action.catch(() => {});
  }

  const fullscreenButtons = slides.map((slide) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "slide-fullscreen";
    button.textContent = "⛶";
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFullscreen();
    });
    slide.appendChild(button);
    return button;
  });

  /* ---------- Volver al índice ---------- */
  const HOME = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/></svg>';
  const homeButtons = slides.map((slide) => {
    const link = document.createElement("a");
    link.className = "slide-home";
    link.href = "../index.html";
    link.innerHTML = HOME;
    link.setAttribute("aria-label", "Ir al índice de presentaciones");
    link.title = "Ir al índice de presentaciones";
    slide.appendChild(link);
    return link;
  });

  /* ---------- Ocultar slides en pantalla completa ---------- */
  const EYE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>';
  const EYE_ON = EYE + "</svg>";
  const EYE_OFF = EYE + '<line x1="3" y1="3" x2="21" y2="21"/></svg>';
  const hiddenStoreKey = "deck-hidden:" + location.pathname;
  // Se identifica cada slide por su titular: así sobrevive a insertar o quitar slides
  const slideKeys = slides.map((s, i) => {
    const h = s.querySelector("h1, h2");
    return h ? h.textContent.replace(/\s+/g, " ").trim() : "#" + (i + 1);
  });
  let localHidden = new Set();
  let localShown = new Set();
  try {
    const stored = JSON.parse(localStorage.getItem(hiddenStoreKey) || "null");
    if (Array.isArray(stored)) localHidden = new Set(stored); // formato anterior
    else if (stored) {
      localHidden = new Set(stored.hidden || []);
      localShown = new Set(stored.shown || []);
    }
  } catch (_) {}

  function isHidden(i) {
    const key = slideKeys[i];
    const sharedHidden = slides[i].classList.contains("slide--hidden");
    return localHidden.has(key) || (sharedHidden && !localShown.has(key));
  }

  function saveHiddenOverrides() {
    const stored = { hidden: Array.from(localHidden), shown: Array.from(localShown) };
    try { localStorage.setItem(hiddenStoreKey, JSON.stringify(stored)); } catch (_) {}
  }

  const hideButtons = slides.map((slide, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "slide-hide";
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      const key = slideKeys[i];
      const sharedHidden = slide.classList.contains("slide--hidden");
      if (isHidden(i)) {
        localHidden.delete(key);
        if (sharedHidden) localShown.add(key);
      } else {
        localShown.delete(key);
        if (!sharedHidden) localHidden.add(key);
      }
      saveHiddenOverrides();
      updateHidden();
    });
    slide.appendChild(button);
    return button;
  });

  function updateHidden() {
    slides.forEach((s, i) => {
      const off = isHidden(i);
      s.classList.toggle("is-skipped", off);
      const button = hideButtons[i];
      button.innerHTML = off ? EYE_OFF : EYE_ON;
      button.setAttribute("aria-pressed", String(off));
      const label = off ? "Oculta en pantalla completa: pulsa para mostrarla" : "Ocultar en pantalla completa";
      button.setAttribute("aria-label", label);
      button.title = label;
    });
    render();
  }

  function updateFullscreenButtons() {
    const isFullscreen = Boolean(document.fullscreenElement);
    hideButtons.forEach((button) => { button.hidden = isFullscreen; });
    homeButtons.forEach((link) => { link.hidden = isFullscreen; });
    fullscreenButtons.forEach((button) => {
      button.hidden = isFullscreen;
      button.setAttribute("aria-pressed", String(isFullscreen));
      button.setAttribute("aria-label", isFullscreen ? "Salir de pantalla completa" : "Poner en pantalla completa");
      button.title = isFullscreen ? "Salir de pantalla completa" : "Poner en pantalla completa";
    });
  }

  document.addEventListener("fullscreenchange", () => {
    updateFullscreenButtons();
    render();
  });
  updateFullscreenButtons();

  /* ---------- Teclado ---------- */
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.fullscreenElement) {
      document.exitFullscreen();
      e.preventDefault();
      return;
    }
    if (document.body.classList.contains("overview")) {
      if (e.key === "o" || e.key === "Escape") { toggleOverview(); e.preventDefault(); }
      return;
    }
    switch (e.key) {
      case "ArrowRight":
      case "ArrowDown":
      case " ":
      case "PageDown":
        next(); e.preventDefault(); break;
      case "ArrowLeft":
      case "ArrowUp":
      case "PageUp":
        prev(); e.preventDefault(); break;
      case "Home": goTo(stepFrom(-1, 1)); e.preventDefault(); break;
      case "End": goTo(stepFrom(slides.length, -1), { end: true }); e.preventDefault(); break;
      case "f":
        toggleFullscreen();
        break;
      case "o": toggleOverview(); e.preventDefault(); break;
    }
  });

  /* ---------- Clic para navegar ---------- */
  document.addEventListener("click", (e) => {
    if (document.body.classList.contains("overview")) return;
    if (e.target.closest("a, button, pre, input, textarea, video")) return;
    const edge = window.innerWidth * 0.17;
    if (e.clientX > window.innerWidth - edge) next();
    else if (e.clientX < edge) prev();
  });

  /* ---------- Vista general (overview) ---------- */
  let gridWrap = null;
  function toggleOverview() {
    const on = document.body.classList.toggle("overview");
    if (on) {
      gridWrap = document.createElement("div");
      gridWrap.className = "deck-grid";
      slides.forEach((s) => gridWrap.appendChild(s));
      document.body.appendChild(gridWrap);
      slides.forEach((s, i) => {
        s.classList.add("is-active");
        s.onclick = () => { toggleOverview(); goTo(i); };
      });
    } else if (gridWrap) {
      slides.forEach((s) => { s.onclick = null; document.body.appendChild(s); });
      gridWrap.remove();
      gridWrap = null;
      render();
    }
  }

  /* ---------- Navegación por hash (enlaces directos #5) ---------- */
  window.addEventListener("hashchange", () => {
    const n = parseInt((location.hash || "").replace("#", ""), 10);
    if (Number.isFinite(n) && n - 1 !== current) goTo(n - 1);
  });

  /* ---------- Versión de la deck ----------
     Sale del nombre de la carpeta: .../mi-charla-v2/index.html → "v2".
     Sin sufijo, la deck es la v0. */
  (function pintarVersion() {
    const partes = decodeURIComponent(location.pathname).split("/").filter(Boolean);
    const carpeta = partes[partes.length - 2] || "";
    const m = carpeta.match(/-v(\d+)$/i);
    const badge = document.querySelector(".author-badge");
    if (!badge || badge.dataset.noVersion !== undefined) return;
    const span = document.createElement("span");
    span.className = "deck-version";
    span.textContent = "v" + (m ? m[1] : "0");
    badge.appendChild(span);
  })();

  /* ---------- Arranque: respeta el hash de la URL ---------- */
  const fromHash = parseInt((location.hash || "").replace("#", ""), 10);
  current = Number.isFinite(fromHash) ? Math.min(Math.max(fromHash - 1, 0), slides.length - 1) : 0;
  updateHidden();

  /* ---------- Impresión: logo, badge y contador en cada página ---------- */
  window.addEventListener("beforeprint", () => {
    const badge = document.querySelector(".author-badge");
    slides.forEach((slide, i) => {
      const logo = document.createElement("span");
      logo.className = "print-logo";
      slide.appendChild(logo);
      if (badge) slide.appendChild(badge.cloneNode(true));
      if (counterCurrent) {
        const counter = document.createElement("div");
        counter.className = "slide-counter";
        counter.innerHTML = '<span class="current">' + (i + 1) + "</span> / " + slides.length;
        slide.appendChild(counter);
      }
      slide.querySelectorAll(":scope > .author-badge, :scope > .slide-counter, :scope > .print-logo")
        .forEach((el) => el.setAttribute("data-print-clone", ""));
    });
  });
  window.addEventListener("afterprint", () => {
    document.querySelectorAll("[data-print-clone]").forEach((el) => el.remove());
  });

  if (new URLSearchParams(location.search).get("print") === "1") {
    const lanzar = () => setTimeout(() => window.print(), 120);
    window.addEventListener("load", () => {
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(lanzar);
      else lanzar();
    });
  }
})();
