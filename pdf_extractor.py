"""GUI nástroj: extrahuje každú stranu (slide) PDF do samostatného PNG obrázka."""
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pymupdf


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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Slide Extractor")
        self.geometry("640x300")
        self.resizable(False, False)

        self.pdf_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.dpi_var = tk.IntVar(value=150)
        self.status_var = tk.StringVar(value="Vyber PDF súbor.")
        self.q: queue.Queue = queue.Queue()

        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="PDF súbor:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.pdf_var).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Vybrať…", command=self.pick_pdf).grid(row=0, column=2, **pad)

        ttk.Label(frm, text="Cieľový priečinok:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.out_var).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Vybrať…", command=self.pick_out).grid(row=1, column=2, **pad)

        ttk.Label(frm, text="Kvalita (DPI):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Spinbox(frm, from_=50, to=600, increment=25, textvariable=self.dpi_var,
                    width=8).grid(row=2, column=1, sticky="w", **pad)

        self.btn = ttk.Button(frm, text="Extrahovať slidy", command=self.start)
        self.btn.grid(row=3, column=0, columnspan=3, pady=12)

        self.bar = ttk.Progressbar(frm, mode="determinate")
        self.bar.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(frm, textvariable=self.status_var).grid(row=5, column=0, columnspan=3, sticky="w", **pad)

    def pick_pdf(self):
        p = choose_pdf(str(Path(self.pdf_var.get()).parent) if self.pdf_var.get() else "")
        if p:
            self.pdf_var.set(p)
            if not self.out_var.get():
                self.out_var.set(str(Path(p).parent))

    def pick_out(self):
        p = choose_dir(self.out_var.get())
        if p:
            self.out_var.set(p)

    def start(self):
        pdf, out = Path(self.pdf_var.get()), self.out_var.get()
        if not pdf.is_file():
            messagebox.showerror("Chyba", "Vyber platný PDF súbor.")
            return
        if not out:
            messagebox.showerror("Chyba", "Vyber cieľový priečinok.")
            return
        # nový priečinok pomenovaný podľa PDF, pri kolízii s číslom
        base = Path(out) / f"{pdf.stem}_extracted"
        target, i = base, 1
        while target.exists():
            i += 1
            target = Path(f"{base}_{i}")
        target.mkdir(parents=True)

        self.btn.config(state="disabled")
        self.bar["value"] = 0
        threading.Thread(target=self.work, args=(pdf, target, self.dpi_var.get()),
                         daemon=True).start()
        self.after(100, self.poll)

    def work(self, pdf: Path, target: Path, dpi: int):
        try:
            with pymupdf.open(pdf) as doc:
                n = len(doc)
                width = len(str(n))
                for i, page in enumerate(doc, 1):
                    page.get_pixmap(dpi=dpi).save(target / f"slide_{i:0{width}d}.png")
                    self.q.put(("progress", i, n))
            self.q.put(("done", n, target))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", str(e)))

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    _, i, n = msg
                    self.bar["maximum"], self.bar["value"] = n, i
                    self.status_var.set(f"Slide {i}/{n}")
                elif msg[0] == "done":
                    self.btn.config(state="normal")
                    self.status_var.set(f"Hotovo: {msg[1]} slidov → {msg[2]}")
                    messagebox.showinfo("Hotovo", f"Uložených {msg[1]} slidov do:\n{msg[2]}")
                    return
                else:
                    self.btn.config(state="normal")
                    self.status_var.set("Chyba")
                    messagebox.showerror("Chyba", msg[1])
                    return
        except queue.Empty:
            pass
        self.after(100, self.poll)


if __name__ == "__main__":
    App().mainloop()
