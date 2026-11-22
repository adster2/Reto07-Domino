# Reto 07 Dominó · Evidencias y resultados

Matteo Garofoli · Inteligencia Artificial, UNEATLANTICO · 22 de noviembre de 2026

Este anexo acompaña a la memoria técnica. Las rutas de **E** se refieren a la entrega pública. Las rutas de **D** se refieren a la carpeta de desarrollo, que conserva los datos y diagnósticos experimentales.

- **E** · [adster2/Reto07-Domino](https://github.com/adster2/Reto07-Domino), commit [569bc00610974f9156e5be43366aaba7787e4141](https://github.com/adster2/Reto07-Domino/tree/569bc00610974f9156e5be43366aaba7787e4141). El README y el commit principal se recuperaron de GitHub y el SHA coincide con el checkout local.
- **D** · `Reto07_Domino`, carpeta local de desarrollo bajo `ChatGPT/PROJ_AI`. Contiene imágenes, anotaciones históricas, predicciones, configuraciones y pruebas auxiliares.
- **Enunciado** · [Reto 07, examen parcial](https://github.com/josebrenosa/-26-27-IYA051---Inteligencia-Artificial/blob/main/Reto%2007/README.md), blob `8bc524181bc4335efb15ff68dae3fe5c91b3f8d1`. Pide visión clásica, decisión explicable, medidas experimentales, escrito, vídeo de 7 a 10 minutos y prueba en directo.

## Trazabilidad del código de entrega

| Afirmación | Archivo o símbolo comprobado |
| --- | --- |
| Camo por DirectShow, coincidencia única por nombre y lectura asíncrona que guarda el último fotograma | E · `src/webcam.py`, `src/list_cameras.ps1`, `src/live_domino.py`, `LatestCamera`, `select_camera` |
| Máscara HSV, selección de blanco, cierre y relleno, contornos, rectángulo mínimo, área, proporción y rectangularidad | E · `src/real_domino.py`, `detect_white_faces`, `src/static_domino.py`, `detect`, `config/detection_live.json` |
| Hipótesis en contacto mediante tamaños, líneas oscuras, anclas, expansión, filtros y selección | E · `src/domino_chain_vision.py`, `detect_chains`, `rectangle`, `score_candidate`, `config/chain_vision.json` |
| Muestreo en expansión, preservación de la divisoria y reintento de margen | E · `src/task08a.py`, `analyze`, `border_crop_failure`. `src/chain_tile_reader.py` está distribuido. El recorrido descrito se ejecuta directamente en `task08a.analyze`. |
| Homografía y reglas de divisoria, blanco, área, aspecto, circularidad, borde y número de puntos | E · `src/recognize_domino.py`, `normalize`, `recognize`, `recognize_half`, `config/recognition_live.json` |
| Orden por coordenadas de cámara | E · `src/spatial_order.py`, `order_halves`. D · `results/spatial_order/vertical_2_5.json` y `vertical_5_2.json` |
| Reintento fotométrico limitado al visualizador de entrega | E · `src/domino_visualizer.py`, `src/domino_app/workers.py`, `src/live_domino.py`, `src/task08a.py`, `recognize_domino.retry_with_preprocessing` |
| Memoria de pantalla, zonas cambiadas y unión incompatible | E · `src/visualizer_scene.py`, `SceneMemory`, `same_region`, `check_chain` |
| Mano, colocación, estado confirmado, recuperación geométrica y ranking | E · `src/domino_app/vision_adapter.py`, `physical_session.py`, `confirmed_memory.py`, `vendor/Reto07-GameEngine/domino_engine/strategy.py` |
| Cálculo de puntos y jugadas compatibles | E · `src/domino_logic.py`, `analyze_scene`, `chain_moves` |

### Distinción de perfiles

`docs/vision.md` recoge varios valores que coinciden con el perfil histórico `config/recognition.json`. En la entrega las dos aplicaciones cargan `config/recognition_live.json`. La tabla siguiente documenta la diferencia. Los SHA son prefijos SHA-256 de los ficheros locales.

| Medida | Perfil histórico base de entrega | Perfil en vivo de entrega | Instantánea de las 38 escenas reales numeradas |
| --- | ---: | ---: | ---: |
| Factor de oscuridad respecto al P75 | 0,55 | 0,57 | 0,55 |
| Fracción blanca mínima | 0,80 | 0,72 | 0,72 |
| Fracción de área del punto | 0,006–0,028 | 0,015–0,050 | 0,015–0,050 |
| Circularidad mínima | 0,65 | 0,45 | 0,45 |
| Área de ruido | 12 px | 20 px | 20 px |
| Ignorar bandas de borde | No | Sí | Sí |
| Identificación del archivo en vivo | — | `4f5707f92e40` | `1709af0e86d8` en las 38 escenas |

Para S000008 también se compararon `src/recognize_domino.py` (entrega `e1d2e253a161`, instantánea `ec9ae43abea6`) y `src/task08a.py` (entrega `c2f12b9c22e0`, instantánea `b56c80136375`). Coinciden `detection_live.json`, `chain_vision.json` y `domino_chain_vision.py` en esa comparación. Para detectar fichas aisladas, el límite de proporción del JSON en vivo es 1,55, distinto del 1,65 consignado en el cuadro de `docs/vision.md`.

## Cifras, denominadores y límites

| Resultado | Evidencia concreta en D o E | Alcance |
| --- | --- | --- |
| Task 04: 42/42 de desarrollo y 123/126 de verificación | D · `results/task04/split_summary.csv` y tres `validation_4070*/evaluation.json` | 10 escenas de desarrollo y 30 con semillas nuevas. Detector 126 TP, 0 FP, 0 FN en verificación. Reconocedor 123 identidades correctas, 3 desconocidas, 0 erróneas aceptadas. Datos sintéticos con generador compartido. |
| Task 04: mediciones de puntos | D · `results/task04/development/measured_ranges.json`, `component_measurements.csv`, `TASK04_REPORT.md` | Fracción, relación de aspecto, circularidad, blanco y divisoria medidos en desarrollo sintético. Justificación parcial del perfil histórico. |
| Task 05: 804/810 puntos, 84/84 pares, 66/66 y 36/42 opciones | D · `results/task05/summary.json` y `chain_1_1/summary.json` | Sumas y opciones de 30 escenas independientes entre sí como entradas lógicas. Son los mismos fotogramas de verificación de Task 04. Comparador de reglas directo. |
| Task 08A, versión previa: 63 TP y 61 identidades correctas sobre 68 | D · `results/task08a/final_summary.json`, `final_validation_1/metrics.csv`, `final_validation_2/metrics.csv` | Dos semillas congeladas de ocho escenas cada una, 0 FP y 5 FN. Precisión 100 %, exhaustividad 92,65 %, identidad extremo a extremo 89,71 %. |
| Task 08A, revisión: 66 TP e identidades correctas sobre 68 | D · `results/task08a/revision_validation_1/metrics.csv`, `revision_validation_2/metrics.csv` y `frozen_revision_line_components.json` | 34/34 y 32/34, 0 FP y 2 FN. Precisión 100 %, exhaustividad e identidad extremo a extremo 97,06 %. Las familias de disposición se mantienen. |
| Contacto real en disposición repetida: 4/4 | D · `data/ground_truth/task08a_contact_independent.json` y `results/task08a/revision_contact_independent/summary.json` | Una captura nueva de la misma disposición de cuatro fichas. Anotación manual espacial y asociación por centro con corte de 25 px. No se combina con la población de noviembre. |
| Replay de integración: 40/40 y 4/4 identidades, 10/10 y 1/1 propuestas | D · `results/task09/visual_validation/summary.json` y `images.csv` | Once fotos de desarrollo y una captura separada. Tres copias de cada foto con tiempos simulados, sin medición de estabilidad en vídeo. |
| Software distribuido: 25 pruebas del asistente y 40 del motor | E · `docs/verificacion.md` y `tests_task09/`, `vendor/Reto07-GameEngine/tests/` | Resultados de verificación archivados de entrega. Otras suites del historial usan conjuntos de tests distintos. |
| Integración lógica: 1000 partidas, 1000 replays, 12 742 eventos, 0 infracciones | D · `results/task09/public_projection_stress/summary.json` y `games.csv` | Semillas 91000–91999. Compara el seguimiento público y las reglas del motor en escenarios simulados. |
| Captura y procesamiento de octubre: 30,00 FPS y 2,25 FPS | D · `results/task07/session_20261017_184943_750348_0ffcbb5f/session_summary.json` | 57,91 s, 1731 capturados, 130 analizados, media de pipeline 420,50 ms. Sesión histórica con escenas concretas. |
| Noviembre: 38 escenas numeradas, 68 rectángulos, 49 aceptaciones, 19 rechazos | D · `results/final_validation/scenes/S000001…S000038/runs/*/prediction.json` y `diagnostic_audit_20261121/summary.json` | Instantánea archivada. La anotación retrospectiva verifica 49 identidades correctas de 69 fichas físicas. |
| Noviembre: 314,4 ms de media, 312,2 de mediana y 461,2 de p95 | D · `results/final_validation/scenes/S000001…S000038/runs/*/timing.json` | Recalculado sobre `reported_pipeline_ms`, con percentil lineal inclusivo. Se excluyen archivo, lectura PNG, anotación y duración de la interfaz. |
| Estado original del programa de validación | D · `results/final_validation/FINAL_VALIDATION_REPORT.md` | La interfaz archivó 39 escenas pendientes y un piloto negro excluido. La anotación independiente de la interfaz cubre los 38 PNG numerados y se entrega aparte. |

Para detección con referencia: precisión = TP/(TP+FP), exhaustividad = TP/(TP+FN). El denominador de identidad extremo a extremo es el total de fichas anotadas, incluidas las omitidas o rechazadas. La aceptación usa rectángulos emitidos como denominador. Task 08A en sintético compara la pareja sin exigir el sentido espacial de los valores. La prueba real de contacto del cuadro anterior sí compara el orden espacial de las mitades.

## Evaluación retrospectiva de fotografías reales

Se anotaron los centros y pares de valores visibles de 69 fichas en los PNG originales de S000001 a S000038. La comparación usa el par sin orden espacial. Para cada escena, el emparejamiento uno a uno maximiza el número de asociaciones y minimiza la distancia total entre centros con un máximo de 25 px. Los resultados permanecen iguales con límites de 20 y 30 px. Cada referencia, predicción y asociación aparece en `Reto07_Validacion_Real_38_Escenas.csv`. Los pilotos quedan fuera del conjunto.

| Ejecución | TP | FP | FN | Correctas | Rechazadas entre TP | Identidad errónea entre TP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Instantánea archivada | 68 | 0 | 1 | 49/69 (71,01 %) | 19 | 0 |
| Entrega sin reintento | 68 | 0 | 1 | 51/69 (73,91 %) | 17 | 0 |
| Visualizador con reintento | 68 | 0 | 1 | 55/69 (79,71 %) | 13 | 0 |

Las dos ejecuciones nuevas utilizan Python 3.12, OpenCV, los perfiles de detección y reconocimiento del commit 569bc00 y `analyze_frame(..., experimental_chains=True)`. La opción `preprocess` activa el reintento del visualizador. La memoria temporal y la lógica de partida quedan fuera de esta medición por fotograma. La precisión de localización es 68/68 y la exhaustividad 68/69. En el visualizador, las fichas aisladas aportan 25/28 aciertos, los grupos separados 21/22 y los contactos 9/19. Las escenas inclinadas S000037 y S000038 aportan 0/10. Son fotografías archivadas de desarrollo y el corpus reservado de nuevas sesiones queda pendiente.

## Origen de las figuras

| Figura | Origen y tratamiento |
| --- | --- |
| 1 | D · `results/final_validation/scenes/S000036/original.png`. Reducción sin recorte del campo de la cámara. |
| 2 | Diagrama elaborado a partir de E · `src/live_domino.py`, `src/task08a.py`, `src/domino_visualizer.py` y `src/domino_app/workers.py`. |
| 3 | D · S000036, cuatro paneles ampliados de una misma región con el original, las dos máscaras y la salida superpuesta. |
| 4 | D · la misma ejecución, `tiles/T1/divider_check.png`, `regions_0.png`, `regions_1.png`. |
| 5 | Árbol elaborado de E · `src/recognize_domino.py` y `config/recognition_live.json`. El programa conserva los diagnósticos de las mitades incluso cuando la divisoria invalidó la identidad. |
| 6 | D · `results/task08a/revision_validation_1/F_transverse_double/annotated.png` y `results/task09/english_ui_playing.png`. |
| 7 | E · Visualizador del commit de entrega. Captura de la aplicación al reproducir D · S000036/original.png. |
| 8 | D · S000008, diagnóstico de divisoria y mitad rechazada, y S000037, recortes comparables del original y de `detections_overlay.png`. |

## Información pendiente para la entrega

1. **Montaje físico y detalle óptico.** Tapete de 50 × 50 cm y lente a 40 cm del plano, según las medidas facilitadas por el autor. Queda pendiente cuantificar el menor detalle distinguible a 1280 × 720 px en el centro y los bordes.
2. **Verificación independiente con nuevas capturas.** Reservar sesiones con giros y dobles transversales antes del ajuste. Anotar polígonos, valores espaciales y extremos de cadena antes de mostrar las predicciones. El CSV adjunto ya documenta la evaluación retrospectiva por centros de las 38 fotos numeradas.
3. **Serie controlada de iluminación, calibración por nodo y partida física completa.** Variar una condición por vez y guardar datos de error y latencia. El código y el archivo histórico permiten concretar el protocolo, pero la adquisición y su verificación requieren el montaje físico.
4. **Vídeo y examen en directo.** El vídeo de demostración se entrega por separado. La prueba de aula usa las escenas que proponga el profesor.
