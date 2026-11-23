# Reto 07 — Dominó

Proyecto de Inteligencia Artificial de UNEATLANTICO. El sistema detecta y separa fichas de dominó sobre un tapete verde, estima su orientación, localiza la división central y cuenta los puntos de cada mitad. Con esas lecturas reconstruye las fichas `[a|b]`. El asistente calcula los puntos de la mano y propone jugadas compatibles con los extremos de la cadena. La visión utiliza OpenCV, características geométricas y reglas explícitas, sin modelos entrenados. [Enunciado oficial](https://github.com/josebrenosa/-26-27-IYA051---Inteligencia-Artificial/blob/main/Reto%2007/README.md)

| Aplicación | Archivo de inicio | Uso |
| --- | --- | --- |
| Visualizador digital | `AVVIA_VISUALIZZATORE.cmd` | Reconstruye la escena en un tablero digital y señala lecturas dudosas y uniones incompatibles. |
| Asistente de partida | `avvia_domino_ai.cmd` | Abre directamente la partida física, registra la mano y los turnos, y recomienda jugadas con el Game Engine local. |


## Vídeo demostrativo

[Ver la demostración del proyecto Reto 07 — Dominó en YouTube](https://youtu.be/KJUkfJiOsgY).

## Instalación en Windows

Se necesita Windows 10 u 11 de 64 bits, Python 3.12 con pip y Tcl/Tk, un iPhone compatible con Camo, un soporte cenital, un tapete de fieltro verde mate de al menos 50 × 50 cm y fichas claras con puntos oscuros del juego doble seis. La instalación requiere Internet. El procesamiento de vídeo y las recomendaciones se ejecutan en el equipo.

1. En la página del repositorio, pulse **Code → Download ZIP** y extraiga todo a una carpeta con permisos de escritura. Si tiene Git, también puede copiar la URL HTTPS de **Code** y ejecutar `git clone URL`.
2. Instale Python 3.12 de 64 bits desde el sitio oficial. Mantenga habilitados pip y Tcl/Tk y marque **Add python.exe to PATH**. [Descargas de Python para Windows](https://www.python.org/downloads/windows/)
3. Abra PowerShell en la carpeta extraída, donde están los dos archivos CMD, y ejecute:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m pip check
   ```

   Si instaló Python 3.12 sin el lanzador `py`, utilice `python -m venv .venv` tras comprobar la versión con `python --version`. No hace falta activar el entorno. Se instalan OpenCV 4.11.0.86 y NumPy 2.1.3. El motor ya está incluido en `vendor/Reto07-GameEngine/`.

## Camo y montaje

1. Instale **Camo Studio** en Windows y **Camo Camera** en el iPhone desde los enlaces oficiales. [Descargas de Camo](https://camo.com/studio#downloads)
2. Abra ambas aplicaciones. Conecte el iPhone desbloqueado con un cable USB de datos; Camo puede funcionar aunque se descarte la solicitud de confianza. Para Wi‑Fi, conecte ambos equipos a la misma red y seleccione **Device → + Pair Camo Camera** en Camo Studio. Escanee el QR con el botón de conexión inalámbrica de Camo Camera. Seleccione el iPhone y compruebe que aparece vídeo en movimiento. [Ayuda oficial de Camo](https://camo.com/es/support/camo/camo-getting-started)
3. Fije la cámara trasera aproximadamente perpendicular al tapete. Ajuste la altura para que se vea toda la zona útil y se distingan un punto y la línea divisoria incluso en los bordes. Use luz difusa y uniforme y desactive el encuadre automático, los efectos y el reemplazo de fondo.
4. Mantenga Camo Studio abierto y cierre otras aplicaciones que utilicen la cámara virtual. Abra uno de los dos CMD con doble clic y ciérrelo antes de abrir el otro. Para comprobar la enumeración de dispositivos DirectShow, ejecute `.\.venv\Scripts\python.exe src\webcam.py --list`. Si Camo falta o aparece de forma ambigua, el programa muestra un error.

## Visualizador digital

El vídeo aparece a la izquierda y la reconstrucción a la derecha. El estado inferior informa de cuántas fichas se leyeron en el último análisis y cuántas aparecen en la vista estabilizada.

- **Amarillo o `?`** indica incertidumbre en la ficha, una mitad o su geometría. **MEM** indica que se conserva una lectura anterior de esa zona.
- **Rojo** indica una unión detectada entre mitades con valores distintos. **Tappeto poco visibile** indica que menos del 35 % del fotograma se clasificó como verde.
- Retire las manos, corrija reflejos, separe las fichas dudosas y espere una nueva lectura. **Azzera scena** borra la memoria y vuelve a analizar. Para salir, cierre la ventana.

## Asistente de partida

1. Reparta siete fichas a cada jugador. Coloque solo las suyas, separadas y visibles, y pulse **Scan my 7 tiles**. Revise los valores antes de pulsar **Confirm my hand**. Puede usar **Rescan with webcam** o **Enter hand manually**.
2. Retire las fichas de la mano del encuadre. Seleccione quién empieza, **YOU** u **OPPONENT**, y pulse **Start game** cuando se haya comprobado la mesa vacía.
3. Jueguen una ficha por turno y retiren la mano del encuadre. Mantenga la cadena completa a la vista. Revise cada propuesta y pulse **Confirm detected move**. La confirmación actualiza la cadena, la mano y el turno.
4. **Hand & table** muestra la cadena y los extremos lógicos A/B. **All moves & analysis** muestra las jugadas y sus valoraciones. La puntuación indica la preferencia del motor. A/B puede diferir de izquierda/derecha después de un giro.
5. Si procede, use **Correct**, **Rescan**, **Discard**, **Manual move** o **Pass** y confirme la propuesta correspondiente. El oponente debe declarar que pasa. Tras dos pases puede ser necesario introducir los puntos que le quedan al oponente. **Undo last confirmed move** requiere restaurar y realinear la mesa física.

En el vídeo, `[?|?]` indica lectura sin identidad y **confirmed \*** indica una lectura retenida de una ficha ya confirmada, hasta cuatro segundos si la geometría sigue siendo coherente. Un aviso rojo señala una propuesta inválida o un problema que requiere revisión. **Game & tools** permite reconectar Camo, guardar y cargar partidas, y guardar fotos o diagnósticos con **Ctrl+S** y **Ctrl+D**. Los datos generados se guardan bajo `results/`.

## Límites y pruebas

Sombras, reflejos, manos sobre la mesa, recortes y contactos ambiguos pueden provocar rechazos o lecturas incompletas. La segunda jugada tras un doble inicial puede requerir elegir manualmente el extremo. Si Camo entrega vídeo negro o congelado, revise primero la imagen en Camo Studio. La fiabilidad del montaje físico requiere una prueba con el iPhone y las fichas reales.

- [Pipeline, características y árbol de decisión](docs/vision.md)
- [Verificaciones reproducibles y entregables pendientes](docs/verificacion.md)
