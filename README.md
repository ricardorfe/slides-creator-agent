# slides-creator-agent

Agente de Copilot para crear presentaciones HTML tipo PPT, con un sistema de diseño compartido.

- `.github/agents/`: definición del agente.
- `presentaciones/_plantilla/`: deck base con ejemplos de cada visualización.
- `presentaciones/shared/`: CSS, JS y fuentes compartidos.
- `tools/`: utilidades.

Servir en local: `python3 -m http.server 8765 --bind 127.0.0.1` y abrir `/presentaciones/`.
