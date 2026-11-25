# Rutas ciclistas con A* propio sobre OpenStreetMap

Aplicación Python que descarga una red ciclable de OpenStreetMap, permite elegir
origen y destino y calcula la ruta de coste mínimo con un **A\*** implementado
desde cero sobre `heapq`. Incluye dos backends de datos intercambiables, dos
perfiles de coste, dos algoritmos, interfaz Streamlit/Folium y CLI.

## Características

- `OsmnxProvider`: descarga con `osmnx.graph_from_bbox(network_type="bike")`,
  proyecta a UTM y conserva lat/lon para la heurística y el mapa.
- `OverpassProvider`: consulta directa a Overpass API con `requests`, parser
  propio de nodos/ways y `MultiDiGraph` con atributos tipo OSMnx.
- A* propio con cola `heapq`, heurística haversine admisible y perfil de coste
  inyectado. Dijkstra se incluye para validar A*.
- Snap con `osmnx.nearest_nodes` en OSMnx y `scipy.spatial.cKDTree` en Overpass.
- Caché en disco por bbox redondeado + backend + perfil, y respeto de
  `osmnx.settings.use_cache`.
- Reintentos Overpass con backoff exponencial para timeout, 429 y 5xx (máximo 3).
- Visualización Folium con ruta, origen, destino, métricas y atribución
  «© OpenStreetMap contributors».

## Abrir sin terminal

### Para compartir en Windows x64

Entrega solo `RutasCiclistas.exe` de la carpeta de distribución. Si tienes
`dist/actualizado/RutasCiclistas.exe`, comparte esa copia. La persona que lo recibe hace doble clic
y la app se abre en el navegador. Python y las dependencias vienen incluidos.
El mapa base, la búsqueda y la descarga inicial de grafos necesitan Internet.
El primer arranque puede tardar mientras se extraen los archivos del ejecutable.

Para generar el ejecutable desde el código, instala PyInstaller en el entorno
de desarrollo y ejecuta este script desde PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\scripts\compilar_windows.ps1
```

### Desde el código fuente

En Windows, haz doble clic en `lanzar_silencioso.vbs` o en `iniciar_app.bat`.
El lanzador prepara el entorno si hace falta y abre el navegador cuando Streamlit
responde. Usa el puerto 8501 si está libre y elige otro si está ocupado.
La primera instalación necesita Python 3.11 o superior, el lanzador `py` y conexión a Internet.

El mapa recuerda centro y zoom al recargar. Guarda la vista en
`%LOCALAPPDATA%\RutasCiclistas\ui_state.json` o en
`~/.config/rutas-ciclistas/ui_state.json` cuando no hay `LOCALAPPDATA`.
Define `APP_UI_STATE` para indicar otra ubicación.

## Buscar lugares

En la web, escribe un nombre y pulsa **Buscar**. Selecciona un resultado y
pulsa **Usar como origen** o **Usar como destino**. Para introducir coordenadas,
selecciona **Origen** o **Destino**, escribe `LAT,LON` y pulsa **Fijar origen** o
**Fijar destino**. El mapa se centra en el punto que acabas de guardar.

```powershell
python -m app --geocode "Plaza Norte, Lima"
python -m app --origin-place "Plaza Norte, Lima" --dest-place "UNI, Lima" --no-plot
```

La CLI usa el primer resultado para cada punto. Si hay varias coincidencias,
indica cuál eligió. Para seleccionar otra, consulta `--geocode` y copia sus
coordenadas a `--origin` o `--dest`.

La búsqueda usa Nominatim bajo demanda. La CLI y la web comparten una caché
local de siete días y envían como máximo una petición por segundo por instalación.
Configura un `OSM_USER_AGENT` identificable y evita enviar datos personales o
confidenciales. Si cambias de servicio, define `APP_NOMINATIM_URL`.
Consulta la [política de uso de Nominatim](https://operations.osmfoundation.org/policies/nominatim/).

## Si Overpass no responde

Overpass prueba los servidores en orden y comparte entre ellos un presupuesto
de 90 segundos (`APP_OVERPASS_DEADLINE_S`). Usa `APP_OVERPASS_URLS` para pasar
una lista separada por comas. Si solo defines `OVERPASS_URL`, se usa ese servidor.
Puedes reintentar en unos minutos o elegir OSMnx en **Configuración avanzada** o con
`--provider osmnx`. OSMnx también depende de la disponibilidad de su propio endpoint.

## Si no hay ruta

Abre **Diagnóstico** en la web o consulta el bloque del mismo nombre en la CLI.
Si los puntos quedaron en componentes distintas, se indican sus tamaños, la
distancia mínima y las coordenadas de los dos nodos más próximos. Un hueco entre
nodos indica dónde termina la conectividad registrada. La app prueba primero
alternativas de un solo extremo, en orden de menor desplazamiento, y después
prueba pares alternativos conectados. Si logra calcular una ruta, muestra qué
puntos sustituyó y su distancia en línea recta a los puntos solicitados.

## Requisitos

- Python 3.11 o superior.
- Conexión a Internet para descargar datos de OSM.
- Windows, Linux o macOS.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

En Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Configura un User-Agent identificable antes de usar Overpass u OSMnx:

```powershell
$env:OSM_USER_AGENT = "MiProyecto/1.0 (mi-correo@ejemplo.com)"
```

También puede pasarse con `--user-agent` en la CLI.

## Uso: interfaz Streamlit

```powershell
streamlit run src/app/ui/streamlit_app.py
```

1. Elige backend (`osmnx` o `overpass`), perfil (`bike` o `shortest`) y
   algoritmo (`astar` o `dijkstra`) en **Configuración avanzada**.
2. Usa los campos independientes de coordenadas, o selecciona «Origen» o
   «Destino» y haz clic en el mapa.
3. Pulsa «Calcular ruta».
4. La app muestra distancia, tiempo estimado, nodos expandidos, backend,
   distancias de snap, avisos y el mapa con la ruta.

La primera sesión abre en Madrid. Puedes desplazar el mapa y ajustar el zoom.
El área se ajusta automáticamente a los dos puntos y al margen configurado.
La barra indica cuándo se está preparando la red y cuándo se calcula la ruta.

## Uso: CLI

```powershell
python -m app --origin 40.4168,-3.7038 --dest 40.4210,-3.6990
```

Ejemplos:

```powershell
python -m app --origin 40.4168,-3.7038 --dest 40.4210,-3.6990 `
  --provider overpass --profile bike --algorithm astar

python -m app --origin 40.4168,-3.7038 --dest 40.4210,-3.6990 `
  --profile shortest --algorithm dijkstra --speed-kmh 18
