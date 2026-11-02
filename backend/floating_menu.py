"""Theme-matched machine actions, alive until an action or dismissal."""
import tkinter as tk


class MachineContextMenu(tk.Toplevel):
    def __init__(self, monitor, x, y, actions):
        super().__init__(monitor.root)
        from backend.floating_monitor import style_native_window
        from backend.floating_position import monitor_work_area
        self.withdraw()
        self.overrideredirect(True)
        self.transient(monitor.root)
        self.attributes('-topmost', True)
        p,s=monitor.palette,monitor.dpi_scale
        self.configure(bg=p['panel'],highlightthickness=0)
        self.corner_radius=round(11*s)
        self.background=tk.Canvas(self,bg=p['panel'],bd=0,highlightthickness=0)
        self.background.place(x=0,y=0,relwidth=1,relheight=1)
        content=tk.Frame(self,bg=p['panel'])
        content.pack(fill='both',expand=True,padx=round(5*s),pady=round(5*s))
        def redraw(event=None):
            if not self.winfo_exists():return
            from PIL import ImageTk
            from backend.floating_drawing import rounded_sprite
            width,height=self.winfo_width(),self.winfo_height()
            if width<2 or height<2 or getattr(self,'_draw_size',None)==(width,height):return
            self._draw_size=(width,height)
            self._outline=ImageTk.PhotoImage(rounded_sprite(width,height,self.corner_radius,p['panel'],p['line'],p['panel']),master=self)
            self.background.delete('all')
            self.background.create_image(0,0,image=self._outline,anchor='nw')
            style_native_window(self,self.corner_radius)
        self.bind('<Configure>',lambda event:redraw() if event.widget==self else None)
        self.bind('<Map>',lambda event:self.after_idle(redraw) if event.widget==self else None)
        self.action_buttons=[]
        def execute(command):
            self.dismiss()
            # Let Tk finish destroying/releasing the popup before launching another UI.
            monitor.root.after_idle(command)
        for index,(label,command) in enumerate(actions):
            if index==2:
                tk.Frame(content,bg=p['line'],height=1).pack(fill='x',padx=round(8*s),pady=round(3*s))
            button=tk.Button(content,text=label,anchor='w',font=('Microsoft YaHei UI',7),
                             bg=p['panel'],fg=p['text'],activebackground=p['hover'],activeforeground=p['accent'],
                             relief='flat',bd=0,highlightthickness=0,cursor='hand2',takefocus=True,
                             padx=round(8*s),pady=round(2*s),command=lambda c=command:execute(c))
            button.pack(fill='x',padx=round(3*s),pady=round(1*s))
            button.bind('<Enter>',lambda event,b=button:b.configure(bg=p['hover'],fg=p['accent']))
            button.bind('<Leave>',lambda event,b=button:b.configure(bg=p['panel'],fg=p['text']))
            button.bind('<Return>',lambda event,b=button:b.invoke())
            self.action_buttons.append(button)
        self.update_idletasks()
        width=max(round(108*s),self.winfo_reqwidth());height=self.winfo_reqheight()
        left,top,right,bottom=monitor_work_area(monitor.root)
        self.geometry(f'{width}x{height}{max(left,min(x,right-width)):+d}{max(top,min(y,bottom-height)):+d}')
        self.bind('<Escape>',lambda event:self.dismiss())
        self.bind('<FocusOut>',lambda event:self.after_idle(self.check_focus))
        self.bind('<ButtonPress-1>',self.outside_click)
        self.bind('<ButtonPress-3>',lambda event:self.dismiss())
        self.deiconify()
        self.update_idletasks()
        redraw()
        self.lift()
        self.focus_force()
        self.grab_set()

    def check_focus(self):
        if not self.winfo_exists():return
        focus=self.focus_get()
        if focus is None or focus.winfo_toplevel()!=self:self.dismiss()

    def outside_click(self,event):
        if not (self.winfo_rootx()<=event.x_root<self.winfo_rootx()+self.winfo_width() and
                self.winfo_rooty()<=event.y_root<self.winfo_rooty()+self.winfo_height()):
            self.dismiss()

    def dismiss(self):
        if not self.winfo_exists():return
        if self.grab_current()==self:self.grab_release()
        self.destroy()
