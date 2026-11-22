"""Avvio unificato locale: nessuna connessione o credenziale API a runtime."""
import argparse
import tkinter as tk
import domino_app
from domino_app.gui import choose_mode,PhysicalApp


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--physical',action='store_true');parser.add_argument('--no-camera',action='store_true')
    args=parser.parse_args()
    # Solo il processo: rende nitida la finestra con il ridimensionamento Windows.
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError,OSError):pass
    root=tk.Tk()
    if args.physical:PhysicalApp(root,start_camera=not args.no_camera)
    else:choose_mode(root)
    root.mainloop()


if __name__=='__main__':main()
