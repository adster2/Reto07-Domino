"""Tracker fisico con soli fatti conosciuti; nessun arbitro o mano avversaria."""
from dataclasses import dataclass,replace
import json
from threading import RLock
from uuid import uuid4
from domino_engine import Tile,Move,Player
from domino_engine.state import PublicEvent
from domino_engine.rules import moves_for,place
from domino_engine.knowledge import KnowledgeState
from domino_engine.events import MoveProposal


@dataclass(frozen=True)
class PhysicalState:
    hand: tuple
    chain: tuple=()
    turn: Player=Player.ASSISTED
    opponent_count: int=7
    history: tuple=()
    passes: int=0
    phase: str='active'
    winner: Player|None=None
    reason: str|None=None
    opponent_score: int|None=None

    @property
    def ends(self):return (self.chain[0].left,self.chain[-1].right) if self.chain else None

    def knowledge(self):
        if self.phase=='awaiting_opponent_score':
            raise ValueError('Blocked game: result unknown; wait for confirmed opponent points.')
        return KnowledgeState(Player.ASSISTED,self.hand,self.chain,self.turn,self.opponent_count,
                              self.history,self.passes,self.phase=='finished',self.winner,self.reason)

    def to_dict(self):
        return {'hand':[t.to_list() for t in self.hand],'chain':[t.to_list() for t in self.chain],
                'turn':self.turn.value,'opponent_count':self.opponent_count,
                'history':[e.to_dict() for e in self.history],'passes':self.passes,'phase':self.phase,
                'winner':self.winner.value if self.winner else None,'reason':self.reason,
                'opponent_score':self.opponent_score}


def initial_state(hand,first):
    hand=tuple(sorted(hand))
    if len(hand)!=7 or len(set(hand))!=7 or any(not isinstance(t,Tile) for t in hand):
        raise ValueError('Confirm exactly seven valid, distinct tile identities.')
    return PhysicalState(hand,turn=Player(first))


def transition(state,move,attested=False):
    if state.phase!='active':raise ValueError('The game is not accepting new moves.')
    actor=state.turn
    view=state.knowledge()
    if actor==Player.ASSISTED:
        if not move.is_pass and move.tile not in state.hand:raise ValueError(f'Tile {move.tile} is not in your hand. Use one of your registered tiles.')
        if move not in moves_for(state.hand,state.chain):raise ValueError('You cannot pass: you have playable tiles.' if move.is_pass else 'Invalid connection or orientation: check the values at the ends.')
    elif move.is_pass:
        if not attested:raise ValueError('An opponent pass requires explicit human confirmation.')
    else:
        if state.opponent_count<=0:raise ValueError('The opponent has no tiles remaining.')
        if move.tile in state.hand or move.tile in {t.tile for t in state.chain}:
            raise ValueError('The opponent tile is a duplicate or is in your hand.')
        if view.forbidden_opponent_values.intersection((move.tile.a,move.tile.b)):
            raise ValueError('The tile contradicts an earlier opponent pass: correct the history.')
        if move not in moves_for((move.tile,),state.chain):raise ValueError('Illegal contact, end or orientation.')
    own=tuple(t for t in state.hand if move.is_pass or actor!=Player.ASSISTED or t!=move.tile)
    count=state.opponent_count-int(actor==Player.OPPONENT and not move.is_pass)
    passes=state.passes+1 if move.is_pass else 0
    phase,winner,reason='active',None,None
    if not own or count==0:phase,winner,reason='finished',actor,'empty_hand'
    elif passes==2:phase,reason='awaiting_opponent_score','blocked'
    result=PhysicalState(own,place(state.chain,move),actor.other,count,
                         state.history+(PublicEvent(actor,move,state.ends),),passes,phase,winner,reason)
    if any(a.right!=b.left for a,b in zip(result.chain,result.chain[1:])):raise ValueError('The chain is disconnected.')
    check=replace(result,phase='active').knowledge() if phase=='awaiting_opponent_score' else result.knowledge()
    if phase!='finished' and len(check.opponent_candidates)<count:
        raise ValueError('The public information leaves too few possible tiles for the opponent.')
    return result


def score_transition(state,score,attested):
    if state.phase!='awaiting_opponent_score' or not attested:raise ValueError('Opponent points have not been confirmed or are not required.')
    if type(score) is not int or score<0:raise ValueError('Invalid point total.')
    view=replace(state,phase='active').knowledge()
    possible=[{0}]+[set() for _ in range(state.opponent_count)]
    for tile in view.opponent_candidates:
        for n in range(state.opponent_count,0,-1):possible[n].update(v+tile.points for v in possible[n-1])
    if score not in possible[state.opponent_count]:raise ValueError('The point total is inconsistent with the tile count and public information.')
    own=sum(t.points for t in state.hand)
    winner=Player.ASSISTED if own<score else Player.OPPONENT if own>score else None
    return replace(state,phase='finished',opponent_score=score,winner=winner)


