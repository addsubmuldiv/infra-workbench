"""Native, rounded picker rows and slim scrollbar, matching the floating monitor."""
from backend.host_alias import host_label, matches_name
from backend.interface_language import tr, current_locale
import tkinter as tk
from tkinter import font as tkfont
from PIL import ImageTk
from .floating_drawing import rounded_sprite


class MachinePickerList(tk.Frame):
    def __init__(self,master,monitor,search_var,on_change):
        super().__init__(master,bg=monitor.BG)
        self.monitor,self.search_var,self.on_change=monitor,search_var,on_change
        self.scale=monitor.dpi_scale
        self.canvas=tk.Canvas(self,bg=monitor.BG,highlightthickness=0,bd=0,yscrollincrement=round(48*self.scale))
        self.scrollbar=tk.Canvas(self,width=round(10*self.scale),bg=monitor.BG,highlightthickness=0,bd=0,cursor='hand2')
        self.scrollbar.pack(side='right',fill='y',padx=(5,0))
        self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.configure(yscrollcommand=self.set_scroll)
        self.canvas.bind('<Configure>',lambda event:self.schedule())
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.scrollbar.bind('<MouseWheel>',self.wheel)
        self.scrollbar.bind('<Configure>',lambda event:self.set_scroll(*self.canvas.yview()))
        self.scrollbar.bind('<Button-1>',self.scroll_start)
        self.scrollbar.bind('<B1-Motion>',self.scroll_drag)
        self._pending=None
        self._cache={}
        self._images=[]
        self._commands=[]
        self._thumb=(0,1)
        self._scroll_origin=None
        self.filtered_ids=[]
        self.font=tkfont.Font(root=monitor.root,family='Microsoft YaHei UI',size=9,weight='bold')
        self.small_font=tkfont.Font(root=monitor.root,family='Microsoft YaHei UI',size=8)
        search_var.trace_add('write',self.filter_changed)
        for variable in monitor.machine_choices.values():variable.trace_add('write',self.changed)
        self.schedule()

    def photo(self,width,height,radius,fill,outline):
        key=(max(1,round(width)),max(1,round(height)),max(1,round(radius)),fill,outline,self.monitor.BG)
        if key not in self._cache:
            if len(self._cache)>256:self._cache.clear()
            self._cache[key]=ImageTk.PhotoImage(rounded_sprite(*key),master=self.monitor.root)
        image=self._cache[key]
        if image not in self._images:self._images.append(image)
        return image

    def schedule(self,*args):
        if self._pending is None:self._pending=self.after_idle(self.redraw)

    def changed(self,*args):
        self.on_change()
        self.schedule()

    def filter_changed(self,*args):
        self.canvas.yview_moveto(0)
        self.schedule()

    def theme_update(self,palette):
        self.configure(bg=palette['panel'])
        self.canvas.configure(bg=palette['panel'])
        self.scrollbar.configure(bg=palette['panel'])
        self.schedule()

    def redraw(self):
        self._pending=None
        if not self.winfo_exists():return
        c,p,s=self.canvas,self.monitor.palette,self.scale
        c.delete('all')
        for command in self._commands:
            try:c.deletecommand(command)
            except tk.TclError:pass
        commands_before=set(c._tclCommands or [])
        self._images=[]
        width=max(60,c.winfo_width())
        term=self.search_var.get().strip()
        hosts=[h for h in self.monitor.hosts if matches_name(h,term)]
        self.filtered_ids=[h['id'] for h in hosts]
        stride=round(48*s)
        height=round(42*s)
        for index,host in enumerate(hosts):
            y=index*stride
            checked=self.monitor.machine_choices[host['id']].get()
            fill=p['accent-bg'] if checked else p['panel']
            border=p['accent'] if checked else p['line']
            tag='choice-'+host['id']
            background=c.create_image(1,y+1,image=self.photo(width-3,height,9*s,fill,border),anchor='nw',tags=tag)
            size=round(16*s);cx=round(12*s);cy=y+(height-size)//2
            c.create_image(cx,cy,image=self.photo(size,size,4*s,p['accent'] if checked else p['panel2'],p['accent'] if checked else p['line']),anchor='nw',tags=tag)
            if checked:c.create_text(cx+size/2,cy+size/2,text='✓',font=self.small_font,fill=p['panel'],tags=tag)
            name=host_label(host);max_width=width-round(62*s)
            while len(name)>1 and self.font.measure(name)>max_width:name=name[:-2]+'…'
            c.create_text(round(40*s),y+round(13*s),text=name,anchor='w',font=self.font,fill=p['text'],tags=tag)
            devices=host.get('snapshot',{}).get('devices',[])
            model=devices[0].get('name','') if devices else ''
            info=tr(f'{len(devices)} 张卡', f'{len(devices)} devices')+(' · '+model if model else '')
            while len(info)>1 and self.small_font.measure(info)>max_width:info=info[:-2]+'…'
            c.create_text(round(40*s),y+round(30*s),text=info,anchor='w',font=self.small_font,fill=p['muted'],tags=tag)
            def toggle(event,ident=host['id']):
                variable=self.monitor.machine_choices[ident]
                variable.set(not variable.get())
            def hover(event,item=background,color=fill):
                c.configure(cursor='hand2')
                c.itemconfigure(item,image=self.photo(width-3,height,9*s,p['hover'],p['accent']))
            def leave(event,item=background,color=fill,line=border):
                c.configure(cursor='')
                c.itemconfigure(item,image=self.photo(width-3,height,9*s,color,line))
            c.tag_bind(tag,'<Button-1>',toggle)
            c.tag_bind(tag,'<Enter>',hover)
            c.tag_bind(tag,'<Leave>',leave)
        if not hosts:c.create_text(12,20,text=tr('没有匹配的机器', 'No matching machines'),anchor='w',fill=p['muted'],font=self.small_font)
        c.configure(scrollregion=(0,0,width,max(1,len(hosts)*stride)))
        self._commands=list(set(c._tclCommands or [])-commands_before)
        self.set_scroll(*c.yview())

    def wheel(self,event):
        if event.delta:self.canvas.yview_scroll(-max(1,abs(int(event.delta/120))) if event.delta>0 else max(1,abs(int(event.delta/120))),'units')
        return 'break'

    def set_scroll(self,first,last):
        first,last=float(first),float(last)
        c=self.scrollbar;c.delete('all')
        width,height=c.winfo_width(),c.winfo_height()
        if last-first>=.999:
            self._thumb=(0,height);return
        thumb=max(round(26*self.scale),height*(last-first))
        top=(height-thumb)*first/max(.001,1-(last-first))
        image=self.photo(max(2,width-2),max(1,round(thumb)),max(2,(width-2)//2),self.monitor.palette['muted'],self.monitor.palette['muted'])
        c._thumb_image=image
        c.create_image(1,top,image=image,anchor='nw')
        self._thumb=(top,top+thumb)

    def scroll_start(self,event):
        first,last=self.canvas.yview()
        if not self._thumb[0]<=event.y<=self._thumb[1]:
            self.canvas.yview_moveto(max(0,event.y/max(1,self.scrollbar.winfo_height())-(last-first)/2))
            first,last=self.canvas.yview()
        self._scroll_origin=(event.y,first,last-first)

    def scroll_drag(self,event):
        if not self._scroll_origin:return
        y,first,visible=self._scroll_origin
        travel=max(1,self.scrollbar.winfo_height()-(self._thumb[1]-self._thumb[0]))
        self.canvas.yview_moveto(first+(event.y-y)/travel*(1-visible))


def rounded_search(master,monitor,variable):
    canvas=tk.Canvas(master,bg=monitor.BG,height=round(34*monitor.dpi_scale),highlightthickness=0,bd=0)
    entry=tk.Entry(canvas,textvariable=variable,bd=0,relief='flat',highlightthickness=0,font=('Microsoft YaHei UI',9))
    entry_id=canvas.create_window(12*monitor.dpi_scale,17*monitor.dpi_scale,window=entry,anchor='w')
    placeholder=tk.Label(canvas,text=tr('搜索机器…', 'Search machines…'),font=('Microsoft YaHei UI',9),cursor='xterm')
    placeholder_id=canvas.create_window(12*monitor.dpi_scale,17*monitor.dpi_scale,window=placeholder,anchor='w')
    def hint(*args):
        canvas.itemconfigure(placeholder_id,state='hidden' if variable.get() or entry.focus_get() is entry else 'normal')
    def focus(event):
        entry.focus_set();hint()
    placeholder.bind('<Button-1>',focus)
    entry.bind('<FocusIn>',hint)
    entry.bind('<FocusOut>',hint)
    variable.trace_add('write',hint)
    def draw(*args):
        p=monitor.palette;width=max(30,canvas.winfo_width());height=round(34*monitor.dpi_scale)
        canvas.configure(bg=p['panel'])
        entry.configure(bg=p['input'],fg=p['text'],insertbackground=p['accent'])
        placeholder.configure(bg=p['input'],fg=p['muted'])
        hint()
        image=ImageTk.PhotoImage(rounded_sprite(width,height,round(9*monitor.dpi_scale),p['input'],p['line'],p['panel']),master=monitor.root)
        canvas._background=image
        canvas.delete('border')
        border=canvas.create_image(0,0,image=image,anchor='nw',tags='border')
        canvas.tag_lower(border)
        canvas.itemconfigure(entry_id,width=max(10,width-round(24*monitor.dpi_scale)))
    canvas.bind('<Configure>',draw)
    canvas.theme_update=draw
    return canvas,entry
