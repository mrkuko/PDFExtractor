"""GUI nástroj: extrahuje každú stranu (slide) PDF do samostatného PNG obrázka."""
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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

        try:
            with pymupdf.open(pdf) as doc:
                self.n = len(doc)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Chyba", str(e))
            return
        self.target = target
        width = len(str(self.n))
        dpi = self.dpi_var.get()
        self.btn.config(state="disabled")
        self.bar.config(maximum=self.n, value=0)
        self.status_var.set(f"Slide 0/{self.n}")
        # Samostatné procesy (nie vlákna): pymupdf drží GIL, takže vlákna by nezrýchlili nič.
        self.pool = ProcessPoolExecutor(max_workers=min(os.cpu_count() or 2, self.n),
                                        mp_context=mp.get_context("spawn"))
        self.futs = [self.pool.submit(_render, str(pdf), i, dpi,
                                      str(target / f"slide_{i + 1:0{width}d}.png"))
                     for i in range(self.n)]
        self.after(50, self.poll)

    def poll(self):
        done = sum(f.done() for f in self.futs)
        self.bar["value"] = done
        self.status_var.set(f"Slide {done}/{self.n}")
        if done < self.n:
            self.after(50, self.poll)
            return
        self.pool.shutdown()
        self.btn.config(state="normal")
        try:
            for f in self.futs:
                f.result()
        except Exception as e:  # noqa: BLE001
            self.status_var.set("Chyba")
            messagebox.showerror("Chyba", str(e))
            return
        self.status_var.set(f"Hotovo: {self.n} slidov → {self.target}")
        messagebox.showinfo("Hotovo", f"Uložených {self.n} slidov do:\n{self.target}")


if __name__ == "__main__":
    App().mainloop()
