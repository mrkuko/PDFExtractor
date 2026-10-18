"""GUI nástroj: extrahuje každú stranu (slide) PDF do samostatného PNG obrázka."""
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pymupdf
from concurrent.futures import ProcessPoolExecutor


def _linux_dialog(kind: str, start: str):
    """Natívny dialóg na Linuxe cez zenity (GTK) alebo kdialog (KDE).

    Vráti cestu, "" pri zrušení, alebo None ak nie je dostupný žiadny nástroj.
    """
    start = start or str(Path.home())
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", f"--filename={start.rstrip('/')}/"]
        if kind == "file":
            cmd += ["--file-filter=PDF | *.pdf *.PDF", "--file-filter=Všetky | *"]
        else:
            cmd.append("--directory")
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--getopenfilename" if kind == "file" else "--getexistingdirectory",
               start] + (["*.pdf|PDF"] if kind == "file" else [])
    else:
        return None
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def choose_pdf(start: str = "") -> str:
    # Windows a macOS: tkinter používa natívne dialógy OS
    if sys.platform.startswith("linux"):
        p = _linux_dialog("file", start)
        if p is not None:
            return p
    return filedialog.askopenfilename(initialdir=start or None, filetypes=[("PDF", "*.pdf")])


def choose_dir(start: str = "") -> str:
    if sys.platform.startswith("linux"):
        p = _linux_dialog("dir", start)
        if p is not None:
            return p
    return filedialog.askdirectory(initialdir=start or None)


_doc = None


def _render(pdf: str, idx: int, dpi: int, out: str):
    """Beží v procese poolu; každý proces si otvorí PDF raz a renderuje svoje strany."""
    global _doc
    if _doc is None:
        _doc = pymupdf.open(pdf)
    _doc[idx].get_pixmap(dpi=dpi, alpha=False).save(out)
    return idx


ACCENT, ACCENT_HOVER = "#6C5CE7", "#7F70F0"
# Farby ako (svetlý, tmavý) pár – customtkinter si vyberie podľa režimu.
BG = ("#F2F2F7", "#14141C")
CARD = ("#FFFFFF", "#1E1E2A")
FIELD = ("#F2F2F7", "#14141C")
BORDER = ("#D0D0DC", "#34344A")
MUTED = ("#6B6B80", "#8A8AA0")
LABEL = ("#4A4A5E", "#B5B5C8")
BTN2, BTN2_HOVER = ("#E6E6F0", "#2A2A3A"), ("#D8D8E6", "#383850")
BTN2_TEXT = ("#1E1E2A", "#EDEDF5")
TRACK = ("#DADAE6", "#2A2A3A")
GREEN, RED = ("#16A34A", "#4ADE80"), ("#DC2626", "#FF6B6B")

CONFIG = Path.home() / ".config" / "pdf_slide_extractor.json"

TEXTS = {
    "en": {
        "subtitle": "Saves every page of a PDF presentation as a PNG image.",
        "pdf": "PDF file", "pick_pdf": "Choose PDF",
        "out": "Destination folder", "pick_out": "Choose folder",
        "dpi": "Quality (DPI)", "run": "Extract slides",
        "idle": "Choose a PDF file.", "progress": "Slide {done}/{n}",
        "done": "Done: {n} slides → {target}", "error": "Error: {e}",
        "open": "Open folder", "err_title": "Error",
        "bad_pdf": "Choose a valid PDF file.", "bad_out": "Choose a destination folder.",
        "language": "Language", "theme": "Theme", "dark": "Dark", "light": "Light",
    },
    "sk": {
        "subtitle": "Každú stranu PDF prezentácie uloží ako PNG obrázok.",
        "pdf": "PDF súbor", "pick_pdf": "Vybrať PDF",
        "out": "Cieľový priečinok", "pick_out": "Vybrať priečinok",
        "dpi": "Kvalita (DPI)", "run": "Extrahovať slidy",
        "idle": "Vyber PDF súbor.", "progress": "Slide {done}/{n}",
        "done": "Hotovo: {n} slidov → {target}", "error": "Chyba: {e}",
        "open": "Otvoriť priečinok", "err_title": "Chyba",
        "bad_pdf": "Vyber platný PDF súbor.", "bad_out": "Vyber cieľový priečinok.",
        "language": "Jazyk", "theme": "Vzhľad", "dark": "Tmavý", "light": "Svetlý",
    },
}
LANGS = {"English": "en", "Slovenčina": "sk"}


def load_settings() -> dict:
    try:
        d = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        d = {}
    return {"lang": d.get("lang", "en") if d.get("lang") in TEXTS else "en",
            "theme": d.get("theme", "dark") if d.get("theme") in ("dark", "light") else "dark"}


