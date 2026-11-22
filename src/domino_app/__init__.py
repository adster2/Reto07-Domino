"""Integrazione locale: una sola sorgente del motore accettato, nessuna installazione."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
ENGINE_ROOT=ROOT/'vendor/Reto07-GameEngine'
sys.path.insert(0,str(ENGINE_ROOT))
import domino_engine
if Path(domino_engine.__file__).resolve().parent!=ENGINE_ROOT/'domino_engine':
    raise RuntimeError('Il Game Engine importato non corrisponde alla consegna locale.')
