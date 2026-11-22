"""AutoCompilateur - fenetre simple : glisse un ZIP, recupere le .jar."""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk

import core

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:  # sans glisser-deposer, le bouton "Choisir un ZIP" reste disponible
    HAS_DND = False

BG, FG, ACC, OK, KO = "#14161f", "#e8eaf2", "#37e6ff", "#4ade80", "#f87171"


class App:
    def __init__(self):
        self.root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
        self.root.title("AutoCompilateur - ZIP vers plugin/mod .jar")
        self.root.geometry("760x640")
        self.root.configure(bg=BG)
        self.q = queue.Queue()
        self.out_dir = None
        self.busy = False

        tk.Label(self.root, text="AutoCompilateur", font=("Segoe UI", 20, "bold"), bg=BG, fg=ACC).pack(pady=(14, 0))
        tk.Label(self.root, text="Plugins Paper/Spigot et mods Fabric/Forge/NeoForge (projets Gradle ou Maven)",
                 bg=BG, fg=FG).pack()

        self.drop = tk.Label(self.root, text=("Glisse ton fichier .zip ici" if HAS_DND else "Clique sur \"Choisir un ZIP\"") +
                             "\n(le ZIP du projet avec son code source)",
                             font=("Segoe UI", 13), bg="#1d2030", fg=FG, relief="groove", bd=2, height=5)
        self.drop.pack(fill="x", padx=24, pady=14)
        if HAS_DND:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self.on_drop)

        row = tk.Frame(self.root, bg=BG)
        row.pack()
        self.btn = tk.Button(row, text="Choisir un ZIP...", command=self.choose, bg=ACC, fg="#001018",
                             font=("Segoe UI", 10, "bold"), relief="flat", padx=14, pady=6)
        self.btn.pack(side="left", padx=6)
        tk.Label(row, text="Java :", bg=BG, fg=FG).pack(side="left", padx=(16, 4))
        self.java = ttk.Combobox(row, width=8, state="readonly", values=["Auto", "8", "11", "17", "21", "25"])
        self.java.set("Auto")
        self.java.pack(side="left")

        self.status = tk.Label(self.root, text="En attente d'un ZIP.", bg=BG, fg=FG, font=("Segoe UI", 11, "bold"), wraplength=700)
        self.status.pack(pady=(12, 2))
        self.bar = ttk.Progressbar(self.root, mode="indeterminate", length=700)
        self.bar.pack()

        self.log = scrolledtext.ScrolledText(self.root, height=16, bg="#0b0d14", fg="#c9d1e5", font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, padx=24, pady=10)

        row2 = tk.Frame(self.root, bg=BG)
        row2.pack(pady=(0, 6))
        self.open_btn = tk.Button(row2, text="Ouvrir le dossier du .jar", command=self.open_out, state="disabled")
        self.open_btn.pack(side="left", padx=6)
        tk.Button(row2, text="Copier le journal", command=self.copy_log).pack(side="left", padx=6)
        tk.Label(self.root, text="Securite : ne compile que des ZIP de confiance. Les scripts de build peuvent executer du code.\n"
                 "Premier lancement : telechargement de Java/Gradle (quelques centaines de Mo, internet requis).",
                 bg=BG, fg="#8b93ad", font=("Segoe UI", 8)).pack(pady=(0, 8))
        self.root.after(100, self.pump)

    # ---- actions
    def choose(self):
        p = filedialog.askopenfilename(title="Choisis le ZIP du projet", filetypes=[("Fichiers ZIP", "*.zip")])
        if p:
            self.start(p)

    def on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self.start(paths[0])

    def start(self, path):
        if self.busy:
            return
        if not path.lower().endswith(".zip"):
            self.set_status("Ce n'est pas un fichier .zip.", KO)
            return
        self.busy = True
        self.btn.config(state="disabled")
        self.open_btn.config(state="disabled")
        self.clear_log()
        self.set_status("Compilation en cours : " + os.path.basename(path), FG)
        self.bar.start(12)
        choice = self.java.get()
        threading.Thread(target=self.work, args=(path, choice), daemon=True).start()

    def work(self, path, choice):
        try:
            out, jars = core.compile_zip(path, choice, lambda m: self.q.put(("log", m)))
            self.q.put(("done", (out, jars)))
        except core.BuildError as e:
            self.q.put(("fail", str(e)))
        except Exception as e:  # erreur imprevue
            self.q.put(("fail", "Erreur inattendue : %r" % e))

    def pump(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.append(data)
                elif kind == "done":
                    self.finish(True, "Termine ! %d fichier(s) .jar crees." % len(data[1]), data[0])
                else:
                    self.finish(False, data, None)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def finish(self, ok, msg, out):
        self.bar.stop()
        self.busy = False
        self.btn.config(state="normal")
        self.set_status(msg, OK if ok else KO)
        if ok and out:
            self.out_dir = out
            self.open_btn.config(state="normal")
            self.open_out()

    def open_out(self):
        if self.out_dir:
            try:
                os.startfile(self.out_dir)  # Windows
            except Exception:
                pass

    def set_status(self, text, color):
        self.status.config(text=text, fg=color)

    def append(self, line):
        self.log.config(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.get("1.0", "end"))
        self.set_status("Journal copie dans le presse-papiers.", FG)


if __name__ == "__main__":
    App().root.mainloop()
