"""The handheld game screen: pixel scene, green LCD, pills and round buttons."""
import math
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageDraw

from . import settings

BODY, BODY_DK, LCD, LCD_EDGE, INK = "#B8CC74", "#A7BC63", "#C9D4B3", "#98A584", "#3C4A33"
MAG, MAG_HI, MAG_DK, MAG_DIM = "#B5246F", "#D8579A", "#7C1048", "#8C5F76"
REC_RED, RUN_GREEN, PILL = "#E8452C", "#2E9E6B", "#3A3A3C"
SCENE_W, SCENE_H, PX = 100, 72, 4        # the scene is painted at 100 x 72 and zoomed 4x
CAT = [".o.....o.", "ooo...ooo", "ooooooooo", "oKooooKoo", "ooooPoooo",
       "owwwwwwwo", ".owwwwwo.", ".owwwwwo.", ".oo...oo."]
CAT_COLORS = {"o": "#F29A4A", "w": "#FFF3E0", "K": "#2F2323", "P": "#E86A8A"}


def mono(size, bold=False):
    return ("Menlo", size, "bold" if bold else "normal")


def lerp(a, b, t):
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


def to_photo(im):
    return tk.PhotoImage(data=b"P6 %d %d 255\n" % im.size + im.convert("RGB").tobytes(), format="PPM")


