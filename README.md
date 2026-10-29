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
   algoritmo (`astar` o `dijkstra`) en la barra lateral.
2. Selecciona «Origen» o «Destino» y haz clic en el mapa.
3. Pulsa «Calcular ruta».
4. La app muestra distancia, tiempo estimado, nodos expandidos, backend,
   distancias de snap, avisos y el mapa con la ruta.

El centro inicial es Madrid; puedes desplazar y hacer zoom en el mapa para
trabajar en otra zona. El área se calcula con los dos puntos más el margen
configurado y se rechaza si supera el límite (25 km² por defecto).

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
- El límite de 25 km² es deliberadamente conservador para no castigar la API
  pública de Overpass.
- La disponibilidad depende de OSMnx, Overpass y de la conexión a Internet.
- Si el snap supera 200 m se avisa; solo se rechaza si se configura
  `APP_MAX_SNAP_M`. El snap ignora los nodos sin ninguna arista transitable por
  el perfil activo (por ejemplo, pasillos `corridor` o escaleras dentro de un
  centro comercial), de modo que un punto en el interior de un recinto se
  ajusta a la calle ciclable más próxima en lugar de quedar aislado.
- La caché no caduca automáticamente; borra `.cache/graphs` para refrescarla.
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
#   P r o y e c t o _ B i c i c l e t a s  
 