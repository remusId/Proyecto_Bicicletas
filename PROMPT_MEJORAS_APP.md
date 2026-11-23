## Rol

Eres un ingeniero senior de Python especializado en aplicaciones de escritorio Windows y apps web locales con Streamlit. Priorizas que el usuario final no toque la terminal, mensajes de error accionables y cambios pequeños verificables. No inventas datos ni rutas.

## Contexto del proyecto (arrastrar)

- Repo: `C:\Users\paris\Documents\Proyecto_Final_POO` (Windows, PowerShell, git ya inicializado).
- Python 3.11+, entorno en `.venv`; ejecutar siempre con `.venv\Scripts\python.exe` o con el venv activado. Paquete instalado en modo editable (`pip install -e ".[dev]"`).
- Arquitectura ya existente y **bloqueada**:
  - `src/app/ui/cli.py` (`python -m app`), `src/app/ui/streamlit_app.py`, `src/app/ui/map_renderer.py` (Folium).
  - `src/app/services/planner.py` (`RoutePlanner.plan`), `src/app/services/cache.py`.
  - `src/app/providers/{factory,overpass_provider,osmnx_provider}.py`.
  - `src/app/routing/{astar,dijkstra,profile}.py` (A\* propio; no tocar).
  - `src/app/visualization/plotter.py` (`RouteRenderer`, PNG con geometría real).
- Decisiones previas que siguen vigentes:
  - El snap ya es consciente del perfil: `RoutePlanner._snap` descarta nodos sin aristas transitables.
  - Los perfiles son solo `bike` y `shortest`; ambos excluyen `motorway`, `trunk`, `steps`, `corridor`, `access=private/no` y `bicycle=no`.
  - La salida numérica actual (Madrid, `--origin 40.4168,-3.7038 --dest 40.4210,-3.6990 --provider overpass`) es: 1.14 km, 4.6 min, 2198 nodos expandidos, snaps 6.6 m / 1.2 m. **Debe quedar idéntica.**
- Hechos verificados del caso Lima (no reinterpretar):
  - `-12.019720,-77.048610` (UNI) ↔ `-11.959777,-76.987531` (SJL) falla con “No hay una ruta ciclable”.
  - El grafo descargado tiene **dos componentes ciclables disjuntas**: 41 315 y 18 257 nodos, **0 aristas entre ambas**; el punto más cercano entre ellas está a 9 m (`-12.029824,-77.042777` ↔ `-12.029808,-77.042859`), sin way que las una en OSM.
  - El origen además es un callejón sin salida: su única salida continúa en Av. Fernando Wiesse con `bicycle=no`. No existe ruta real; no se debe fabricar una.
- Estado actual de la UI: Streamlit abre siempre centrada en Madrid (`Settings.default_center`), no recuerda la última vista y no tiene buscador de lugares.
- Estado actual de Overpass: un solo endpoint (`Settings.overpass_url`), 3 reintentos con backoff; cuando falla, el mensaje no ofrece alternativas.

## Objetivo

Convertir la app web en algo que un cliente abra con doble clic (sin terminal ni activar venv), recordando su última ubicación y permitiendo buscar lugares por nombre; además, hacer el acceso a Overpass y los errores de ruteo comprensibles y accionables, sin cambiar el algoritmo ni los resultados numéricos.

## Orden de trabajo obligatorio

### Fase 1 — Lanzador de doble clic (P0)

- Crear `iniciar_app.bat` y `lanzar_silencioso.vbs` en la raíz.
- Requisitos: resolver rutas con `%~dp0` (soportar espacios); si no existe `.venv`, crearlo con `py -3 -m venv .venv`, actualizar pip e instalar `-e ".[dev]"`; si existe, no reinstalar en cada arranque.
- Arrancar `streamlit run src/app/ui/streamlit_app.py --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false` con `pythonw.exe` para no dejar consola; esperar el puerto y abrir el navegador.
- Si el puerto 8501 está ocupado, elegir otro libre o informar en un cuadro de diálogo; nunca fallar en silencio.
- El `.vbs` debe ocultar la ventana negra. No requiere permisos de administrador.
- Criterio: en una máquina con Python y conexión, doble clic abre la app; sin escribir comandos; el segundo arranque es rápido y no reinstala.

