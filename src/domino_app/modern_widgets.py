"""Widget desktop locali, palette e tiles ispirate al progetto web approvato."""
import tkinter as tk
from tkinter import font as tkfont

PAPER='#f5f4ef';INK='#20352e';GREEN='#184e3b';IVORY='#fffdf5';MUTED='#6a756e';GOLD='#e5b661'


def rounded(canvas,x,y,w,h,r=10,**kwargs):
    return canvas.create_polygon(x+r,y,x+w-r,y,x+w,y,x+w,y+r,x+w,y+h-r,x+w,y+h,x+w-r,y+h,x+r,y+h,x,y+h,x,y+h-r,x,y+r,x,y,smooth=True,**kwargs)


class ActionButton(tk.Canvas):
    def __init__(self,parent,text='',command=None,style='',**kwargs):
        self.label=text;self.command=command;self.enabled=True;self.primary=style=='Primary.TButton';self.hover=False
        self.text_font=tkfont.Font(family='Segoe UI',size=10,weight='bold' if self.primary else 'normal')
        super().__init__(parent,highlightthickness=0,bd=0,background=PAPER,takefocus=1,
                         width=self.text_font.measure(text)+30,height=self.text_font.metrics('linespace')+(22 if self.primary else 16),**kwargs)
        self.bind('<Configure>',lambda e:self.draw());self.bind('<Enter>',lambda e:self.over(True));self.bind('<Leave>',lambda e:self.over(False))
        self.bind('<Button-1>',lambda e:self.invoke());self.bind('<Return>',lambda e:self.invoke());self.bind('<space>',lambda e:self.invoke())
        self.bind('<FocusIn>',lambda e:self.draw());self.bind('<FocusOut>',lambda e:self.draw())
        self.draw()

    def over(self,value):self.hover=value;self.draw()

    def configure(self,cnf=None,**kwargs):
        if cnf:kwargs.update(cnf)
        if 'text' in kwargs:
            self.label=kwargs.pop('text');super().configure(width=self.text_font.measure(self.label)+30)
        if 'state' in kwargs:self.enabled=kwargs.pop('state')!='disabled'
        if 'command' in kwargs:self.command=kwargs.pop('command')
        if 'style' in kwargs:self.primary=kwargs.pop('style')=='Primary.TButton'
        if kwargs:super().configure(**kwargs)
        self.draw()
    config=configure

    def cget(self,key):
        if key=='state':return 'normal' if self.enabled else 'disabled'
        if key=='text':return self.label
        return super().cget(key)
    __getitem__=cget

    def draw(self):
        self.delete('all');w=max(self.winfo_width(),int(super().cget('width')) if self.winfo_width()==1 else 1);h=int(super().cget('height'))
        fill=('#103e2e' if self.hover else GREEN) if self.primary else ('#e9eee4' if self.hover else IVORY)
        if not self.enabled:fill='#e3e5dd'
        rounded(self,1,1,w-2,h-2,10,fill=fill,outline=GOLD if self.focus_get()==self else ('#d9ddd2' if not self.primary else fill),width=2 if self.focus_get()==self else 1)
        self.create_text(w/2,h/2,text=self.label,font=self.text_font,fill=('#8b958c' if not self.enabled else 'white' if self.primary else INK))
        super().configure(cursor='hand2' if self.enabled else '')

    def invoke(self):
        if self.enabled and self.command:return self.command()


PIPS={0:[],1:[(1,1)],2:[(0,0),(2,2)],3:[(0,0),(1,1),(2,2)],4:[(0,0),(2,0),(0,2),(2,2)],5:[(0,0),(2,0),(1,1),(0,2),(2,2)],6:[(0,0),(0,1),(0,2),(2,0),(2,1),(2,2)]}

def draw_tile(canvas,x,y,a,b,w=46,h=88,highlight=False):
    rounded(canvas,x+1,y+3,w,h,6,fill='#d9d4c4',outline='')
    rounded(canvas,x,y,w,h,6,fill=IVORY,outline=GOLD if highlight else '#d8d4c6',width=3 if highlight else 1)
    canvas.create_line(x+6,y+h/2,x+w-6,y+h/2,fill='#b5baaa')
    for offset,value in ((0,a),(h/2,b)):
        for px,py in PIPS[value]:
            cx=x+w*(.25+.25*px);cy=y+offset+h/2*(.25+.25*py);r=max(2,w*.055)
            canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=INK,outline='')


class HandPanel(tk.Canvas):
    def __init__(self,parent):
        super().__init__(parent,height=156,background=IVORY,highlightthickness=0)
        self.hand=();self.ends=None;self.opponent=7;self.recommendation=None
        self.bind('<Configure>',lambda e:self.draw())
    def update_hand(self,hand,ends,opponent,recommendation=None):
        self.hand=hand;self.ends=ends;self.opponent=opponent;self.recommendation=recommendation;self.draw()
    def draw(self):
        self.delete('all');w=max(300,self.winfo_width())
        self.create_text(14,17,text='YOUR HAND',anchor='w',font=('Segoe UI',9,'bold'),fill=MUTED)
        self.create_text(w-14,17,text=f'Opponent · {self.opponent} tiles',anchor='e',font=('Segoe UI',9),fill=MUTED)
        tile_w=min(46,(w-36)/max(7,len(self.hand))-7)
        for i,t in enumerate(self.hand):draw_tile(self,14+i*(tile_w+8),36,t.a,t.b,w=tile_w,h=76,highlight=t==self.recommendation)
        if not self.hand:self.create_text(16,70,text='Your tiles will appear here.',anchor='w',font=('Segoe UI',11),fill=MUTED)
        self.create_text(14,138,text='Open ends: '+('  ·  '.join(map(str,self.ends)) if self.ends else 'empty table'),anchor='w',font=('Segoe UI',11,'bold'),fill=GREEN)
