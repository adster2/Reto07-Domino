# Verificación y estado de la entrega

## Pruebas de la entrega en Windows

| Prueba | Resultado |
| --- | --- |
| Python 3.12.5 x64, entorno aislado nuevo | Instalación desde PyPI de OpenCV 4.11.0.86 y NumPy 2.1.3. `pip check` correcto. |
| Inicio desde otro directorio | Los dos CMD abrieron sus respectivas ventanas y salieron con código 0 al cerrarlas. El asistente abrió directamente **Physical game**. |
| Asistente, pruebas incluidas | 25 superadas, incluidas pruebas Tk con entradas sintéticas. |
| Game Engine, pruebas de escritorio incluidas | 40 superadas. |
| Simulación de la integración | 1.000 partidas y 1.000 replays, semillas 91000–91999. Se compararon 12.742 eventos públicos y se registraron 0 infracciones. |

Para repetir las pruebas de esta entrega, ejecute desde la raíz después de crear el entorno:

```powershell
New-Item -ItemType Directory -Force results/task09 | Out-Null
.\.venv\Scripts\python.exe -m unittest discover -s tests_task09
.\.venv\Scripts\python.exe src\task09_validate.py --games 1000 --seed-start 91000
$python = (Resolve-Path .\.venv\Scripts\python.exe).Path
Push-Location vendor/Reto07-GameEngine
try { & $python -m unittest discover -s tests } finally { Pop-Location }
```

En una copia temporal de desarrollo con sus fixtures se ejecutaron también las suites originales de visión (68 superadas), integración (48 superadas) herramienta de validación (40 superadas con Pillow instalado en esa copia) y Game Engine completo (48 superadas, incluidas pruebas del bridge y de la construcción web). Tk emitió un aviso de callback `poll` al cerrar una prueba del asistente. Las suites terminaron correctamente. El entorno de la entrega se probó en Windows ya instalado, con Python limpio. La apertura de ventanas, la simulación y los fotogramas archivados no constituyen una nueva prueba física con Camo.

## Evidencia real archivada

El informe de desarrollo registra 0 escenas revisadas, 39 pendientes y 1 excluida por captura negra o ilegible. La auditoría previa registró, para las 38 escenas numeradas, 68 rectángulos emitidos, 49 identidades aceptadas y 19 rechazos. Son salidas del programa. Sin polígonos e identidades confirmados no se pueden calcular precisión, exhaustividad ni exactitud independientes. La auditoría identificó recortes de puntos en cadenas inclinadas y rechazos de componentes por geometría. Las capturas y diagnósticos de desarrollo quedan fuera de la distribución.

## Pendiente para el parcial

- Redactar y revisar el trabajo escrito final. Incorporar el montaje medido, la comprobación de que se distingue el menor detalle en toda la zona útil, la justificación experimental de los umbrales y resultados con aciertos, errores y rechazos.
- Confirmar las anotaciones de las escenas de referencia y evaluar un conjunto independiente con variación de cantidad, posición, orientación, distribución y clases. Incluir fichas separadas, contactos, giros y dobles transversales. Realizar también una partida física completa con Camo.
- Grabar una demo de 7–10 minutos, subirla a YouTube con la cuenta universitaria e incluir el enlace en la portada del trabajo escrito.
- Realizar la prueba en directo con las escenas propuestas por el profesor.