def make_scene():
    im = Image.new("RGB", (SCENE_W, SCENE_H))
    d = ImageDraw.Draw(im)
    for y in range(SCENE_H):                                   # banded sky
        d.line([(0, y), (SCENE_W, y)], fill=lerp("#6EC1EE", "#CFEAFB", min(y // 6, 9) / 9))
    for cx, cy, w in ((14, 10, 12), (62, 7, 16), (86, 20, 10), (34, 24, 9)):   # clouds
        d.rounded_rectangle([cx - w, cy - 3, cx + w, cy + 3], 3, fill="#FFFFFF")
        d.rounded_rectangle([cx - w // 2, cy - 5, cx + w // 2, cy], 2, fill="#FFFFFF")
    d.polygon([(0, 56), (22, 30), (38, 40), (56, 18), (78, 38), (100, 28), (100, 58), (0, 58)], fill="#A9BDEB")
    d.polygon([(40, 58), (56, 18), (70, 40), (78, 58)], fill="#C9D6F4")
    d.polygon([(50, 30), (56, 18), (62, 30), (56, 27)], fill="#FFFFFF")
    d.polygon([(54, 22), (56, 6), (58, 22)], fill="#F4B6D2")
    d.polygon([(60, 24), (62, 10), (64, 24)], fill="#F4B6D2")
    d.ellipse([-10, 44, 40, 70], fill="#6DB36B")
    d.ellipse([70, 36, 112, 70], fill="#4E9A5B")
    d.ellipse([80, 40, 100, 62], fill="#5FAF66")
    d.rectangle([0, 52, SCENE_W, SCENE_H], fill="#BBD958")
    d.rectangle([0, 60, SCENE_W, SCENE_H], fill="#A9CB4B")
    d.rectangle([14, 40, 36, 54], fill="#9A6B45")              # house
    d.polygon([(11, 41), (25, 30), (39, 41)], fill="#C95A3B")
    d.rectangle([17, 44, 21, 48], fill="#F2C94C")
    d.rectangle([28, 44, 32, 48], fill="#F2C94C")
    d.rectangle([23, 47, 26, 54], fill="#5B3A29")
    for x, y, c in ((6, 64, "#F06FA8"), (20, 67, "#FFE066"), (46, 66, "#F06FA8"),
                    (70, 68, "#FFE066"), (90, 65, "#F06FA8"), (34, 69, "#FFFFFF")):   # flowers
        d.rectangle([x, y, x + 1, y + 1], fill=c)
    return im


def draw_sprite(cv, rows, x, y, px, colors, tag, blink=False, tail=False):
    cv.delete(tag)
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            col = colors.get(ch)
            if blink and ch == "K":
                col = colors["o"]
            if col:
                cv.create_rectangle(x + c * px, y + r * px, x + (c + 1) * px, y + (r + 1) * px,
                                    fill=col, outline="", tags=tag)
    tx, ty = x + 9 * px, y + 6 * px
    for dx, dy in ((0, 0), (1, -1 if tail else 1)):
        cv.create_rectangle(tx + dx * px, ty + dy * px, tx + (dx + 1) * px, ty + (dy + 1) * px,
                            fill=colors["o"], outline="", tags=tag)


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def clickable(cv, tag, command):
    cv.tag_bind(tag, "<Button-1>", lambda e: command())
    cv.tag_bind(tag, "<Enter>", lambda e: cv.config(cursor="hand2"))
    cv.tag_bind(tag, "<Leave>", lambda e: cv.config(cursor=""))


class Screen:
    """Builds and updates the window. App (app.py) adds the behaviour."""

    def _build(self):
        self.configure(fg_color=BODY)
        holder = ctk.CTkFrame(self, fg_color="transparent", width=400, height=SCENE_H * PX, corner_radius=0)
        holder.pack()
        holder.pack_propagate(False)
        self.scene = tk.Canvas(holder, width=400, height=SCENE_H * PX, highlightthickness=0, bg=BODY)
        self.scene.place(x=0, y=0)
        self.scene_image = to_photo(make_scene()).zoom(PX)
        self.scene.create_image(0, 0, anchor="nw", image=self.scene_image)
        ctk.CTkButton(holder, text="\u2699", width=38, height=38, corner_radius=8, font=mono(16, True),
                      fg_color="#F4EFD8", hover_color="#E3DCB8", text_color=INK, border_width=2,
                      border_color="#CFC8A6", command=self.settings_menu).place(x=348, y=10)

        # green screen
        self.lcd = lcd = tk.Canvas(self, width=364, height=140, bg=BODY, highlightthickness=0)
        lcd.pack(pady=(14, 0))
        round_rect(lcd, 3, 3, 361, 137, 24, fill=LCD, outline=LCD_EDGE, width=3)
        lcd.create_text(20, 52, text="", tags="name", anchor="w", fill=INK, font=mono(14, True))
        lcd.create_text(20, 96, text="READY", tags="status", anchor="w", fill=INK, font=mono(10), width=164)
        lcd.create_line(188, 22, 188, 118, fill=LCD_EDGE, width=2)
        for y, label, tag in ((34, "STEPS", "steps"), (70, "REPEAT", "rep"), (106, "SPEED", "spd")):
            lcd.create_text(204, y, text=label, anchor="w", fill=INK, font=mono(11))
            lcd.create_text(346, y, text="", anchor="e", tags=tag, fill=INK, font=mono(13, True))
        for tag, command in (("name", self.save), ("rep", self.cycle_repeat), ("spd", self.cycle_speed)):
            clickable(lcd, tag, command)

        # controls
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=18, pady=(8, 0))
        left = ctk.CTkFrame(controls, fg_color="transparent")
        left.pack(side="left", anchor="n")
        self.smart = ctk.CTkSwitch(left, text="Smart replay", font=mono(12, True), text_color=INK,
                                   progress_color=MAG, button_color="#F1E6EE", fg_color="#7A8A55")
        self.smart.select()
        self.smart.pack(anchor="w", pady=(14, 14))
        pills = ctk.CTkFrame(left, fg_color="transparent")
        pills.pack(anchor="w")
        self._pill(pills, "Macros", self.open_library)
        self.brain_label = self._pill(pills, "LOCAL", self.cycle_brain)
        self.pad = pad = tk.Canvas(controls, width=180, height=190, bg=BODY, highlightthickness=0)
        pad.pack(side="right")
        pad.create_line(50, 138, 126, 72, width=104, capstyle="round", fill=BODY_DK)
        self._round_button(pad, 50, 138, "rec", "REC", self.toggle_record)
        self._round_button(pad, 126, 72, "act", "RUN", self.toggle_play)

    def _pill(self, parent, label, command):
        frame = ctk.CTkFrame(parent, fg_color=BODY_DK, corner_radius=16)
        frame.pack(side="left", padx=(0, 8))
        ctk.CTkButton(frame, text="", width=62, height=20, corner_radius=10, fg_color=PILL,
                      hover_color="#55555A", command=command).pack(padx=8, pady=(9, 3))
        text = ctk.CTkLabel(frame, text=label, font=mono(10, True), text_color=INK)
        text.pack(pady=(0, 8))
        return text

    def _round_button(self, cv, cx, cy, tag, text, command):
        cv.create_oval(cx - 35, cy - 31, cx + 35, cy + 39, fill=MAG_DK, outline="", tags=tag)
        cv.create_oval(cx - 34, cy - 34, cx + 34, cy + 34, fill=MAG, outline=MAG_DK, width=2, tags=(tag, tag + "_f"))
        cv.create_oval(cx - 23, cy - 27, cx - 7, cy - 15, fill=MAG_HI, outline="", tags=tag)
        cv.create_text(cx, cy + 2, text=text, fill="#FFFFFF", font=mono(12, True), tags=(tag, tag + "_t"))
        clickable(cv, tag, command)

    def _tick(self):
        """Animates the cat in the scene."""
        self.anim += 1
        a, x, y = self.anim, 250, 200
        if self.recording:
            x = 70 + int(130 * (1 + math.sin(a / 6)))
        elif self.playing:
            x, y = 40 + (a * 4) % 300, 200 - int(abs(math.sin(a / 2)) * 16)
        draw_sprite(self.scene, CAT, x, y, 4, CAT_COLORS, "cat", blink=a % 26 < 2, tail=a % 6 < 3)
        self.after(120, self._tick)

    def set_status(self, text):
        text = text.strip()
        if text == "Recording":
            text += ". FN+F8 STOPS"
        elif text.startswith("Playing"):
            text += ". FN+F9 STOPS"
        self.lcd.itemconfigure("status", text=text.upper())

    def refresh_lcd(self):
        name = self.macro_name.upper()[:12]
        self.lcd.itemconfigure("name", text=f"{name} \u270e")
        self.lcd.itemconfigure("rep", text=f"x{self.repeat_n} \u25b8")
        self.lcd.itemconfigure("spd", text=f"{self.speed_v:g}x \u25b8")
        self.lcd.itemconfigure("steps", text=str(self.nsteps))

    def update_count(self):
        self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])
        self.lcd.itemconfigure("steps", text=str(self.nsteps))

    def refresh_buttons(self):
        p = self.pad
        p.itemconfigure("rec_f", fill=REC_RED if self.recording else (MAG_DIM if self.playing else MAG))
        p.itemconfigure("rec_t", text="STOP" if self.recording else "REC")
        p.itemconfigure("act_f", fill=RUN_GREEN if self.playing else (MAG_DIM if self.recording else MAG))
        p.itemconfigure("act_t", text="STOP" if self.playing else "RUN")

    def open_library(self):
        names = settings.macro_names()
        win = ctk.CTkToplevel(self)
        win.title("Macros")
        win.geometry("320x380")
        win.configure(fg_color=BODY)
        win.after(100, win.lift)
        ctk.CTkLabel(win, text="SAVED MACROS", font=mono(12, True), text_color=INK).pack(pady=(14, 8))
        box = ctk.CTkScrollableFrame(win, fg_color=LCD, corner_radius=14)
        box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        if not names:
            ctk.CTkLabel(box, text="Nothing saved yet.\nTap the name on the screen to save.",
                         font=mono(10), text_color=INK).pack(pady=20)
        for name in names:
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkButton(row, text=name.upper(), anchor="w", font=mono(11), fg_color=BODY_DK, hover_color=BODY,
                          text_color=INK, command=lambda n=name: (self.load_named(n), win.destroy())
                          ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="\u2715", width=32, font=mono(12, True), fg_color="transparent",
                          hover_color=BODY, text_color=INK,
                          command=lambda n=name: (self.delete_named(n), win.destroy())).pack(side="left", padx=(6, 0))