### Fase 2 — Memoria de la vista y buscador (P0)

- Persistir centro y zoom del mapa en `%LOCALAPPDATA%\RutasCiclistas\ui_state.json` (fallback `~/.config/rutas-ciclistas/ui_state.json`; override `APP_UI_STATE`). Validar JSON y ante datos corruptos volver a `Settings.default_center` sin romper.
- En Streamlit, leer centro/zoom al iniciar, guardarlos cuando cambien (`st_folium` con `returned_objects=["last_clicked", "center", "zoom"]`), y usarlos en render posteriores. Guardar solo si cambió el valor para no escribir en cada rerun.
- Añadir “Ir a coordenadas” que acepte `LAT,LON` usando `Coordinate.from_string`.
- Criterio: recargar la página mantiene la última zona; la primera ejecución sigue abriendo en Madrid.

### Fase 3 — Geocodificación de nombres (P0)

- Nuevo `src/app/services/geocoder.py` con clase `NominatimGeocoder` usando `requests` (ya es dependencia; **no añadas geopy**).
- Endpoint `https://nominatim.openstreetmap.org/search`, `format=jsonv2`, `limit=5`, `accept-language=es`, User-Agent obligatorio de `Settings.user_agent`, timeout y manejo de 429/5xx.
- Respetar la política de uso: máximo 1 petición por segundo, sin paralelismo, y caché en disco `.cache/geocode.json` con TTL de 7 días.
- CLI: `--geocode "texto"` imprime resultados legibles y, al final, la línea `lat,lon` reutilizable; `--origin-place` y `--dest-place` permiten calcular sin escribir coordenadas. Si se combinan con `--origin`/`--dest`, error claro. Mantener `--origin/--dest` funcionando igual.
- Streamlit: campo de búsqueda + botón, lista de resultados con nombre y coordenadas; al elegir uno, centrar el mapa (zoom 16) y asignarlo a Origen/Destino según el selector existente.
- Criterio: `python -m app --geocode "Plaza Norte, Lima"` devuelve coordenadas a menos de 2 km de `-12.0063,-77.0588`; en la web, buscar “Universidad Nacional de Ingeniería” centra Lima y permite fijar el destino.

### Fase 4 — Overpass tolerante a caídas (P1)

- Soportar varios endpoints en `Settings`: `APP_OVERPASS_URLS` (lista separada por comas) manteniendo `OVERPASS_URL` como caso de un solo servidor. Incluir al menos dos espejos públicos además del principal.
- Failover **secuencial**, no en paralelo (no dupliques carga sobre servidores públicos): por endpoint hasta `overpass_retries` intentos, backoff exponencial con jitter, deadline total configurable (p. ej. 90 s) y paso al siguiente espejo ante 429/5xx/timeout.
- Mensaje final accionable que nombre los servidores probados, el número de intentos y 2–3 salidas: reintentar en unos minutos, `--provider osmnx`, o definir `OVERPASS_URL`.
- No registrar credenciales ni el cuerpo completo de las respuestas.
- Criterio: simulando 502 en el primer endpoint y éxito en el segundo, la ruta se calcula; si fallan todos, la app sigue viva y el mensaje explica qué hacer.

### Fase 5 — Diagnóstico de “no hay ruta” (P1)

- Nuevo servicio de solo lectura (p. ej. `src/app/services/diagnostics.py`) que, al capturar `NoRouteFoundError`, distinga y explique: grafo vacío; snap sin aristas transitables; origen y destino en componentes ciclables distintas; misma componente pero sin camino dirigido.
- Para el caso de componentes distintas, reportar tamaños, distancia mínima entre componentes y **coordenadas de los puntos viables más cercanos** (sin inventar rutas).
- Integrarlo en CLI (bloque “Diagnóstico” tras el error) y en Streamlit (`st.error` + detalles expandibles). El código de salida sigue siendo distinto de cero.
- Criterio: el par UNI↔SJL produce el diagnóstico de dos componentes con el hueco de 9 m y alternativas; ningún caso imprime un traceback.

