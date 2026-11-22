"""Un solo event loop Tk; la camera e la strategia lavorano in thread separati."""
import base64
from datetime import datetime
import json
from pathlib import Path
import re
import time
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk,messagebox,simpledialog,filedialog
import cv2
import numpy as np
from domino_engine import Tile,Move,Side,OrientedTile,Player
from live_domino import save_bundle,save_original
from . import ROOT
from .ui_text import english_error
from .physical_session import PhysicalSession
from .vision_adapter import VisionAdapter
from .confirmed_memory import ConfirmedMemory
from .workers import VisionWorker,AdviceWorker
from .modern_widgets import ActionButton,HandPanel


def parse_hand(text):
    tokens=text.replace('[','').replace(']','').replace(';',' ').split()
    result=[]
    for token in tokens:
        if not re.fullmatch(r'[0-6][|/\-][0-6]',token):raise ValueError('Enter seven pairs, for example 0|0 1|2 3|6 ...')
        result.append(Tile(int(token[0]),int(token[2])))
    if len(result)!=7 or len(set(result))!=7:raise ValueError('Seven valid, distinct tiles are required.')
    return tuple(result)


class PhysicalApp:
    def __init__(self,root,*,start_camera=True):
        self.root=root;root.title('Reto 07 — Domino AI | Physical game')
        root.geometry('1390x870');root.minsize(1100,730)
        self.session=None;self.phase='setup';self.bundle=None;self.hand_evidence=None;self.alignment_ids=None
        self.adapter=VisionAdapter();self.memory=ConfirmedMemory();self.last_effective_report=None;self.last_auto_debug=0;self.auto_debug_count=0;self.vision=VisionWorker();self.advice=AdviceWorker()
        self.ranking=None;self.ignored=None;self.closed=False;self.manual_hand=False;self.last_frame_at=None;self.restarting=False;self.last_telemetry=0
        self.io=ThreadPoolExecutor(max_workers=1,thread_name_prefix='domino-save');self.saving=[]
        self.level=tk.IntVar(value=3);self.first=tk.StringVar(value='YOU');self.status=tk.StringVar(value='New game: scan your seven tiles.')
        self.camera_status=tk.StringVar(value='Camera not started');self.pending_text=tk.StringVar(value='No proposal')
        self.session_folder=ROOT/'results/task09/physical_sessions'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self._build();root.protocol('WM_DELETE_WINDOW',self.close);self.poll_id=root.after(80,self.poll)
        root.bind('<Control-s>',lambda e:self.save_frame());root.bind('<Control-d>',lambda e:self.save_debug())
        if start_camera:self.vision.start()

    def _build(self):
        for child in self.root.winfo_children():child.destroy()
        style=ttk.Style(self.root);style.theme_use('clam')
        style.configure('.',font=('Segoe UI',10),background='#f5f4ef',foreground='#20352e')
        style.configure('TButton',padding=(12,8))
        style.configure('Primary.TButton',font=('Segoe UI',12,'bold'),background='#184e3b',foreground='white',padding=(18,12))
        style.map('Primary.TButton',background=[('disabled','#cad7d2'),('active','#095b47')],foreground=[('disabled','#53635d')])
        style.configure('Title.TLabel',font=('Georgia',26),foreground='#184e3b')
        style.configure('TNotebook',borderwidth=0,tabmargins=(0,8,0,0))
        style.configure('TNotebook.Tab',padding=(14,8),background='#e7eade',borderwidth=0)
        style.map('TNotebook.Tab',background=[('selected','#fffdf5')])
        style.configure('TFrame',background='#f5f4ef')
        style.configure('TLabelframe',borderwidth=0,background='#f5f4ef')
        style.configure('Treeview',background='#fffdf5',fieldbackground='#fffdf5',borderwidth=0)
        style.configure('Treeview.Heading',background='#e9eee4',relief='flat',padding=8)
        style.map('Treeview',background=[('selected','#dce8d7')],foreground=[('selected','#184e3b')])
        style.configure('Step.TLabel',font=('Segoe UI',12,'bold'),foreground='#184e3b')
        style.configure('Treeview',rowheight=32,font=('Segoe UI',10))
        self.root.configure(background='#f5f4ef');self.root.geometry(f'{min(1380,self.root.winfo_screenwidth()-60)}x{min(900,self.root.winfo_screenheight()-100)}');self.root.minsize(1000,650)
        bar=ttk.Frame(self.root,padding=(24,16));bar.pack(fill='x')
        ttk.Label(bar,text='Dominó  /  Live table',style='Title.TLabel').pack(side='left')
        menu=ttk.Menubutton(bar,text='Game & tools');menu.pack(side='right')
        options=tk.Menu(menu,tearoff=False);menu.configure(menu=options)
        for title,fn in [('New game',self.new_game),('Reconnect Camo',self.restart_camera),('Save game',self.save_game),('Load saved game',self.load_game),('Save photo',self.save_frame),('Save diagnostics',self.save_debug)]:
            options.add_command(label=title,command=lambda f=fn:self.safe(f))
        self.step_title=tk.StringVar();self.guide=tk.StringVar();self.turn_title=tk.StringVar()
        guide=ttk.Frame(self.root,padding=(24,4));guide.pack(fill='x')
        ttk.Label(guide,textvariable=self.step_title,style='Step.TLabel').pack(anchor='w')
        ttk.Label(guide,textvariable=self.guide,wraplength=1200,font=('Segoe UI',11)).pack(anchor='w',pady=(4,10))
        content=ttk.Frame(self.root,padding=(24,0));content.pack(fill='both',expand=True)
        content.columnconfigure(0,weight=3,uniform='columns');content.columnconfigure(1,weight=2,uniform='columns');content.rowconfigure(0,weight=1)
        left=ttk.Frame(content);left.grid_propagate(False);left.columnconfigure(0,weight=1);left.rowconfigure(0,weight=1);left.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        self.video=ttk.Label(left,text='Connecting to Camo…',anchor='center',background='#12221f',foreground='white')
        self.video.grid(row=0,column=0,sticky='nsew')
        ttk.Label(left,textvariable=self.camera_status,wraplength=650).grid(row=1,column=0,sticky='ew',pady=8)
        self.action=ttk.LabelFrame(left,text='Next action',padding=12);self.action.grid(row=2,column=0,sticky='ew',pady=(0,8))
        self.setup_controls=ttk.Frame(self.action)
        self.hand_controls=ttk.Frame(self.setup_controls)
        ttk.Label(self.hand_controls,text='Your 7 tiles (you can correct the values before confirming)').pack(anchor='w')
        self.hand_entry=tk.Text(self.hand_controls,height=2,width=30,font=('Consolas',14),relief='solid',borderwidth=1)
        self.hand_entry.pack(fill='x',pady=6)
        self.first_controls=ttk.Frame(self.setup_controls)
        ttk.Label(self.first_controls,text='Who starts, after the physical draw?').pack(side='left',padx=(0,12))
        ttk.Combobox(self.first_controls,textvariable=self.first,values=('YOU','OPPONENT'),state='readonly',width=13).pack(side='left')
        self.next_button=ActionButton(self.setup_controls,style='Primary.TButton',command=lambda:self.safe(self.advance))
        self.next_button.pack(fill='x',pady=6)
        self.setup_secondary=ttk.Frame(self.setup_controls);self.setup_secondary.pack(fill='x')
        ActionButton(self.setup_secondary,text='Rescan with webcam',command=lambda:self.safe(self.scan_hand)).pack(side='left')
        ActionButton(self.setup_secondary,text='Enter hand manually',command=self.manual_registration).pack(side='left',padx=6)
        self.play_controls=ttk.Frame(self.action)
        self.notice=tk.Label(self.play_controls,textvariable=self.pending_text,wraplength=620,font=('Segoe UI',11),anchor='w',justify='left',bg='#e8efdf',fg='#20352e',padx=14,pady=12)
        self.notice.pack(fill='x',pady=(0,8))
        self.confirm_button=ActionButton(self.play_controls,text='Confirm detected move',style='Primary.TButton',command=lambda:self.safe(self.confirm_move))
        self.confirm_button.pack(fill='x',pady=5)
        row=ttk.Frame(self.play_controls);row.pack(fill='x')
        self.play_buttons={}
        for title,fn in [('Correct',self.correct),('Rescan',self.reread),('Discard',self.discard),('Manual move',self.manual_move),('Pass',self.pass_move)]:
            button=ActionButton(row,text=title,command=lambda f=fn:self.safe(f));button.pack(side='left',padx=2);self.play_buttons[title]=button
        self.undo_button=ActionButton(self.play_controls,text='Undo last confirmed move',command=lambda:self.safe(self.undo));self.undo_button.pack(anchor='w',pady=(7,0))
        self.score_button=ActionButton(self.action,text='Enter opponent points and finish',style='Primary.TButton',command=lambda:self.safe(self.opponent_score))
        right=ttk.Frame(content);right.pack_propagate(False);right.grid(row=0,column=1,sticky='nsew')
        ttk.Label(right,textvariable=self.turn_title,font=('Segoe UI',15,'bold')).pack(anchor='w',pady=(0,8))
        self.best_move=tk.StringVar(value='Your recommendation will appear on your turn.')
        ttk.Label(right,textvariable=self.best_move,wraplength=450,font=('Georgia',17),foreground='#184e3b').pack(fill='x',pady=(0,10))
        notebook=ttk.Notebook(right);self.notebook=notebook;notebook.pack(fill='both',expand=True)
        statepage=ttk.Frame(notebook,padding=8);movepage=ttk.Frame(notebook,padding=8)
        notebook.add(statepage,text='Hand & table');notebook.add(movepage,text='All moves & analysis')
        self.hand_panel=HandPanel(statepage);self.hand_panel.pack(fill='x',pady=(0,12))
        self.state_text=tk.Text(statepage,wrap='word',width=38,height=9,font=('Segoe UI',10),relief='flat',background='#fffdf5',padx=16,pady=12,state='disabled')
        self.state_text.pack(fill='both',expand=True)
        scroll=ttk.Scrollbar(statepage,command=self.state_text.yview);scroll.pack(side='right',fill='y');self.state_text.configure(yscrollcommand=scroll.set)
        levelrow=ttk.Frame(movepage);levelrow.pack(fill='x',pady=5)
        ttk.Label(levelrow,text='Search level').pack(side='left')
        combo=ttk.Combobox(levelrow,textvariable=self.level,values=(1,2,3,4,5),width=3,state='readonly');combo.pack(side='left',padx=8)
        combo.bind('<<ComboboxSelected>>',lambda e:self.level_changed())
        self.moves=ttk.Treeview(movepage,columns=('move','score'),show='headings',height=6)
        for key,label,width in [('move','Available move',300),('score','Rating',100)]:
            self.moves.heading(key,text=label);self.moves.column(key,width=width,minwidth=40)
        ttk.Label(movepage,text='Higher = preferred by the engine. This is not a win probability.',wraplength=420).pack(fill='x',pady=5)
        self.moves.pack(fill='both',expand=True);self.moves.bind('<<TreeviewSelect>>',self.explain)
        self.diagnostics=tk.StringVar(value='Waiting for the game to start.')
        ttk.Label(movepage,textvariable=self.diagnostics,wraplength=440).pack(fill='x',pady=6)
        self.explanation=tk.Text(movepage,height=5,width=35,wrap='word',state='disabled');self.explanation.pack(fill='x')
        ttk.Label(self.root,textvariable=self.status,wraplength=1300,padding=(18,8)).pack(fill='x')
        self.refresh()

    def advance(self):
        if self.phase=='setup':self.scan_hand()
        elif self.phase=='registration_review':self.confirm_hand()
        elif self.phase in ('clear_table','reconcile'):self.align_table()

    @staticmethod
    def move_label(move):
        if move is None:return 'No recommendation available'
        if move.is_pass:return 'Pass: no playable tiles'
        side='end A' if move.side==Side.LEFT else 'end B'
        return f'{move.tile} → {side}'

    def update_workflow(self):
        pending=self.session.pending if self.session else None
        active=self.phase=='playing' and self.session and self.session.state.phase=='active'
        self.setup_controls.pack_forget();self.play_controls.pack_forget();self.score_button.pack_forget()
        self.hand_controls.pack_forget();self.first_controls.pack_forget();self.setup_secondary.pack_forget()
        if self.phase!='playing':
            self.setup_controls.pack(fill='x')
            info={
                'setup':('1 / 3 · Register your hand','Place your 7 tiles separately on the mat, all in view. Then press the green button.','Scan my 7 tiles'),
                'registration':('1 / 3 · Scanning your hand','Keep all 7 tiles still. The reading is checked across multiple frames.','Scanning…'),
                'registration_review':('1 / 3 · Review your seven tiles','Compare the values below with your tiles. Correct any errors, then confirm.','Confirm my hand'),
                'clear_table':('2 / 3 · Now remove the 7 tiles from the mat','Your hand is saved. Keep it out of camera view: only played tiles go on the mat. Then select who starts.','Start game'),
                'reconcile':('Resume · Align the table','Place only the tiles from the saved chain on the mat, then confirm.','Confirm table alignment'),
            }
            title,instruction,button=info[self.phase];self.step_title.set(title);self.guide.set(instruction)
            self.next_button.configure(text=button,state='disabled' if self.phase=='registration' or self.phase in ('clear_table','reconcile') and self.alignment_ids is None else 'normal')
            if self.phase=='registration_review':self.hand_controls.pack(fill='x',before=self.next_button)
            if self.phase=='clear_table':self.first_controls.pack(fill='x',before=self.next_button,pady=8)
            if self.phase in ('setup','registration','registration_review'):self.setup_secondary.pack(fill='x')
            self.turn_title.set('Game setup')
        else:
            state=self.session.state;ours=state.turn==Player.ASSISTED
            self.step_title.set('3 / 3 · Game in progress')
            self.turn_title.set('YOUR TURN' if ours else 'OPPONENT TURN')
            instruction='Place the recommended tile at the indicated end. Wait for recognition, then confirm the move.' if ours else 'Your opponent places a tile. Wait for recognition, then confirm their move.'
            if pending:instruction='Check the highlighted tile and proposed move. Confirm only if they match the actual placement.'
            if state.phase=='awaiting_opponent_score':
                instruction='Both players passed. Count the points remaining in the opponent hand to determine the result.';self.score_button.pack(fill='x');self.turn_title.set('BLOCKED GAME')
            elif state.phase=='finished':
                instruction='Game finished and saved. To play again: Game & tools → New game.';self.turn_title.set('GAME FINISHED')
            else:self.play_controls.pack(fill='x')
            self.guide.set(instruction)
        for name,button in self.play_buttons.items():
            enabled=active and (bool(pending) if name in ('Correct','Discard') else not pending if name in ('Manual move','Pass') else True)
            button.configure(state='normal' if enabled else 'disabled')
        self.undo_button.configure(state='normal' if self.session and self.session.journal else 'disabled')

    def safe(self,function):
        try:return function()
        except Exception as exc:self.status.set(english_error(exc));messagebox.showerror('Reto 07',english_error(exc),parent=self.root)

    @staticmethod
    def set_text(widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')

    def new_game(self):
        if self.session and not messagebox.askyesno('New game','Leave the current game? The automatic save will remain available.',parent=self.root):return
        self.memory.clear();self.session=None;self.phase='setup';self.hand_evidence=None;self.manual_hand=False;self.ignored=None
        self.alignment_ids=None;self.session_folder=ROOT/'results/task09/physical_sessions'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.adapter.reset();self.invalidate_advice();self.hand_entry.delete('1.0','end');self.refresh()
        self.status.set('Select Scan my 7 tiles and show all seven tiles together.')

    def scan_hand(self):
        if self.session and self.session.journal:raise ValueError('Start a new game to change a hand already used in play.')
        self.phase='registration';self.hand_evidence=None;self.manual_hand=False;self.adapter.reset();self.refresh()
        self.status.set('Show all seven tiles. Keep them still, then review and confirm the reading.')

    def manual_registration(self):
        if self.session and self.session.journal:self.status.set('Start a new game to change your hand.');return
        self.manual_hand=True;self.hand_evidence=None;self.phase='registration_review';self.refresh();self.hand_entry.focus_set()
        self.status.set('MANUAL: no camera scan. Enter seven pairs separated by spaces, e.g. 0|0 1|2 ...')

    def confirm_hand(self):
        if self.phase!='registration_review':raise ValueError('First scan seven tiles with a stable reading, or explicitly select Enter hand manually.')
        hand=parse_hand(self.hand_entry.get('1.0','end'))
        if not self.manual_hand and self.hand_evidence is None:raise ValueError('No camera reading of your hand has been captured.')
        if not messagebox.askyesno('Confirm hand','Save these seven tiles? After confirming, remove all of them from camera view.\n'+' '.join(map(str,hand)),parent=self.root):return
        self.session=PhysicalSession(hand);self.phase='clear_table';self.alignment_ids=None;self.adapter.reset();self.invalidate_advice()
        self.autosave();self.refresh();self.status.set('Hand saved. Remove the seven tiles, select the starting player after the draw, and confirm the empty table.')

    def align_table(self):
        if not self.session or self.phase not in ('clear_table','reconcile'):raise ValueError('No table alignment is required.')
        if not self.bundle:raise ValueError('A camera reading of the table is required for alignment.')
        if self.alignment_ids is None:raise ValueError('Wait for a stable, up-to-date table reading.')
        identities=self.alignment_ids
        if self.phase=='clear_table':
            if identities:raise ValueError('The table must be empty: remove your hand tiles.')
            self.session=PhysicalSession(self.session.initial_hand,Player.ASSISTED if self.first.get()=='YOU' else Player.OPPONENT)
        self.session.confirm_alignment(identities);self.memory.clear();self.memory.accept(self.bundle['report'],self.session.state);self.phase='playing';self.adapter.reset();self.ignored=None
        self.invalidate_advice();self.autosave();self.refresh();self.status.set('Table confirmed. Place one tile at a time; each proposed move requires confirmation.')

    def manual_move(self):self.move_dialog(False)
    def correct(self):self.move_dialog(True)

    def move_dialog(self,correction):
        if not self.session or self.phase!='playing':raise ValueError('First register your hand and confirm the table.')
        pending=self.session.pending
        if correction and not pending:raise ValueError('No proposal to correct.')
        if not correction and pending:raise ValueError('Use Correct or Discard on the pending proposal.')
        dialog=tk.Toplevel(self.root);dialog.title('Orientation in the LOGICAL CHAIN');dialog.transient(self.root);dialog.grab_set()
        oriented=pending.move.orientation if pending and not pending.move.is_pass else OrientedTile(0,0)
        if not pending and self.bundle:
            baseline={t.tile for t in self.session.state.chain}
            candidates=[r['identity'] for r in self.bundle['report']['readings'] if r['identity'] and Tile(*r['identity']) not in baseline]
            if len(candidates)==1:oriented=OrientedTile(*candidates[0])
        a=tk.IntVar(value=oriented.left);b=tk.IntVar(value=oriented.right);side=tk.StringVar(value=pending.move.side.value if pending and pending.move.side else 'RIGHT')
        ttk.Label(dialog,text='Faces in the logical chain: first and second.\nThese are not necessarily camera left and right.',padding=12).pack()
        row=ttk.Frame(dialog,padding=10);row.pack()
        ttk.Spinbox(row,from_=0,to=6,textvariable=a,width=4).pack(side='left');ttk.Label(row,text=' | ').pack(side='left')
        ttk.Spinbox(row,from_=0,to=6,textvariable=b,width=4).pack(side='left')
        ttk.Combobox(row,textvariable=side,values=('LEFT','RIGHT'),state='readonly',width=8).pack(side='left',padx=10)
        def invert():av,bv=a.get(),b.get();a.set(bv);b.set(av)
        ActionButton(dialog,text='Reverse orientation',command=invert).pack(pady=5)
        def submit():
            move=Move(Tile(a.get(),b.get()),Side(side.get()),OrientedTile(a.get(),b.get()))
            if correction:self.session.correct(pending.id,move)
            else:self.session.propose(move,source='manual')
            self.refresh();dialog.destroy()
        ActionButton(dialog,text='Propose and validate (then press CONFIRM)',command=lambda:self.safe(submit)).pack(padx=12,pady=12)

    def confirm_move(self):
        if not self.session or not self.session.pending:raise ValueError('No proposal to confirm.')
        identifier=self.session.pending.id
        if self.session.pending.source.startswith('vision') and (self.last_frame_at is None or time.monotonic()-self.last_frame_at>3):
            self.session.discard();self.refresh();raise ValueError('Video is out of date: wait for a new reading before confirming.')
        self.session.commit(identifier)
        if self.last_effective_report:self.memory.accept(self.last_effective_report,self.session.state)
        self.adapter.reset();self.ignored=None;self.invalidate_advice();self.autosave();self.refresh()
        self.status.set('Move confirmed. Game state and turn updated.')

    def reread(self):
        if self.phase=='registration_review':self.scan_hand();return
        if self.session:self.session.discard()
        self.adapter.reset();self.ignored=None;self.refresh();self.status.set('Previous proposal cleared. Waiting for a new stable reading.')

    def discard(self):
        if not self.session:return
        self.session.discard();self.ignored=self.adapter.signature;self.adapter.reset();self.refresh()
        self.status.set('Proposal discarded. Remove or reposition the tile, or press Rescan to try again.')

    def pass_move(self):
        if not self.session or self.phase!='playing':raise ValueError('No active game.')
        attested=False
        if self.session.state.turn==Player.OPPONENT:
            attested=messagebox.askyesno('Opponent pass','Does your opponent confirm that they have no legal moves? The camera cannot verify their hand.',parent=self.root)
            if not attested:return
        self.session.propose(Move(),source='human_pass',attested=attested);self.refresh()

    def undo(self):
        if not self.session:raise ValueError('No game in progress.')
        if not messagebox.askyesno('Undo','Undo the last event? You will then need to realign the physical table.',parent=self.root):return
        self.session.undo();self.memory.clear();self.phase='reconcile';self.alignment_ids=None;self.adapter.reset();self.invalidate_advice();self.autosave();self.refresh()
        self.status.set('Move undone. Restore the physical table, then press Confirm table alignment.')

    def opponent_score(self):
        if not self.session or self.session.state.phase!='awaiting_opponent_score':raise ValueError('Opponent points are requested after two consecutive passes.')
        score=simpledialog.askinteger('Blocked game','Points remaining in the opponent hand (confirmed by a person):',minvalue=0,maxvalue=84,parent=self.root)
        if score is not None and messagebox.askyesno('Confirm points',f'Confirm {score} opponent points?',parent=self.root):
            self.session.confirm_opponent_score(score,attested=True);self.autosave();self.refresh()

    def autosave(self):
        self.session_folder.mkdir(parents=True,exist_ok=True)
        if self.session:(self.session_folder/'physical_game.json').write_text(self.session.to_json(),encoding='utf-8')

    def save_game(self):
        if not self.session:raise ValueError('No game to save.')
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',filetypes=[('Physical game','*.json')])
        if path:Path(path).write_text(self.session.to_json(),encoding='utf-8')

    def load_game(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('Physical game','*.json')])
        if not path:return
        session=PhysicalSession.from_json(Path(path).read_text(encoding='utf-8'))
        self.session=session;self.memory.clear();self.phase='reconcile';self.alignment_ids=None;self.adapter.reset();self.invalidate_advice();self.refresh()
        self.status.set('Saved game replayed. Align the physical table before resuming automatic recognition.')

    def save_frame(self):
        if not self.bundle:self.status.set('No frame available.');return
        if len(self.saving)>=2:self.status.set('Wait for the current saves to finish.');return
        self.saving.append(self.io.submit(save_original,self.bundle['original']));self.status.set('Saving original frame...')

    def save_debug(self):
        if not self.bundle:self.status.set('No diagnostics available.');return
        if len(self.saving)>=2:self.status.set('Wait for the current saves to finish.');return
        self.saving.append(self.io.submit(save_bundle,self.bundle,self.session_folder,'manual_D',self.bundle.get('timing')))
        self.status.set('Saving diagnostics...')

    def restart_camera(self):
        if self.restarting:return
        self.restarting=True
        if self.vision.thread and self.vision.thread.is_alive():
            self.status.set('Stopping the camera…')
            self.vision.stop_event.set()
            self.root.after(200,self._finish_camera_restart);return
        self._finish_camera_restart()
        self.camera_status.set('Connecting to Camo...')

    def _finish_camera_restart(self):
        if self.closed:return
        if self.vision.thread and self.vision.thread.is_alive():
            self.root.after(200,self._finish_camera_restart);return
        # Non aprire una seconda camera se il precedente driver è ancora in chiusura.
        if self.vision.camera and self.vision.camera.thread.is_alive():
            self.restarting=False;self.camera_status.set('Camo is not releasing the camera: close and reopen Camo before trying again.');return
        self.memory.clear();self.vision=VisionWorker();self.bundle=None;self.last_frame_at=None;self.alignment_ids=None
        self.adapter.reset()
        if self.session and self.session.pending and self.session.pending.source.startswith('vision'):self.session.discard()
        self.restarting=False;self.refresh();self.vision.start()

    def invalidate_advice(self):
        self.advice.invalidate();self.ranking=None;self.best_move.set('Waiting for your turn to recommend a move.')
        self.moves.delete(*self.moves.get_children());self.set_text(self.explanation,'')
        self.diagnostics.set('Waiting for your turn and a confirmed game state.')

    def level_changed(self):self.invalidate_advice()

    def refresh(self):
        self.update_workflow()
        pending=self.session.pending if self.session else None
        if self.session:
            state=self.session.state
            self.hand_panel.update_hand(state.hand,state.ends,state.opponent_count,self.ranking.recommendation.tile if self.ranking and self.ranking.recommendation else None)
        else:self.hand_panel.update_hand((),None,7)
        self.notice.configure(bg='#fbe9e6' if pending and not pending.legal else '#e8efdf',fg='#ab3e37' if pending and not pending.legal else '#20352e')
        self.confirm_button.configure(state='normal' if pending and pending.legal else 'disabled')
        if pending:
            self.pending_text.set(('Your move: ' if pending.player==Player.ASSISTED else 'Opponent move: ')+self.move_label(pending.move)+'\n'+('Reading ready: check and confirm.' if pending.legal else 'Needs correction: '+str(pending.error)))
        else:self.pending_text.set('Waiting for a new tile on the table…')
        if not self.session:self.set_text(self.state_text,'Register seven tiles.\nThe opponent hand is never stored.');return
        state=self.session.state
        outcome=''
        if state.phase=='finished':outcome='\nRESULT: '+('DRAW' if state.winner is None else 'YOU WIN' if state.winner==Player.ASSISTED else 'YOU LOSE')
        elif state.phase=='awaiting_opponent_score':outcome='\nBLOCKED GAME: waiting for opponent points. The winner is not yet known.'
        text=(f'Points in your hand: {sum(t.points for t in state.hand)}\n\nCONFIRMED CHAIN\n'+
              (' — '.join(map(str,state.chain)) or 'No tiles on the table yet.')+
              '\n\nA = start · B = end of the chain\nLetters mark the logical ends, even after a turn.'+outcome)
        text+='\n\nRECENT MOVES\n'+'\n'.join(f'{i+1}. '+('You' if event.player==Player.ASSISTED else 'Opponent')+': '+self.move_label(event.move) for i,event in list(enumerate(state.history))[-6:])
        self.set_text(self.state_text,text)

    def explain(self,event=None):
        if not self.ranking or not self.moves.selection():return
        index=int(self.moves.selection()[0]);self.set_text(self.explanation,self.ranking.moves[index].explanation)

    def display_frame(self,bundle):
        annotated=bundle['original'].copy()
        report=self.last_effective_report or bundle['report']
        pending=self.session.pending if self.session else None
        endpoints={}
        if self.session and self.session.state.chain:
            endpoints[self.session.state.chain[0].tile]='A'
            last=self.session.state.chain[-1].tile
            endpoints[last]=endpoints.get(last,'')+' / B' if last in endpoints else 'B'
        for geometry,reading in zip(report['detections'],report['readings']):
            identity=reading.get('identity');tile=Tile(*identity) if identity else None
            held=reading.get('temporal_reused',False)
            color=(80,190,145) if held else (220,175,70) if identity else (60,140,245)
            label=f'[{identity[0]}|{identity[1]}]' if identity else '[?|?]'
            if held:label+=' confirmed *'
            if tile in endpoints:label=endpoints[tile]+'  '+label
            if pending and not pending.move.is_pass and tile==pending.move.tile:color=(100,200,245)
            polygon=np.int32(geometry['vertices']);cv2.polylines(annotated,[polygon],True,color,2)
            x=max(0,int(polygon[:,0].min()));y=max(22,int(polygon[:,1].min())-5)
            width=cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,.55,1)[0][0]
            x=min(x,max(0,annotated.shape[1]-width-10))
            cv2.rectangle(annotated,(x,y-21),(x+width+8,y+3),(40,55,40),-1)
            cv2.putText(annotated,label,(x+4,y-3),cv2.FONT_HERSHEY_SIMPLEX,.55,(245,250,245),1,cv2.LINE_AA)
        scale=min(max(100,self.video.winfo_width())/annotated.shape[1],max(100,self.video.winfo_height())/annotated.shape[0]);width=max(1,int(annotated.shape[1]*scale));height=max(1,int(annotated.shape[0]*scale))
        encoded=cv2.imencode('.png',cv2.resize(annotated,(width,height)))[1]
        self.photo=tk.PhotoImage(data=base64.b64encode(encoded).decode('ascii'));self.video.configure(image=self.photo,text='')
        report=bundle['report'];timing=bundle.get('timing',{})
        self.camera_status.set(f'{bundle["original"].shape[1]}x{bundle["original"].shape[0]} | camera {timing.get("camera_fps",0):.1f} FPS | processed {timing.get("processing_fps",0):.1f} FPS | pipeline {report["pipeline_ms"]:.0f}ms\nTiles {report["detected_count"]}; recognized {report["recognized_count"]}; uncertain {report["unknown_count"]}'+(f' | {len(self.memory.held)} confirmed from memory *' if self.memory.held else ''))

    def process_bundle(self,bundle):
        self.bundle=bundle;self.last_frame_at=time.monotonic()
        report=self.memory.reconcile(bundle['report'],self.session.state) if self.session and self.phase=='playing' else bundle['report']
        self.last_effective_report=report;self.display_frame(bundle)
        pending=self.session.pending if self.session else None
        if pending and pending.source.startswith('vision'):
            try:
                probe=VisionAdapter(required_frames=1,minimum_seconds=0)
                observed=probe.observation(report,self.session.state)
                new=next(t for t in observed.tiles if Tile(t.a,t.b)==pending.move.tile)
                if new.to_move()!=pending.move:raise ValueError('The placement has changed.')
            except (ValueError,StopIteration):
                self.session.discard();self.adapter.reset();self.refresh()
                self.status.set('The reading has changed: waiting for a new stable placement.');return
        try:
            if self.phase=='registration':
                tiles,_=self.adapter.stable_tiles(report)
                if len(tiles)!=7:raise ValueError(f'Hand scan: detected {len(tiles)} identities; all seven must be visible together.')
                self.hand_evidence=tuple(t.identity for t in tiles);self.hand_entry.delete('1.0','end')
                self.hand_entry.insert('1.0',' '.join(f'{t.a}|{t.b}' for t in self.hand_evidence));self.phase='registration_review'
                self.refresh();self.status.set('Seven tiles scanned. Check the values and press Confirm my hand.')
            elif self.phase in ('clear_table','reconcile'):
                tiles,_=self.adapter.stable_tiles(report)
                expected=set() if self.phase=='clear_table' else {t.tile for t in self.session.state.chain}
                self.alignment_ids=[t.identity for t in tiles] if {t.identity for t in tiles}==expected else None
                self.update_workflow()
                self.status.set('Table ready: press the green button.' if self.alignment_ids is not None else 'Remove the unexpected tiles from the table.')
            elif self.phase=='playing' and self.session and self.session.state.phase=='active' and not self.session.pending:
                signature=tuple(sorted(tuple(sorted(r['identity'])) for r in report['readings'] if r['identity']))
                if self.ignored==signature:return
                if self.ignored is not None:self.ignored=None;self.adapter.reset()
                scene=self.adapter.observation(report,self.session.state)
                self.session.observe(scene);self.refresh();self.status.set('New move proposed: check the tile, logical end and orientation before confirming.')
        except ValueError as exc:
            if self.phase in ('clear_table','reconcile'):self.alignment_ids=None;self.update_workflow()
            self.status.set(english_error(exc))
            if self.phase=='playing':
                self.pending_text.set(english_error(exc));self.notice.configure(bg='#f1e9d4' if english_error(exc).startswith(('New tile','No new placement')) else '#fbe9e6',fg='#73613b' if english_error(exc).startswith(('New tile','No new placement')) else '#ab3e37')
                # Conserva il caso reale per la diagnosi, senza una coda illimitata.
                if self.auto_debug_count<20 and len(self.saving)<2 and time.monotonic()-self.last_auto_debug>15 and not english_error(exc).startswith(('No new placement','New tile read')):
                    self.last_auto_debug=time.monotonic();self.auto_debug_count+=1
                    self.saving.append(self.io.submit(save_bundle,bundle,self.session_folder,'automatic_reading_issue',bundle.get('timing')))

    def poll(self):
        if self.closed:return
        try:
            for job in list(self.saving):
                if job.done():
                    self.saving.remove(job);self.status.set('Saved: '+str(job.result()))
            item=self.vision.poll()
            if item:
                if item[0]=='frame':self.process_bundle(item[1])
                else:
                    self.alignment_ids=None;self.adapter.reset();self.update_workflow();self.camera_status.set('CAMERA: '+english_error(item[1])+' — use Reconnect Camo')
                    if self.session and self.session.pending and self.session.pending.source.startswith('vision'):
                        self.session.discard();self.refresh()
            if self.last_frame_at is not None and time.monotonic()-self.last_frame_at>3:
                self.alignment_ids=None
                if self.session and self.session.pending and self.session.pending.source.startswith('vision'):
                    self.session.discard();self.refresh()
                self.update_workflow();self.camera_status.set('Video is delayed or frozen: check Camo. Automatic readings are paused.')
            if time.monotonic()-self.last_telemetry>5:
                self.last_telemetry=time.monotonic()
                self.session_folder.mkdir(parents=True,exist_ok=True)
                report=self.bundle['report'] if self.bundle else {}
                telemetry={'time':datetime.now().isoformat(),'phase':self.phase,'status':self.status.get(),
                           'camera':self.camera_status.get(),'detected':report.get('detected_count'),
                           'recognized':report.get('recognized_count'),'unknown':report.get('unknown_count'),
                           'timing':self.bundle.get('timing') if self.bundle else None,
                           'confirmed_events':len(self.session.journal) if self.session else 0,
                           'turn':self.session.state.turn.value if self.session else None,
                           'suggestion':self.best_move.get()}
                (self.session_folder/'live_status.json').write_text(json.dumps(telemetry,indent=2),encoding='utf-8')
            if self.session:
                self.advice.request(self.session,self.level.get());ranking=self.advice.poll(self.session,self.level.get())
                if ranking:
                    if ranking.diagnostics.limit=='inconsistent_knowledge':raise ValueError('Inconsistent game information: correct the game before requesting recommendations.')
                    self.ranking=ranking;self.moves.delete(*self.moves.get_children())
                    for index,row in enumerate(ranking.moves):
                        self.moves.insert('','end',iid=str(index),values=(self.move_label(row.move),f'{row.score:.2f}'))
                    self.best_move.set('Recommended: '+self.move_label(ranking.recommendation))
                    diag=ranking.diagnostics
                    self.diagnostics.set(f'Recommendation: {ranking.recommendation}\nRequested/completed depth {diag.requested_depth}/{diag.completed_depth}; nodes {diag.nodes}; samples {diag.samples}; {diag.elapsed_ms:.0f}ms; limit {diag.limit or "none"}.')
                    if ranking.moves:self.moves.selection_set('0');self.explain()
                    self.refresh()
        except Exception as exc:self.status.set('Recoverable error: '+english_error(exc))
        self.poll_id=self.root.after(80,self.poll)

    def close(self):
        self.closed=True
        if getattr(self,'poll_id',None):self.root.after_cancel(self.poll_id)
        try:self.autosave()
        finally:
            self.vision.close();self.advice.close();self.io.shutdown(wait=False,cancel_futures=False);self.root.destroy()


def choose_mode(root):
    root.title('Reto 07 — Domino AI');root.geometry('620x320')
    frame=ttk.Frame(root,padding=30);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Reto 07 — Domino AI',font=('Segoe UI',20,'bold')).pack(pady=10)
    ttk.Label(frame,text='Choose a mode. All recommendations are calculated locally.').pack(pady=8)
    ActionButton(frame,text='PHYSICAL GAME — Camo + AI assistance against a human',command=lambda:PhysicalApp(root)).pack(fill='x',pady=10)
    def virtual():
        for child in root.winfo_children():child.destroy()
        from domino_engine.controller import GameController
        from domino_engine.gui import DominoApp
        DominoApp(root,GameController(42,3),assist=True)
    ActionButton(frame,text='VIRTUAL SIMULATOR — offline, no camera',command=virtual).pack(fill='x',pady=10)
