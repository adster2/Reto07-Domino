"""Collaudi riproducibili dell'integrazione, senza camera o mani nascoste nel tracker."""
import argparse,json
import domino_app
from domino_app.stress import run
from domino_app import ROOT

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--games',type=int,default=1000);parser.add_argument('--seed-start',type=int,default=91000)
    args=parser.parse_args();print(json.dumps(run(args.games,args.seed_start,ROOT/'results/task09/public_projection_stress'),indent=2))
