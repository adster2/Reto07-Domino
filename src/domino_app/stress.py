"""Harness di test: l'arbitro segreto esiste SOLO qui, mai nel tracker fisico."""
import argparse
import csv
import json
from pathlib import Path
import random
import time
from domino_engine import deal,Player
from domino_engine.rules import legal_moves,apply_move
from .physical_session import PhysicalSession
from . import ROOT


def run(games=1000,seed_start=91000,output=None):
    started=time.perf_counter();rows=[];half_moves=0;blocks=0
    for seed in range(seed_start,seed_start+games):
        referee=deal(seed);session=PhysicalSession(referee.hand(Player.ASSISTED),referee.turn)
        session.confirm_alignment(());rng=random.Random(seed);events=0
        while not referee.terminal:
            move=rng.choice(legal_moves(referee));actor=referee.turn
            proposal=session.propose(move,source='public_test_event',attested=move.is_pass and actor==Player.OPPONENT)
            assert proposal.legal,proposal.error
            before=session.state;assert before.hand==referee.hand(Player.ASSISTED)
            session.commit(proposal.id);referee=apply_move(referee,move);state=session.state;events+=1
            assert state.hand==referee.hand(Player.ASSISTED)
            assert state.chain==referee.chain and state.ends==referee.ends
            assert state.turn==referee.turn and state.opponent_count==len(referee.hand(Player.OPPONENT))
            assert state.passes==referee.passes and state.history==referee.history
            assert events<=40,'Possibile deadlock'
        if referee.reason=='blocked':
            assert session.state.phase=='awaiting_opponent_score';blocks+=1
            session.confirm_opponent_score(sum(t.points for t in referee.hand(Player.OPPONENT)),attested=True)
        assert session.state.phase=='finished' and session.state.winner==referee.winner
        replay=PhysicalSession.from_json(session.to_json());assert replay.state==session.state
        assert not replay.aligned
        half_moves+=events;rows.append({'seed':seed,'events':events,'reason':referee.reason,'status':'PASS'})
    summary={'status':'PASS','games':games,'seed_start':seed_start,'seed_end':seed_start+games-1,
             'public_events_compared':half_moves,'blocked_games':blocks,'replays':games,
             'violations':0,'seconds':time.perf_counter()-started,'secret_hand_supplied_to_tracker':False}
    if output:
        output=Path(output);output.mkdir(parents=True,exist_ok=True)
        (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        with (output/'games.csv').open('w',newline='',encoding='utf-8') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--games',type=int,default=1000)
    parser.add_argument('--seed-start',type=int,default=91000);parser.add_argument('--output',type=Path,default=ROOT/'results/task09/public_projection_stress')
    args=parser.parse_args();print(json.dumps(run(args.games,args.seed_start,args.output),indent=2))