```

Opciones principales: `--provider`, `--profile`, `--algorithm`,
`--margin-km`, `--max-area-km2`, `--speed-kmh`, `--cache-dir`, `--no-cache`
y `--user-agent`.

### Mapa PNG

La CLI genera además un mapa `route.png` (o el nombre indicado en
`--plot-out`) con la red vial de fondo, la ruta sobre la geometría real de cada
tramo, nombres de calles, flechas de sentido, escala, norte y origen/destino.

```powershell
python -m app --origin 40.4168,-3.7038 --dest 40.4210,-3.6990 `
  --provider overpass --plot-out ruta.png --no-show
```

| Flag | Efecto |
| --- | --- |
| `--plot` / `--no-plot` | Activa o desactiva el PNG (activado por defecto). |
| `--plot-out RUTA` | Archivo de salida (por defecto `route.png`). |
| `--no-show` | Guarda sin abrir el visor del sistema. |
| `--dpi N` | Resolución (200 por defecto; el lado mayor nunca baja de 2000 px). |
| `--margin-m N` | Margen alrededor de la ruta en metros (150 por defecto). |
| `--no-labels` | Oculta los nombres de calles. |
| `--basemap osm` | Usa tiles de OSM como fondo; requiere `pip install -e ".[basemap]"` y degrada a la red dibujada si falta la librería o la red. |

La ejecución imprime, después del resumen, los metros recorridos en cada calle
agrupando tramos consecutivos. Si el PNG falla, el resumen de texto se muestra
igual y solo se añade un aviso del error.

## Pruebas

```powershell
pytest -q
ruff check src tests
ruff format --check src tests
```

La suite usa un grafo sintético y una respuesta Overpass guardada; no necesita
red. La prueba de integración real está marcada y se omite por defecto:

```powershell
pytest -m network -q
```

## Arquitectura (10 líneas)