class PhysicalSession:
    def __init__(self,hand,first=Player.ASSISTED):
        self.initial_hand=tuple(sorted(hand));self.first=Player(first)
        self._state=initial_state(hand,first);self._journal=[];self._pending=None
        self.session_id=uuid4().hex;self.revision=0;self.aligned=False
        self._lock=RLock()

    @property
    def state(self):
        with self._lock:return self._state

    @property
    def pending(self):
        with self._lock:return self._pending[0] if self._pending else None

    @property
    def journal(self):
        with self._lock:return json.loads(json.dumps(self._journal))

    def confirm_alignment(self,identities):
        with self._lock:
            given=list(identities)
            if len(given)!=len(set(given)) or set(given)!={t.tile for t in self._state.chain}:
                raise ValueError('The observed table does not match the confirmed chain.')
            self.aligned=True

    def pause_alignment(self):
        with self._lock:self.aligned=False;self._pending=None

    def propose(self,move,*,source='manual',attested=False,image_ref=None):
        with self._lock:
            if self._pending is not None:raise ValueError('A proposal is already pending: confirm, correct or discard it.')
            if not self.aligned:raise ValueError('First align and confirm the physical table.')
            try:
                after=transition(self._state,move,attested);legal,error,ends=True,None,after.ends
            except ValueError as exc:legal,error,ends=False,str(exc),None
            proposal=MoveProposal(self.session_id+':'+uuid4().hex,self.revision,self._state.turn,
                                   move,legal,error,ends,source,image_ref)
            self._pending=(proposal,bool(attested))
            return proposal

    def correct(self,identifier,move,*,attested=False):
        with self._lock:
            self._require(identifier);self._pending=None
            return self.propose(move,source='manual_correction',attested=attested)

    def _require(self,identifier):
        if self._pending is None or self._pending[0].id!=identifier:raise ValueError('Proposal expired or not found.')
        return self._pending

    def discard(self,identifier=None):
        with self._lock:
            if identifier is not None:self._require(identifier)
            self._pending=None

    def observe(self,scene,*,reread=False):
        with self._lock:
            if reread:self._pending=None
            elif self._pending:return self._pending[0]
            if scene.geometry_ambiguous:raise ValueError('Ambiguous geometry: correct or rescan.')
            identities=[Tile(t.a,t.b) for t in scene.tiles]
            if len(set(identities))!=len(identities):raise ValueError('Duplicate tile identities in the scene.')
            baseline={t.tile for t in self._state.chain}
            if not baseline.issubset(identities):raise ValueError('Confirmed tiles are missing or uncertain: no automatic removal.')
            new=set(identities)-baseline
            if len(new)!=1:raise ValueError('Exactly one new tile is required.')
            index=identities.index(next(iter(new)));item=scene.tiles[index]
            if not .8<=item.confidence<=1.:raise ValueError('Unstable reading or insufficient quality.')
            return self.propose(item.to_move(),source='vision_temporal_consistency',image_ref=scene.image_ref)

    def commit(self,identifier):
        with self._lock:
            if not isinstance(identifier,str) or not identifier.startswith(self.session_id+':'):
                raise ValueError('This identifier belongs to an older session.')
            if any(e['id']==identifier for e in self._journal):return self._state
            proposal,attested=self._require(identifier)
            if proposal.revision!=self.revision or not proposal.legal:raise ValueError(proposal.error or 'Stale revision.')
            result=transition(self._state,proposal.move,attested)
            event={'kind':'move','id':identifier,'player':proposal.player.value,'move':proposal.move.to_dict(),
                   'attested':attested,'source':proposal.source,'ends_before':list(self._state.ends) if self._state.ends else None}
            self._journal.append(event);self._state=result;self.revision+=1;self._pending=None
            return result

    def confirm_opponent_score(self,score,*,attested=False):
        with self._lock:
            result=score_transition(self._state,score,attested)
            self._journal.append({'kind':'score','id':self.session_id+':'+uuid4().hex,'score':score,'attested':attested,
                                  'source':'human_attestation'})
            self._state=result;self.revision+=1;self._pending=None

    def _replay(self,events):
        state=initial_state(self.initial_hand,self.first);seen=set()
        for event in events:
            if not isinstance(event.get('id'),str) or event['id'] in seen:raise ValueError('Duplicate identifiers.')
            seen.add(event['id'])
            if event['kind']=='move':
                if set(event)!={'kind','id','player','move','attested','source','ends_before'}:raise ValueError('Invalid event.')
                if event['player']!=state.turn.value or event['ends_before']!=(list(state.ends) if state.ends else None):
                    raise ValueError('Corrupted history or chain ends.')
                if type(event['attested']) is not bool:raise ValueError('Invalid confirmation.')
                state=transition(state,Move.from_dict(event['move']),event['attested'])
            elif event['kind']=='score':
                if set(event)!={'kind','id','score','attested','source'} or event['source']!='human_attestation':raise ValueError('Invalid points event.')
                state=score_transition(state,event['score'],event['attested'] is True)
            else:raise ValueError('Unknown event type.')
        return state

    def undo(self):
        with self._lock:
            if not self._journal:raise ValueError('No event to undo.')
            remaining=self._journal[:-1];result=self._replay(remaining)
            self._journal=remaining;self._state=result;self.revision+=1;self._pending=None;self.aligned=False

    def to_json(self):
        with self._lock:
            return json.dumps({'format':'reto07-physical','version':1,'initial_hand':[t.to_list() for t in self.initial_hand],
                               'first':self.first.value,'events':self._journal,'state':self._state.to_dict()},indent=2)

    @classmethod
    def from_json(cls,text):
        try:
            data=json.loads(text)
            if set(data)!={'format','version','initial_hand','first','events','state'} or data['format']!='reto07-physical' or type(data['version']) is not int or data['version']!=1:
                raise ValueError('Unsupported physical-game format.')
            result=cls(tuple(Tile(*t) for t in data['initial_hand']),Player(data['first']))
            state=result._replay(data['events'])
            if state.to_dict()!=data['state']:raise ValueError('The saved snapshot does not match the replay.')
            result._state=state;result._journal=data['events'];result.revision=len(data['events'])
            return result
        except (TypeError,KeyError,IndexError) as exc:raise ValueError('Corrupted physical-game save.') from exc