def save_settings(d: dict):
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(d))
    except OSError:
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        ctk.set_appearance_mode(self.settings["theme"])
        self.title("PDF Slide Extractor")
        self.geometry("680x480")
        self.minsize(560, 440)
        self.configure(fg_color=BG)

        self.pdf_var = ctk.StringVar()
        self.out_var = ctk.StringVar()
        self.dpi_var = ctk.IntVar(value=150)
        self.target = None
        self.tr_widgets = []              # (widget, kľúč textu)
        self.status_state = ("idle", {}, MUTED)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(22, 0))
        ctk.CTkLabel(header, text="PDF Slide Extractor",
                     font=ctk.CTkFont(size=26, weight="bold")).pack(side="left")
        self.gear = ctk.CTkButton(header, text="⚙", width=40, height=40, corner_radius=20,
                                  font=ctk.CTkFont(size=20), fg_color=BTN2, hover_color=BTN2_HOVER,
                                  text_color=BTN2_TEXT, command=self.toggle_settings)
        self.gear.pack(side="right")
        self.subtitle = self._label(self, "subtitle", text_color=MUTED)
        self.subtitle.pack(anchor="w", padx=28, pady=(0, 14))

        card = ctk.CTkFrame(self, corner_radius=16, fg_color=CARD)
        card.pack(fill="x", padx=24)
        card.columnconfigure(0, weight=1)

        self._row(card, 0, "pdf", self.pdf_var, self.pick_pdf, "pick_pdf")
        self._row(card, 2, "out", self.out_var, self.pick_out, "pick_out")

        self._label(card, "dpi", text_color=LABEL).grid(
            row=4, column=0, sticky="w", padx=18, pady=(4, 0))
        self.dpi_label = ctk.CTkLabel(card, text="150", font=ctk.CTkFont(weight="bold"))
        self.dpi_label.grid(row=4, column=1, sticky="e", padx=18, pady=(4, 0))
        ctk.CTkSlider(card, from_=50, to=400, number_of_steps=14, variable=self.dpi_var,
                      progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
                      command=lambda v: self.dpi_label.configure(text=str(int(v)))
                      ).grid(row=5, column=0, columnspan=2, sticky="ew", padx=18, pady=(4, 18))

        self.btn = ctk.CTkButton(self, height=46, corner_radius=12,
                                 font=ctk.CTkFont(size=15, weight="bold"),
                                 fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white",
                                 command=self.start)
        self.tr_widgets.append((self.btn, "run"))
        self.btn.pack(fill="x", padx=24, pady=(18, 10))

        self.bar = ctk.CTkProgressBar(self, height=10, progress_color=ACCENT, fg_color=TRACK)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=24)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=24, pady=10)
        self.status = ctk.CTkLabel(bottom, text="", anchor="w", justify="left")
        self.status.pack(side="left", fill="x", expand=True)
        self.open_btn = ctk.CTkButton(bottom, width=140, fg_color=BTN2, hover_color=BTN2_HOVER,
                                      text_color=BTN2_TEXT, command=self.open_folder)
        self.tr_widgets.append((self.open_btn, "open"))

        self._build_settings_popup()
        self.bind("<Button-1>", self._click_away, add="+")
        self.apply_language()

    # ---------- preklady ----------
    def t(self, key: str, **kw) -> str:
        return TEXTS[self.settings["lang"]][key].format(**kw)

    def _label(self, parent, key, **kw):
        w = ctk.CTkLabel(parent, **kw)
        self.tr_widgets.append((w, key))
        return w

    def set_status(self, key, color, **kw):
        self.status_state = (key, kw, color)
        self.status.configure(text=self.t(key, **kw), text_color=color)

    def apply_language(self):
        for w, key in self.tr_widgets:
            w.configure(text=self.t(key))
        key, kw, color = self.status_state
        self.set_status(key, color, **kw)
        self.lang_lbl.configure(text=self.t("language"))
        self.theme_lbl.configure(text=self.t("theme"))
        names = [self.t("dark"), self.t("light")]
        self.theme_seg.configure(values=names)
        self.theme_seg.set(names[0 if self.settings["theme"] == "dark" else 1])

    # ---------- nastavenia (ozubené koliesko) ----------
    def _build_settings_popup(self):
        self.popup = ctk.CTkFrame(self, corner_radius=14, fg_color=CARD, border_width=1,
                                  border_color=BORDER)
        self.lang_lbl = ctk.CTkLabel(self.popup, text_color=LABEL)
        self.lang_lbl.pack(anchor="w", padx=16, pady=(14, 2))
        self.lang_seg = ctk.CTkSegmentedButton(
            self.popup, values=list(LANGS), command=self.on_lang,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        self.lang_seg.set(next(k for k, v in LANGS.items() if v == self.settings["lang"]))
        self.lang_seg.pack(padx=16, fill="x")
        self.theme_lbl = ctk.CTkLabel(self.popup, text_color=LABEL)
        self.theme_lbl.pack(anchor="w", padx=16, pady=(12, 2))
        self.theme_seg = ctk.CTkSegmentedButton(
            self.popup, values=["Dark", "Light"], command=self.on_theme,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        self.theme_seg.pack(padx=16, pady=(0, 16), fill="x")
        self.popup_open = False

    def toggle_settings(self):
        if self.popup_open:
            self.popup.place_forget()
        else:
            self.popup.place(relx=1.0, x=-24, y=70, anchor="ne")
            self.popup.lift()
        self.popup_open = not self.popup_open

    def _click_away(self, event):
        if not self.popup_open:
            return
        w = event.widget
        while w is not None:
            if w is self.popup or w is self.gear or w is getattr(self.gear, "_canvas", None):
                return
            w = getattr(w, "master", None)
        self.toggle_settings()

    def on_lang(self, value):
        self.settings["lang"] = LANGS[value]
        save_settings(self.settings)
        self.apply_language()

    def on_theme(self, value):
        self.settings["theme"] = "dark" if value == self.t("dark") else "light"
        save_settings(self.settings)
        ctk.set_appearance_mode(self.settings["theme"])

    # ---------- UI pomocníci ----------
    def _row(self, parent, row, label_key, var, cmd, btn_key):
        self._label(parent, label_key, text_color=LABEL).grid(
            row=row, column=0, sticky="w", padx=18, pady=(14, 0))
        ctk.CTkEntry(parent, textvariable=var, height=38, corner_radius=10,
                     fg_color=FIELD, border_color=BORDER
                     ).grid(row=row + 1, column=0, sticky="ew", padx=(18, 8), pady=(4, 4))
        b = ctk.CTkButton(parent, width=140, height=38, corner_radius=10, fg_color=BTN2,
                          hover_color=BTN2_HOVER, text_color=BTN2_TEXT, command=cmd)
        self.tr_widgets.append((b, btn_key))
        b.grid(row=row + 1, column=1, padx=(0, 18), pady=(4, 4))

    def pick_pdf(self):
        cur = self.pdf_var.get()
        p = choose_pdf(str(Path(cur).parent) if cur else "")
        if p:
            self.pdf_var.set(p)
            if not self.out_var.get():
                self.out_var.set(str(Path(p).parent))

    def pick_out(self):
        p = choose_dir(self.out_var.get())
        if p:
            self.out_var.set(p)

    def open_folder(self):
        if not self.target:
            return
        if sys.platform.startswith("win"):
            os.startfile(self.target)  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(self.target)])

    # ---------- extrakcia ----------
    def start(self):
        pdf, out = Path(self.pdf_var.get()), self.out_var.get()
        if not pdf.is_file():
            messagebox.showerror(self.t("err_title"), self.t("bad_pdf"))
            return
        if not out:
            messagebox.showerror(self.t("err_title"), self.t("bad_out"))
            return
        try:
            with pymupdf.open(pdf) as doc:
                self.n = len(doc)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(self.t("err_title"), str(e))
            return
        # nový priečinok pomenovaný podľa PDF, pri kolízii s číslom
        base = Path(out) / f"{pdf.stem}_extracted"
        target, i = base, 1
        while target.exists():
            i += 1
            target = Path(f"{base}_{i}")
        target.mkdir(parents=True)
        self.target = target

        width = len(str(self.n))
        dpi = int(self.dpi_var.get())
        self.btn.configure(state="disabled")
        self.open_btn.pack_forget()
        self.bar.set(0)
        self.set_status("progress", LABEL, done=0, n=self.n)
        # Samostatné procesy (nie vlákna): pymupdf drží GIL, takže vlákna by nezrýchlili nič.
        self.pool = ProcessPoolExecutor(max_workers=min(os.cpu_count() or 2, self.n),
                                        mp_context=mp.get_context("spawn"))
        self.futs = [self.pool.submit(_render, str(pdf), i, dpi,
                                      str(target / f"slide_{i + 1:0{width}d}.png"))
                     for i in range(self.n)]
        self.after(50, self.poll)

    def poll(self):
        done = sum(f.done() for f in self.futs)
        self.bar.set(done / self.n)
        self.set_status("progress", LABEL, done=done, n=self.n)
        if done < self.n:
            self.after(50, self.poll)
            return
        self.pool.shutdown()
        self.btn.configure(state="normal")
        try:
            for f in self.futs:
                f.result()
        except Exception as e:  # noqa: BLE001
            self.set_status("error", RED, e=e)
            return
        self.set_status("done", GREEN, n=self.n, target=self.target)
        self.open_btn.pack(side="right")


if __name__ == "__main__":
    App().mainloop()