### Fase 6 — Hilos para percepción de velocidad (P2)

- Prefetch en segundo plano del grafo al fijar origen y destino: un solo hilo (`ThreadPoolExecutor(max_workers=1)`), guardando el `Future` en `st.session_state`; si se pulsa “Calcular” antes de terminar, esperar ese mismo future en vez de lanzar otra descarga.
- Nunca llamar a `st.*` ni a `st.session_state` desde el hilo; solo desde el hilo principal.
- No paralelizar consultas a Overpass/Nominatim (política de uso). El threading es para no bloquear y para reutilizar descargas.
- Criterio: la UI responde mientras descarga y no se descarga dos veces el mismo grafo.

### Fase 7 — Documentación y pruebas (P2)

- README: sección “Abrir sin terminal”, “Buscar lugares”, “Si Overpass no responde”, “Si no hay ruta”.
- Pruebas nuevas, todas sin red (mock de `requests`): geocoder (parseo, caché, 429), failover de endpoints, persistencia de estado, diagnóstico de componentes disjuntas y de isla dirigida.
- Mantener verdes las 50 pruebas actuales.

## Restricciones (MUST / NEVER)

- **NEVER** modificar A\*, Dijkstra, perfiles, costes, heurística ni la semántica del snap ya implementada.
- **NEVER** cambiar los números del resumen para rutas que hoy funcionan; el caso Madrid debe seguir dando 1.14 km / 4.6 min / 2198 / 6.6 m / 1.2 m.
- **NEVER** fabricar una ruta cuando los datos no la tienen; el diagnóstico debe decir la verdad.
- **NEVER** añadir dependencias nuevas sin preguntar antes (usa `requests`, `concurrent.futures`, `json`, `pathlib`).
- **NEVER** borrar archivos, cachés ni datos del usuario sin autorización.
- **MUST** mantener compatibles `--origin`, `--dest`, `--plot`, `--no-plot`, `--plot-out`, `--no-show`, `--provider`, `--profile`, `--algorithm`, `--margin-km`, `--max-area-km2`, `--dpi`, `--margin-m`, `--no-labels`, `--basemap`, `--no-cache`, `--user-agent`.
- **MUST** encapsular la lógica nueva en clases/servicios pequeños y testeables; la UI solo orquesta.
- **MUST** mantener el estilo del repo y pasar `ruff check` y `ruff format --check`.
- **MUST** detenerte y preguntar antes de: renombrar módulos públicos, cambiar firmas usadas por CLI/Streamlit, o modificar el ruteo.

## Verificación obligatoria (con evidencia)

1. `.\.venv\Scripts\python.exe -m pytest -q` → todas verdes (50 actuales + nuevas).
2. `.\.venv\Scripts\python.exe -m ruff check src tests` y `ruff format --check src tests`.
3. Madrid sin cambios:
   `python -m app --origin 40.4168,-3.7038 --dest 40.4210,-3.6990 --provider overpass --no-plot`
4. `python -m app --geocode "Plaza Norte, Lima"` (marcar como `network`, no en CI).
5. Doble clic en `iniciar_app.bat` y en `lanzar_silencioso.vbs`: abren la app sin terminal; recargar conserva el centro.
6. Failover: `APP_OVERPASS_URLS="http://127.0.0.1:9,https://overpass.kumi.systems/api/interpreter"` con una ruta corta; debe saltar el primero y explicar el resultado.
7. Par UNI↔SJL: debe imprimir el diagnóstico de componentes disjuntas, sin traceback y con código de salida ≠ 0.
8. Adjunta `route.png` regenerado para Madrid y confirma que sigue igual.

## Entregable de tu respuesta

- Plan breve por fases antes de editar (máx. 10 líneas).
- Archivos creados/modificados con una línea de propósito cada uno.
- Evidencia de los 8 puntos de verificación (comandos y salida resumida).
- Decisiones tomadas y cualquier limitación (p. ej. Nominatim sin cobertura para una calle, o componentes OSM desconectadas).
- Si algo no se puede cumplir sin cambiar el ruteo, detente y explica en vez de improvisar.