- `domain/`: `Coordinate`, `BoundingBox` y `RouteResult` inmutables; aquí vive la **encapsulación** de datos.
- `providers/base.py`: `GraphProvider` es la **abstracción** común de descarga y snap.
- `providers/osmnx_provider.py` y `providers/overpass_provider.py`: **herencia** y **polimorfismo** de `GraphProvider`.
- `routing/profile.py`: `CostProfile` abstracta; `ShortestProfile` y `BikeFriendlyProfile` son **polimorfismo** de coste.
- `routing/astar.py`: A* propio con `heapq`; `DijkstraPathFinder` reutiliza el motor con heurística nula.
- `routing/base.py`: `PathFinder` define `find_path(origin, dest)` y `PathSearchResult`.
- `services/planner.py`: `RoutePlanner` usa **composición** e inyección de `GraphProvider`, `CostProfile` y `PathFinder`.
- `services/cache.py` y `app/cache.py`: `GraphCache` independiente, clave bbox/backend/perfil.
- `providers/factory.py` y `routing/factory.py`: fábricas que ocultan las clases concretas a la UI.
- `ui/`: `StreamlitApp`, `CliApp` y `MapRenderer` solo orquestan presentación y llaman a `RoutePlanner`.

## Decisiones tomadas

- **Distancias siempre en metros**: longitudes OSM, haversine y proyección local
  para snap; nunca se comparan grados como si fueran metros.
- **A\* admisible**: la heurística es haversine multiplicada por el mínimo
  multiplicador del perfil. `BikeFriendlyProfile` valida que todo multiplicador
  sea ≥ 1.
- **Oneway**: el parser Overpass crea solo las aristas permitidas y respeta
  `oneway:bicycle=no`; OSMnx ya devuelve la red dirigida.
- **Perfil más corto**: usa longitud como coste, pero sigue excluyendo
  motorway/trunk/steps/`bicycle=no` por seguridad.
- **Caché**: `pickle` atómico con SHA-256 corto; se activa o desactiva con
  `use_cache` y se comparte la decisión con `osmnx.settings.use_cache`.
- **Overpass**: una consulta por grafo, User-Agent configurable y reintentos
  secuenciales con backoff; nunca se lanzan ráfagas.
- **Errores**: se envuelven en `RoutingError` y subclases; la UI y la CLI
  muestran mensajes claros sin trazas.
- **Dijkstra** reutiliza el mismo motor de búsqueda que A* con `h=0`, lo que
  facilita comparar costes en los tests.
- **Dependencias transitivas**: `pyproj` y `shapely` se usan porque ya forman
  parte del stack de OSMnx; no se añaden paquetes ajenos a la lista permitida.

## Limitaciones conocidas

- No hay geocodificación: los puntos se eligen en el mapa o se pasan como
  `LAT,LON`.
- No hay instrucciones giro a giro, elevación, tráfico en vivo ni perfil de
  altimetría.
- Las áreas grandes pueden tardar más o exceder el tiempo de espera del proveedor.
  La CLI muestra el progreso en la salida de errores y admite un límite manual
  con `--max-area-km2` o `APP_MAX_AREA_KM2`.
- La disponibilidad depende de OSMnx, Overpass y de la conexión a Internet.
- Si el snap supera 200 m se avisa; solo se rechaza si se configura
  `APP_MAX_SNAP_M`. El snap ignora los nodos sin ninguna arista transitable por
  el perfil activo (por ejemplo, pasillos `corridor` o escaleras dentro de un
  centro comercial), de modo que un punto en el interior de un recinto se
  ajusta a la calle ciclable más próxima en lugar de quedar aislado.
- La caché de grafos y descargas de OSMnx caduca en 14 días y se limita a 150 MiB.
  Se revisa al usar la web y tras escribir un grafo. **Limpiar caché**, en
  **Configuración avanzada**, borra también las búsquedas guardadas en disco. El ejecutable
  guarda la caché en `%LOCALAPPDATA%\RutasCiclistas\cache`.
- No hay fallback automático entre backends: si uno falla, el usuario debe
  cambiar de backend.

## Atribución

Datos de mapa y red: **© OpenStreetMap contributors**, disponibles bajo la
Open Database License (ODbL). La atribución se muestra en los mapas Folium y
en la salida de la CLI.

## Estructura

```text
src/app/
├─ config.py
├─ cache.py                 # re-export de GraphCache
├─ domain/                  # modelos inmutables y excepciones
├─ providers/               # GraphProvider, OSMnx, Overpass, factory
├─ routing/                 # A*, Dijkstra, perfiles, geometría
├─ services/                # RoutePlanner y GraphCache
└─ ui/                      # Streamlit, CLI y Folium
tests/
├─ fixtures/overpass_response.json
├─ test_astar.py
├─ test_profiles.py
├─ test_overpass_provider.py
├─ test_planner.py
├─ test_network.py          # @pytest.mark.network
└─ ...
docs/diagrama_clases.md
```
