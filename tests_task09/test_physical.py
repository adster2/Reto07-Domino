import sys
from pathlib import Path
import unittest
import json
from concurrent.futures import ThreadPoolExecutor,Future
from dataclasses import fields
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import domino_app
from domino_engine import Tile,Move,Side,OrientedTile,Player
from domino_engine.events import ObservedScene,ObservedTile
from domino_engine.strategy import StrategyEngine,SearchConfig
from domino_app.physical_session import PhysicalSession,PhysicalState
from domino_app.workers import AdviceWorker
from domino_app.stress import run

HAND=tuple(Tile(a,b) for a,b in [(0,0),(0,1),(1,1),(1,2),(2,2),(2,3),(3,3)])
def started(hand=HAND,first=Player.ASSISTED):
    session=PhysicalSession(hand,first);session.confirm_alignment(());return session
def play(session,a,b,side=Side.RIGHT):
    p=session.propose(Move(Tile(a,b),side,OrientedTile(a,b)))
    if not p.legal:raise ValueError(p.error)
    session.commit(p.id);return p


class PhysicalTests(unittest.TestCase):
    def test_hand_validated_and_alignment_required(self):
        for hand in [HAND[:6],HAND+(Tile(4,4),),HAND[:6]+(HAND[0],)]:
            with self.assertRaises(ValueError):PhysicalSession(hand)
        s=PhysicalSession(HAND)
        with self.assertRaises(ValueError):s.propose(Move(HAND[0],Side.RIGHT,OrientedTile(0,0)))
        self.assertEqual(len(s.state.hand),7)

    def test_only_commit_changes_own_hand_and_duplicate_click_is_safe(self):
        s=started();before=s.state;p=s.propose(Move(Tile(0,1),Side.RIGHT,OrientedTile(0,1)))
        self.assertEqual(s.state,before);s.commit(p.id);s.commit(p.id)
        self.assertEqual(len(s.state.hand),6);self.assertEqual(len(s.state.history),1)

    def test_concurrent_commit_once(self):
        s=started();p=s.propose(Move(HAND[0],Side.RIGHT,OrientedTile(0,0)))
        with ThreadPoolExecutor(4) as pool:list(pool.map(s.commit,[p.id]*8))
        self.assertEqual(len(s.journal),1)

    def test_opponent_count_and_no_private_hand(self):
        s=started(first=Player.OPPONENT);play(s,6,5)
        self.assertEqual(s.state.opponent_count,6);self.assertEqual(s.state.hand,tuple(sorted(HAND)))
        names={f.name for f in fields(PhysicalState)}
        self.assertFalse(names&{'hands','excluded','opponent_hand','seed'})
        self.assertEqual(s.state.knowledge().opponent_count,6)

    def test_opponent_cannot_play_our_tile_or_duplicate(self):
        s=started(first=Player.OPPONENT)
        p=s.propose(Move(HAND[0],Side.RIGHT,OrientedTile(0,0)));self.assertFalse(p.legal)
        with self.assertRaises(ValueError):s.commit(p.id)

    def test_wrong_side_and_correction(self):
        s=started();play(s,0,1)
        wrong=s.propose(Move(Tile(1,6),Side.LEFT,OrientedTile(1,6)));self.assertFalse(wrong.legal)
        fixed=s.correct(wrong.id,Move(Tile(1,6),Side.RIGHT,OrientedTile(1,6)));self.assertTrue(fixed.legal)
        with self.assertRaises(ValueError):s.commit(wrong.id)
        s.commit(fixed.id);self.assertEqual(s.state.ends,(0,6))

    def test_own_pass_illegal_and_opponent_attestation(self):
        s=started();self.assertFalse(s.propose(Move()).legal)
        s=started(first=Player.OPPONENT);self.assertFalse(s.propose(Move()).legal)
        s.discard();self.assertTrue(s.propose(Move(),attested=True).legal)

    def test_pass_constraints_and_contradiction(self):
        s=started();play(s,0,1);p=s.propose(Move(),attested=True);self.assertTrue(p.legal);s.commit(p.id)
        play(s,1,2);p=s.propose(Move(Tile(2,0),Side.RIGHT,OrientedTile(2,0)))
        self.assertFalse(p.legal);self.assertIn('contradicts',p.error)

    def test_unknown_block_score_not_invented(self):
        hand=tuple(Tile(a,b) for a,b in [(0,0),(0,1),(1,1),(1,2),(2,2),(2,3),(3,3)])
        s=started(hand,Player.OPPONENT);play(s,6,6)
        p=s.propose(Move());self.assertTrue(p.legal);s.commit(p.id)
        p=s.propose(Move(),attested=True);self.assertTrue(p.legal);s.commit(p.id)
        self.assertEqual(s.state.phase,'awaiting_opponent_score');self.assertIsNone(s.state.winner)
        with self.assertRaises(ValueError):s.state.knowledge()
        with self.assertRaises(ValueError):s.confirm_opponent_score(999,attested=True)
        # Sei tiles restanti, nessun 6: somma plausibile attestata.
        from dataclasses import replace
        view=replace(s.state,phase='active').knowledge();score=sum(t.points for t in view.opponent_candidates[:6])
        s.confirm_opponent_score(score,attested=True);self.assertEqual(s.state.phase,'finished')
        s.undo();self.assertEqual(s.state.phase,'awaiting_opponent_score')

    def test_undo_replay_and_corruption(self):
        s=started();p=play(s,0,1);after=s.state
        loaded=PhysicalSession.from_json(s.to_json());self.assertEqual(loaded.state,after);self.assertFalse(loaded.aligned)
        with self.assertRaises(ValueError):loaded.commit(p.id)
        d=json.loads(s.to_json());d['state']['opponent_count']=3
        with self.assertRaises(ValueError):PhysicalSession.from_json(json.dumps(d))
        s.undo();self.assertEqual(len(s.state.hand),7);self.assertFalse(s.aligned)
        with self.assertRaises(ValueError):s.commit(p.id)

    def test_pending_blocks_other_proposals(self):
        s=started();s.propose(Move())
        with self.assertRaises(ValueError):s.propose(Move())

    def test_failed_reread_invalidates_previous_proposal(self):
        s=started();old=s.propose(Move(HAND[0],Side.RIGHT,OrientedTile(0,0)))
        with self.assertRaises(ValueError):s.observe(ObservedScene((),True),reread=True)
        self.assertIsNone(s.pending)
        with self.assertRaises(ValueError):s.commit(old.id)

    def test_observe_zero_multiple_duplicate_and_low_quality(self):
        for scene in [ObservedScene(()),ObservedScene((ObservedTile(0,0),ObservedTile(0,1))),
                      ObservedScene((ObservedTile(0,0),ObservedTile(0,0))),ObservedScene((ObservedTile(0,0,confidence=.79),))]:
            with self.assertRaises(ValueError):started().observe(scene)
        s=started();p=s.observe(ObservedScene((ObservedTile(0,0,confidence=.8),)))
        self.assertTrue(p.legal);self.assertEqual(len(s.state.hand),7)

    def test_rankings_real_core_all_levels(self):
        s=started()
        for level in range(1,6):
            rank=StrategyEngine(SearchConfig(level=level,time_limit_ms=100000)).rank(s.state.knowledge())
            self.assertEqual(set(m.move for m in rank.moves),set(s.state.knowledge().legal_moves()))
            self.assertEqual(rank.diagnostics.requested_depth,level)

    def test_same_public_facts_no_hidden_input(self):
        from domino_engine.tiles import ALL_TILES
        from domino_engine.state import from_hands
        hidden=[t for t in ALL_TILES if t not in HAND]
        ref1=from_hands(HAND,tuple(hidden[:7]));ref2=from_hands(HAND,tuple(hidden[-7:]))
        self.assertNotEqual(ref1.hand(Player.OPPONENT),ref2.hand(Player.OPPONENT))
        s1=started(ref1.hand(Player.ASSISTED));s2=started(ref2.hand(Player.ASSISTED))
        self.assertEqual(s1.state.knowledge(),s2.state.knowledge())
        config=SearchConfig(level=2,time_limit_ms=100000)
        a=StrategyEngine(config).rank(s1.state.knowledge());b=StrategyEngine(config).rank(s2.state.knowledge())
        self.assertEqual(a.moves,b.moves)

    def test_stale_async_result_is_not_accepted(self):
        s=started();worker=AdviceWorker()
        try:
            future=Future();future.set_result('OLD');worker.future=future
            worker.token=(s.session_id,s.revision,3,worker.generation)
            play(s,0,1);self.assertIsNone(worker.poll(s,3))
        finally:worker.close()

    def test_public_projection_sample(self):
        result=run(20,93000);self.assertEqual(result['violations'],0)
