# Querra Fence · Gardian X500

{{LANGBAR}}

<img src="docs/assets/icon.svg" width="72" align="right" alt="Icono de Querra Fence">

**Cerca segura: protege a tus animales de los depredadores.** Página del proyecto, con los sensores y la hoja de ruta:
**[cosminbmemetea.github.io/querra-fence](https://cosminbmemetea.github.io/querra-fence/?lang=es)**

Inspección autónoma de cercas eléctricas con un PX4 **Holybro X500**, simulada de punta a punta en **Gazebo Harmonic**.
El dron recorre solo la línea de la cerca, encuentra averías (hilo cortado, poste caído, una rama que pone en
cortocircuito los hilos), mide dónde pierde tensión la cerca, detecta los animales que salieron del potrero, aterriza
y escribe un informe con las coordenadas GPS de cada hallazgo.

La documentación detallada de `docs/` está en inglés.

![El campo tras un vuelo de inspección: ruta amarilla, haces naranjas en las averías, rojos en los animales escapados](docs/media/result-overview.jpg)

<p>
  <img src="docs/media/dronecam.gif" width="49%" alt="La cámara de inspección pasa junto al hilo cortado, con las vacas escapadas marcadas">
  <img src="docs/media/takeoff.gif" width="49%" alt="El X500 despega de su plataforma junto a la cerca">
</p>

## Panel de control de campo

El Jetson ejecuta un panel web en el puerto 8080 (`http://mmx-desktop.local:8080`) para un teléfono en el hotspot o un
portátil. Muestra las dos cámaras en vivo, los objetivos del radar LD2450 y el fix GPS, e inicia y detiene la recogida
de datos con el detector de cerca v0.3. Funciona sin conexión, en inglés o polaco. El código y la arquitectura están en
[`jetson/panel/`](jetson/panel/). La tarjeta del radar tiene un mapa de calor de ocupación que se desvanece
(activar/desactivar y Borrar), y la tarjeta de ROS 2 inicia y detiene ROS 2, muestra la frecuencia de los topics y
graba bags.

<img src="docs/img/panel-demo.gif" width="960" alt="Panel QUERRA: cámaras en vivo, mapa de calor del radar, GPS (posición difuminada), inicio y fin de la recogida, tarjeta de ROS 2, de inglés a polaco">

<img src="docs/img/panel-demo-phone.gif" width="300" alt="Panel QUERRA en un teléfono"> <img src="docs/img/panel-desktop.png" width="560" alt="Panel QUERRA en el escritorio">

Las coordenadas GPS están difuminadas en estas capturas.

Lanzador de escritorio: `sudo apt install ./querra-fence-panel_0.6.0_arm64.deb` añade al dock del Jetson un icono
**Querra Fence** que vuelve a abrir el panel (y lo inicia si hace falta). Ver [packaging/deb/](packaging/deb/).

## ROS 2 (fases 1–3)

Los sensores del Jetson también son topics de ROS 2 Humble. Los nodos corren en Docker en el SSD y son clientes de los
servicios dueños del hardware: cámaras desde el hub del panel, GPS desde gpsd, radar desde el servicio ld2450-radar.
Publican imágenes `sensor_msgs`, `NavSatFix`, objetivos del radar, `PointCloud2` y marcadores. Las grabaciones son
archivos rosbag2 MCAP, y Foxglove se conecta a `ws://<jetson>:8765`. Usa la tarjeta de ROS 2 del panel o `ros2/ros.sh`.
Los detalles están en [docs/ros2.md](docs/ros2.md).

La fase 2 ejecuta el detector de cerca en ROS 2: `fence_detector` corre el motor TensorRT FP16 del modelo YOLO11n v0.3
en la GPU del Jetson (unos 15 Hz, 20–30 ms por imagen, del JPEG a las cajas) y publica `vision_msgs/Detection2DArray`
y una imagen anotada. `alert_confirm` convierte las detecciones en `/fence/alerts` solo cuando 5 de las últimas 8
imágenes coinciden a menos de 5 m en el suelo. `./ros.sh demo` (o **Demo** en el panel) reproduce una misión grabada de
Gazebo por toda la cadena; `./ros.sh demo tcp://<mac>:5601` usa la simulación en vivo. Layout de Foxglove:
[`ros2/foxglove/querra-layout.json`](ros2/foxglove/querra-layout.json).

La fase 3 conecta el propio PX4: `./ros.sh demo tcp://<mac>:5601 px4:=true` inicia un agente micro-ROS en UDP 8888. El
cliente uXRCE-DDS de PX4 le publica `/fmu/out/*`, y `px4_pose` convierte la posición y el rumbo del propio dron en
`/px4/telemetry`, que luego ubica las alertas. En el Mac, `tools/uxrce_relay.py <jetson>` reenvía el cliente de PX4
SITL al Jetson, así que nada cambia en PX4. En un vuelo simulado, la posición de PX4 coincidió con la telemetría del
simulador a 0,6 m (mediana), y las tres averías reales se alertaron a 2,4 m, 3,0 m y 4,2 m de su posición real.
Con `refly:=true`, el Jetson toma el control después de la vuelta de inspección: pasa PX4 a OFFBOARD, vuela bajo sobre
cada avería confirmada para verla de cerca y devuelve el control con Return. En SITL todo el vuelo funcionó: 8 pasadas,
luego regreso y aterrizaje. La verificación de cerca aún no es fiable, porque el detector se entrenó a 12 m y no a 6 m.
Detalles y los números honestos: [docs/ros2.md](docs/ros2.md#phase-3-px4-over-uxrce-dds).

{{MERMAID_ROS}}

## Qué hace un vuelo

| Paso | Qué pasa |
|---|---|
| Planificar | El polígono de la cerca de `fence.json` se convierte en una ruta suavizada a 2,5 m por fuera del hilo, con 56 puntos |
| Volar | PX4 despega a 12 m, recorre los 414 m de cerca a 5 m/s, regresa y aterriza (unos 2,5 min) |
| Detectar | Una cámara de inspección inclinada y un sensor EM simulado informan averías, pérdidas de tensión y animales fuera del polígono |
| Informe | `reports/raport_*.json` para software, `raport_*.html` con mapa, tablas y el perfil de tensión |

Resultado del vuelo de ejemplo en [`docs/sample-report`](docs/sample-report/sample-report.html):
**3 de 3 averías** encontradas, **3 de 3 animales escapados** encontrados, tensión perdida en el hilo superior justo
después del corte, **9 de 24 animales** contados (una pasada por el perímetro solo ve 10 a 15 m hacia dentro del potrero).

## Demo

**Cámara de inspección.** Lo que ve el dron a 12 m, con las detecciones dibujadas en la imagen.

<p>
  <img src="docs/media/dronecam-F1.jpg" width="49%" alt="Hilo superior cortado visto desde el dron">
  <img src="docs/media/dronecam-V13.jpg" width="49%" alt="Vaca escapada junto al hilo cortado">
</p>

**Las tres averías en el suelo.**

![Hilo superior cortado, poste caído, rama sobre los hilos](docs/media/faults.jpg)

**Antes del despegue.** El X500 en su plataforma y el electrificador al comienzo de la cerca.

<p>
  <img src="docs/media/x500-on-pad.jpg" width="49%" alt="X500 en la plataforma de aterrizaje">
  <img src="docs/media/fence-energizer.jpg" width="49%" alt="Electrificador de la cerca y los primeros postes">
</p>

**El informe.** Se abre en el idioma en que corrió el vuelo y tiene un menú con nueve idiomas: EN, RO, PL, PT, DE, ES,
HR, BG, DA.

<img src="docs/media/report.png" width="640" alt="Informe de inspección con mapa, tabla de averías, animales escapados y gráfico de tensión">

## Inicio rápido

Probado en un Mac con Apple Silicon (M2, 8 GB) con PX4 `main` (v1.18 beta) y Gazebo Harmonic 8.10.

1. Compila PX4 para simulación una vez, con la configuración de Gazebo del propio PX4:

   {{BASH_PX4}}

2. Ejecuta la inspección:

   {{BASH_RUN}}

   Se abre Gazebo, el dron vuela, las detecciones aparecen en la terminal y el informe se abre en el navegador.
   **Enter** para otro vuelo, **Ctrl+C** para cerrar todo.

| Comando | Qué hace |
|---|---|
| `./start.sh` | Vuelo de inspección totalmente automático e informe (por defecto) |
| `./start.sh manual` | Solo la simulación; la consola de PX4 (`pxh>`) queda en la terminal para tus comandos |
| `./start.sh headless` | Igual que por defecto, sin la ventana de Gazebo; lo más liviano en un portátil |
| `./start.sh mission` | Solo el vuelo de inspección, sobre una simulación que ya está corriendo |
| `./start.sh demo` | Un vuelo filmado que vuelve a generar todo en `docs/media` |
| `./start.sh guard` | Tierra + aire: una estación terrestre en el portón (RGB, térmica, iToF, monitor de la cerca) envía el dron cuando ve un problema; sus cámaras son flujos RTSP ([detalles](docs/ground-station.md)) |
| `./stop.sh` | Detiene todos los procesos, incluidos los restos de una ejecución caída |
| `tools/install_launcher.sh` | Añade al escritorio un `Gardian Sim.command` que arranca con doble clic |

Añade `--lang <código>` a cualquier modo (o define `GARDIAN_LANG`) para tener la terminal y el informe en otro idioma:
`en` (por defecto), `ro`, `pl`, `pt`, `de`, `es`, `hr`, `bg` o `da`. El idioma del informe también se puede cambiar
después. PX4 en otro lugar: `PX4_DIR=/ruta/a/PX4-Autopilot ./start.sh`. No se modifica nada dentro del árbol de PX4.

## Estación terrestre + dron

`./start.sh guard` añade una estación terrestre al estilo Jetson en un poste junto al portón: cámaras RGB y térmica en
el mástil, un sensor de profundidad iToF en el poste del portón y un monitor de la cerca en el extremo del hilo. Vigila
todo el tiempo y envía el dron cuando un animal sale por el portón o cae la tensión de la cerca. Sus cámaras se publican
como flujos RTSP, así que un Jetson real puede correr sus modelos sobre la simulación antes de ir al campo.
Ver [docs/ground-station.md](docs/ground-station.md).

**Pregúntale al Jetson qué ve.** `brain/server.py` corre en el Jetson: toma las imágenes RTSP y el estado en vivo
(`sim/state_server.py`), responde preguntas escritas con un modelo local de visión y lenguaje (Ollama) apoyado en los
datos de los sensores, y dice la respuesta en voz alta (Piper). Instalación y guion: [docs/jetson-brain.md](docs/jetson-brain.md).

![Flujos simulados de la estación terrestre](docs/media/ground-cameras.png)

## Sensor real: el radar LD2450 en el Jetson

El primer hardware real de la estación terrestre es un HiLink LD2450, un radar mmWave de 24 GHz que sigue hasta 3
objetivos. Se conecta al Jetson mediante un adaptador USB-serie CH340.
`radar/` lo lee y sirve una página de radar en vivo:
- objetivos en un abanico de ±60°, con movimiento suave, estelas y un mapa de calor;
- distancia, ángulo, velocidad y tipo de movimiento de cada objetivo;
- un gráfico de distancia de 60 segundos y un registro de actividad.

Está empaquetado como paquete Debian que corre como servicio del sistema y añade un icono de aplicación al escritorio:

```bash
sudo apt install ./ld2450-radar_1.0.1_all.deb     # desde la página de versiones (releases)
# luego abre "LD2450 Radar", o http://<jetson>:8077 desde cualquier dispositivo de la red
```

Los detalles, el cableado y la API JSON/SSE están en [radar/README.md](radar/README.md).

![Radar LD2450 funcionando en el Jetson](docs/media/ld2450-radar.png)

## Cómo funciona

{{MERMAID_HOW}}

| Ruta | Función |
|---|---|
| `fence.json` | Única fuente de verdad: polígono de la cerca, postes, averías, rebaño, animales escapados, ajustes de vuelo y de cámara |
| `sim/gen_world.py` | Genera el mundo de Gazebo: cerca de dos hilos con portón aislado y electrificador, averías, árboles, galpón, rebaño |
| `models/x500_fence` | El X500 de PX4 más una cámara de inspección de 640×400 a 15 fps, inclinada 55° hacia abajo, más liviana que la de serie de 1280×960 |
| `sim/mission.py` | pymavlink: parámetros de PX4 para vuelo suave, carga de la misión, armado como GCS, detector, informe |
| `sim/director.py` | Python de Gazebo: animales que pastan y caminan, cámara de seguimiento, ruta planificada y marcadores de detección |
| `sim/geo.py` | Geometría compartida: postes, ubicación de averías, ruta exterior, punto en polígono, local ⇄ GPS, modelo de tensión |
| `sim/report.py` | Informe HTML con mapa SVG, perfil de tensión y un menú de idiomas (nueve idiomas) |
| `sim/i18n.py` | Cada mensaje que lee una persona, en nueve idiomas (EN, RO, PL, PT, DE, ES, HR, BG, DA) |
| `tools/` | Captura de la demo, generador de medios, grabador de escenarios, lanzador de escritorio |
| `ground/`, `brain/` | Nodo simulado de la estación terrestre; el cerebro del Jetson que responde preguntas sobre lo que ve |
| `radar/` | Radar mmWave LD2450 en el Jetson: vista web en vivo y su paquete Debian |

## Configuración

Todo el escenario está en `fence.json`. Cámbialo y vuelve a arrancar; el mundo se regenera.

{{JSON}}

Las coordenadas son metros locales (x hacia el este, y hacia el norte) alrededor de `origin`, que fija la posición GPS
del campo.

## Detector de cerca en el Jetson (YOLO11n)

La simulación entrena ahora la percepción real del dron. `tools/make_dataset.py` genera granjas aleatorias en Gazebo y
etiqueta cada imagen a partir de la geometría 3D conocida: 7 clases, sin etiquetado manual. Un YOLO11n entrenado con
esas imágenes corre como motor TensorRT FP16 en un Jetson Orin Nano. El Jetson lee la cámara simulada del dron por la
red local (`tools/cam_stream.py`) mientras PX4 vuela la misión, y registra cada detección con GPS.

| Modelo | Val mAP50 | En el Jetson (misión simulada) | Versión |
|---|---|---|---|
| v0.1 · checkpoint de la época 2 | 0.72 | hilo cortado F1 encontrado (0.78); flojo con el poste caído | `model-v0.1` |
| v0.2 · 25 épocas | 0.921 | 13.3 fps; F1, F2, F3 todos encontrados (0.94 / 0.96 / 0.84); 385 imágenes con hilo cortado falso | `model-v0.2` |
| v0.3 · ajustado con datos dirigidos | 0.916 (prueba reservada 0.912) | `wire_break` prueba mAP50 0.58 → 0.68; con confirmación GPS 5 de 8, falsas alertas 33 → 6, todas las averías encontradas | `model-v0.3` |

![v0.2 en el Jetson: hilo cortado, poste caído, rama y el hilo cortado falso que la v0.3 reduce](docs/img/v0.2-jetson-faults.jpg)

- [Registro de reentrenamiento](docs/retraining-log.md): qué se le escapó a cada versión y qué cambió.
- [Ficha del modelo](docs/model-card.md): datos, métricas, límites y cómo reproducirlo.
- [Integración con el Jetson](docs/jetson-integration.md): la fuente de cámara `sim:`, el detector y el modo de campo en querra-scout.

## Simulado frente a real

El vuelo es código PX4 real: la misma misión, los mismos parámetros y los mismos comandos MAVLink manejarían un X500
físico. La percepción aún no es real, y las cajas de las imágenes de la demo lo indican:

- **La detección** en `sim/mission.py` todavía usa las posiciones reales de Gazebo para mostrar lo que informaría la
  cámara. El modelo de visión que la reemplaza ya corre en el Jetson (ver [Detector de cerca](#detector-de-cerca-en-el-jetson-yolo11n)).
- **La tensión de la cerca** sale de un modelo simple de circuito a lo largo de la cerca. Una versión real necesita un
  sensor que capte desde el aire los pulsos del electrificador, o monitores de tensión fijos en la cerca.
- **Cobertura**: a 12 m la cámara ve unos 10 a 15 m a cada lado. Contar todo el rebaño requiere un vuelo extra en cuadrícula.

## Hoja de ruta

1. Entrenar un detector con el flujo de la cámara de Gazebo y luego con fotos reales de cercas (hilo cortado, poste
   inclinado, vegetación, vacunos, ovejas)
2. Importar la cerca desde un recorrido con GPS o un archivo KML/GeoJSON en lugar de metros locales
3. Gimbal y cámara térmica para inspecciones nocturnas
4. Vuelo en cuadrícula para contar todo el rebaño
5. Alertas al teléfono y un mapa de las averías abiertas
6. El radar LD2450 como contador real en el portón en modo guardia, en lugar del sensor iToF simulado
7. Hardware: X500 V2, Pixhawk, Raspberry Pi 5 o Jetson como ordenador de a bordo, con el mismo código de misión MAVLink

La vigilancia nocturna de depredadores (cámara térmica y radar en el portón) está planificada; ver la
[página del proyecto](https://cosminbmemetea.github.io/querra-fence/?lang=es#roadmap).

## Notas

- La simulación habla nueve idiomas (`--lang pl`, `--lang de`, …). Los registros siempre están en inglés. En los datos
  JSON, el texto que lee una persona se guarda en todos los idiomas.
- Las imágenes de la demo en `docs/media` tienen por ahora rótulos en rumano; `./start.sh demo` las vuelve a generar en inglés.
- Linux aún no está probado. Los scripts esperan el entorno Gazebo de PX4 para macOS (`Tools/setup/macos/.pixi`) y usan
  `open` para el informe.
- Los registros de cada ejecución están en `run/`: `mission.log`, `px4.log`, `gz_server.log`, `director.log`.
  Los dos errores "Unable to load Ogre Plugin" de `gz_server.log` son normales en macOS; la cámara renderiza igual.
