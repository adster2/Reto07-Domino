import sys,json,tempfile,unittest,random
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
import tkinter as tk
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import domino_app
from domino_app.gui import PhysicalApp,parse_hand
from domino_app.vision_adapter import VisionAdapter
from domino_app.physical_session import PhysicalSession
from domino_engine import Tile,Move,Player,deal
from domino_engine.rules import legal_moves,apply_move
from task08a import analyze
from static_domino import tile_sprite


class GuiTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest('Desktop Tk non disponibile in questa esecuzione: '+str(exc))
        self.app=PhysicalApp(self.root,start_camera=False)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'results/task09')
        self.app.session_folder=Path(self.tmp.name)
        self.root.update()

    def tearDown(self):
        if hasattr(self,'app'):self.app.close();self.tmp.cleanup()

    def test_registration_real_pipeline_on_synthetic_fixture_and_clear_table(self):
        image=np.full((720,1280,3),(47,116,48),np.uint8)
        values=[(0,0),(0,1),(1,1),(1,2),(2,2),(2,3),(3,3)]
        for index,pair in enumerate(values):
            sprite=cv2.resize(tile_sprite(*pair),(180,90));x=100+(index%4)*280;y=140+(index//4)*240
            region=image[y:y+90,x:x+180];alpha=sprite[:,:,3:]/255
            region[:]=np.uint8(region*(1-alpha)+sprite[:,:,:3]*alpha)
        d=json.loads((ROOT/'config/detection_live.json').read_text());r=json.loads((ROOT/'config/recognition_live.json').read_text())
        bundle=analyze(image,d,r);self.assertEqual(bundle['report']['recognized_count'],7)
        self.app.adapter=VisionAdapter(minimum_seconds=0);self.app.scan_hand()
        for _ in range(3):self.app.process_bundle(bundle)
        self.assertEqual(self.app.phase,'registration_review');self.assertIsNone(self.app.session)
        with patch('domino_app.gui.messagebox.askyesno',return_value=True):self.app.confirm_hand()
        self.assertEqual(len(self.app.session.state.hand),7);self.assertEqual(self.app.phase,'clear_table')
        empty=analyze(np.full_like(image,(47,116,48)),d,r)
        for _ in range(3):self.app.process_bundle(empty)
        self.app.align_table();self.assertTrue(self.app.session.aligned);self.assertEqual(self.app.phase,'playing')

    def test_full_match_through_real_confirm_widget_not_physical_camera(self):
        referee=deal(42);self.app.session=PhysicalSession(referee.hand(Player.ASSISTED),referee.turn)
        self.app.session.confirm_alignment(());self.app.phase='playing';rng=random.Random(42);count=0
        while not referee.terminal:
            move=rng.choice(legal_moves(referee));p=self.app.session.propose(move,attested=move.is_pass and referee.turn==Player.OPPONENT,source='GUI_TEST_PUBLIC_EVENT')
            self.assertTrue(p.legal,p.error);self.app.refresh();self.app.confirm_button.invoke()
            referee=apply_move(referee,move);count+=1
            self.assertEqual(self.app.session.state.chain,referee.chain)
            self.assertEqual(self.app.session.state.hand,referee.hand(Player.ASSISTED))
            self.assertLess(count,40)
        if referee.reason=='blocked':
            score=sum(t.points for t in referee.hand(Player.OPPONENT))
            with patch('domino_app.gui.simpledialog.askinteger',return_value=score),patch('domino_app.gui.messagebox.askyesno',return_value=True):self.app.opponent_score()
        self.assertEqual(self.app.session.state.winner,referee.winner)
        self.assertTrue((self.app.session_folder/'physical_game.json').exists())

    def test_layout_and_controls_are_real(self):
        self.assertGreater(self.app.video.winfo_width(),100)
        self.app.notebook.select(1);self.root.update()
        self.assertGreater(self.app.moves.winfo_height(),100)
        self.assertEqual(self.app.next_button['text'],'Scan my 7 tiles')
        self.assertFalse(self.app.play_controls.winfo_ismapped())
        self.assertEqual(str(self.app.confirm_button['state']),'disabled')
        self.assertEqual(self.app.level.get(),3)

    def test_guided_actions_and_keyboard_do_not_interfere_with_text(self):
        self.app.next_button.invoke();self.root.update()
        self.assertEqual(self.app.phase,'registration')
        self.assertEqual(str(self.app.next_button['state']),'disabled')
        self.app.manual_registration();self.root.update()
        self.assertTrue(self.app.hand_controls.winfo_ismapped())
        self.assertEqual(self.app.next_button['text'],'Confirm my hand')
        self.assertFalse(self.root.bind('<Key-s>'))
        self.assertFalse(self.root.bind('<Key-d>'))

    def test_camera_loss_disables_empty_table_confirmation(self):
        self.app.session=PhysicalSession(deal(42).hand(Player.ASSISTED))
        self.app.phase='clear_table';self.app.alignment_ids=[];self.app.refresh()
        self.assertEqual(str(self.app.next_button['state']),'normal')
        self.app.vision.put(('error','camera scollegata'));self.app.poll()
        self.assertIsNone(self.app.alignment_ids)
        self.assertEqual(str(self.app.next_button['state']),'disabled')
        self.assertFalse(self.app.session.aligned)

    def test_old_camera_proposal_cannot_be_confirmed(self):
        self.app.session=PhysicalSession(deal(42).hand(Player.ASSISTED))
        self.app.session.confirm_alignment(());self.app.phase='playing'
        move=self.app.session.state.knowledge().legal_moves()[0]
        self.app.session.propose(move,source='vision_temporal_consistency')
        self.app.last_frame_at=None
        with self.assertRaises(ValueError):self.app.confirm_move()
        self.assertFalse(self.app.session.journal)
        self.assertIsNone(self.app.session.pending)

    def test_single_score_and_explicit_clear_hand_instruction(self):
        self.assertEqual(tuple(self.app.moves['columns']),('move','score'))
        self.app.session=PhysicalSession(deal(42).hand(Player.ASSISTED))
        self.app.phase='clear_table';self.app.refresh()
        self.assertIn('remove the 7 tiles',self.app.step_title.get())
        self.assertIn('out of camera view',self.app.guide.get())

    def test_parse_hand_rejects_invalid_values_duplicates_and_extra_text(self):
        for text in ['0|0 '*7,'7|1 0|0 0|1 0|2 0|3 0|4 0|5','ciao']:
            with self.assertRaises(ValueError):parse_hand(text)


if __name__=='__main__':unittest.main()
