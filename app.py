# -*- coding: utf-8 -*-
"""Gallery Cleaner — Tkinter UI.

All heavy computation runs in a background thread; results reach the UI
through a Queue so the interface never freezes, however large the folder.

Design system (light, high-contrast desktop tool):
  semantic color tokens below — no raw hex sprinkled through the widgets.
"""

import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import classifier
import config
import file_ops

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
C = {
    "bg":          "#F8FAFC",  # app background
    "surface":     "#FFFFFF",  # cards / panels
    "surface_hi":  "#EEF2F7",  # hovered surface
    "border":      "#E2E8F0",
    "fg":          "#0F172A",  # primary text
    "fg_muted":    "#64748B",  # secondary text
    "primary":     "#7C3AED",  # violet — primary actions
    "primary_hi":  "#8B5CF6",
    "accent":      "#0891B2",  # cyan — selection
    "accent_hi":   "#0E7490",
    "danger":      "#DC2626",  # destructive actions
    "danger_hi":   "#EF4444",
    "success":     "#16A34A",
    "warning":     "#D97706",
}

THUMB_SIZE = 140
GRID_COLS = 5
PAGE_SIZE = 60  # paginate instead of loading thousands of thumbnails at once

FONT_BODY = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 8)
FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_HEADING = ("Segoe UI", 11, "bold")


def _conf_color(conf: float) -> str:
    """Red→green gradient for the confidence bar."""
    r = int(220 * (1 - conf) + 22 * conf)
    g = int(38 * (1 - conf) + 163 * conf)
    b = int(38 * (1 - conf) + 74 * conf)
    return f"#{r:02x}{g:02x}{b:02x}"


class FlatButton(tk.Button):
    """Styled button with hover/pressed/disabled states and a color role."""

    ROLES = {
        "primary":   (C["primary"], C["primary_hi"], "#FFFFFF"),
        "secondary": (C["surface_hi"], C["border"], C["fg"]),
        "danger":    (C["danger"], C["danger_hi"], "#FFFFFF"),
        "ghost":     (C["surface"], C["surface_hi"], C["fg_muted"]),
    }

    def __init__(self, master, role="secondary", **kw):
        base, hover, fg = self.ROLES[role]
        super().__init__(
            master, bd=0, relief="flat", cursor="hand2",
            bg=base, fg=fg, activebackground=hover, activeforeground=fg,
            disabledforeground=C["fg_muted"], font=FONT_BODY,
            padx=14, pady=6, highlightthickness=0, **kw)
        self._base, self._hover = base, hover
        self.bind("<Enter>", lambda e: self._set_bg(self._hover))
        self.bind("<Leave>", lambda e: self._set_bg(self._base))

    def _set_bg(self, color):
        if self["state"] != "disabled":
            self.config(bg=color)

    def set_enabled(self, enabled: bool):
        if enabled:
            self.config(state="normal", bg=self._base)
        else:
            self.config(state="disabled", bg=C["surface"])


class GalleryCleanerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("GalleryCleaner — Smart Gallery Cleaner")
        root.geometry("1220x800")
        root.configure(bg=C["bg"])
        root.minsize(980, 640)

        self.folder = None
        self.results = []            # ImageResult
        self.dup_groups = []
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.scanning = False
        self.selected = set()        # paths selected for removal
        self.thumb_cache = {}
        self.page = 0
        self.active_category = None
        self._cats = []
        self._cells = {}             # path -> thumbnail cell frame

        self._build_ui()
        self._bind_keys()
        self._update_action_bar()
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # ---- header ----------------------------------------------------
        header = tk.Frame(self.root, bg=C["surface"], padx=14, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="GalleryCleaner", font=FONT_TITLE,
                 bg=C["surface"], fg=C["fg"]).pack(side="left")
        self.folder_label = tk.Label(header, text="No folder selected",
                                     font=FONT_BODY, bg=C["surface"],
                                     fg=C["fg_muted"])
        self.folder_label.pack(side="left", padx=16)

        self.stop_btn = FlatButton(header, text="Stop", role="ghost",
                                   command=self.stop_scan)
        self.stop_btn.pack(side="right", padx=(6, 0))
        self.scan_btn = FlatButton(header, text="Start Scan", role="primary",
                                   command=self.start_scan)
        self.scan_btn.pack(side="right", padx=(6, 0))
        FlatButton(header, text="Choose Folder…", role="secondary",
                   command=self.choose_folder).pack(side="right")
        self.scan_btn.set_enabled(False)
        self.stop_btn.set_enabled(False)

        # ---- progress + live status ------------------------------------
        prog = tk.Frame(self.root, bg=C["bg"], padx=14, pady=6)
        prog.pack(fill="x")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("GC.Horizontal.TProgressbar",
                        troughcolor=C["border"], bordercolor=C["border"],
                        background=C["primary"], lightcolor=C["primary"],
                        darkcolor=C["primary"], thickness=6)
        self.progress = ttk.Progressbar(prog, mode="determinate",
                                        style="GC.Horizontal.TProgressbar")
        self.progress.pack(fill="x")
        self.status_label = tk.Label(prog, text="Choose a folder to begin.",
                                     font=FONT_BODY, bg=C["bg"],
                                     fg=C["fg_muted"], anchor="w")
        self.status_label.pack(fill="x", pady=(4, 0))

        # ---- body: sidebar + grid ---------------------------------------
        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True)

        side = tk.Frame(body, bg=C["surface"], width=280, padx=12, pady=10)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(body, bg=C["border"], width=1).pack(side="left", fill="y")
        tk.Label(side, text="CATEGORIES", font=FONT_HEADING,
                 bg=C["surface"], fg=C["fg_muted"]).pack(anchor="w", pady=(0, 6))
        self.cat_list = tk.Listbox(
            side, bd=0, highlightthickness=0, activestyle="none",
            bg=C["surface"], fg=C["fg"], font=FONT_BODY,
            selectbackground=C["primary"], selectforeground="#FFFFFF")
        self.cat_list.pack(fill="both", expand=True)
        self.cat_list.bind("<<ListboxSelect>>", self._on_category_select)

        maint = tk.Frame(side, bg=C["surface"])
        maint.pack(fill="x", pady=(10, 0))
        tk.Label(maint, text="TRASH & REPORT", font=FONT_HEADING,
                 bg=C["surface"], fg=C["fg_muted"]).pack(anchor="w", pady=(0, 4))
        for text, cmd in (("Restore trash", self.restore_trash),
                          ("Empty trash…", self.empty_trash),
                          ("Export CSV…", self.export_csv)):
            FlatButton(maint, text=text, role="ghost", anchor="w",
                       command=cmd).pack(fill="x", pady=1)

        # ---- thumbnail grid ---------------------------------------------
        grid_frame = tk.Frame(body, bg=C["bg"])
        grid_frame.pack(side="right", fill="both", expand=True)
        self.canvas = tk.Canvas(grid_frame, bg=C["bg"], bd=0,
                                highlightthickness=0)
        vsb = ttk.Scrollbar(grid_frame, orient="vertical",
                            command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.inner = tk.Frame(self.canvas, bg=C["bg"])
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

        # pagination strip
        nav = tk.Frame(self.root, bg=C["bg"], pady=2)
        nav.pack(fill="x")
        FlatButton(nav, text="◀ Previous", role="ghost",
                   command=lambda: self._change_page(-1)).pack(side="left", padx=14)
        FlatButton(nav, text="Next ▶", role="ghost",
                   command=lambda: self._change_page(1)).pack(side="right", padx=14)
        self.page_label = tk.Label(nav, text="", font=FONT_BODY,
                                   bg=C["bg"], fg=C["fg_muted"])
        self.page_label.pack()

        # ---- ALWAYS-VISIBLE ACTION BAR ----------------------------------
        bar = tk.Frame(self.root, bg=C["surface"], padx=14, pady=10)
        bar.pack(fill="x", side="bottom")
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x",
                                                           side="bottom")
        self.sel_label = tk.Label(bar, text="", font=FONT_HEADING,
                                  bg=C["surface"], fg=C["fg"])
        self.sel_label.pack(side="left")

        self.remove_all_btn = FlatButton(bar, text="Remove ALL in category",
                                         role="danger",
                                         command=self.remove_all_in_category)
        self.remove_all_btn.pack(side="right", padx=(6, 0))
        self.remove_sel_btn = FlatButton(bar, text="Remove Selected",
                                         role="danger",
                                         command=self.remove_selected)
        self.remove_sel_btn.pack(side="right", padx=(6, 0))
        self.clear_sel_btn = FlatButton(bar, text="Clear selection",
                                        role="ghost",
                                        command=self.clear_selection)
        self.clear_sel_btn.pack(side="right", padx=(6, 0))
        self.select_all_btn = FlatButton(bar, text="Select all",
                                         role="secondary",
                                         command=self.select_all_in_category)
        self.select_all_btn.pack(side="right", padx=(6, 0))
        self.select_low_btn = FlatButton(bar, text="Select < 70% confidence",
                                         role="secondary",
                                         command=self.select_low_confidence)
        self.select_low_btn.pack(side="right", padx=(6, 0))

    def _bind_keys(self):
        self.root.bind("<Control-a>", lambda e: self.select_all_in_category())
        self.root.bind("<Escape>", lambda e: self.clear_selection())
        self.root.bind("<Delete>", lambda e: self.remove_selected())
        self.root.bind("<Prior>", lambda e: self._change_page(-1))
        self.root.bind("<Next>", lambda e: self._change_page(1))

    def _on_mousewheel(self, event):
        if event.num == 4 or getattr(event, "delta", 0) > 0:
            self.canvas.yview_scroll(-2, "units")
        else:
            self.canvas.yview_scroll(2, "units")

    # ------------------------------------------------------------ actions
    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder = folder
            self.folder_label.config(text=folder, fg=C["fg"])
            self.scan_btn.set_enabled(True)
            self.status_label.config(text="Ready — press Start Scan.")

    def start_scan(self):
        if self.scanning or not self.folder:
            return
        self.results.clear()
        self.dup_groups.clear()
        self.selected.clear()
        self.thumb_cache.clear()
        self.stop_event.clear()
        self.scanning = True
        self.scan_btn.set_enabled(False)
        self.stop_btn.set_enabled(True)
        self.status_label.config(text="Counting images…")
        self._update_action_bar()
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def stop_scan(self):
        self.stop_event.set()

    def _scan_worker(self):
        paths = list(classifier.iter_image_paths(self.folder))
        total = len(paths)
        self.queue.put(("total", total))
        start = time.time()
        done = 0
        collected = []
        for result in classifier.classify_folder(self.folder, self.stop_event):
            done += 1
            eta = (time.time() - start) / done * (total - done) if done else 0
            collected.append(result)
            self.queue.put(("result", result, done, total, eta))
        groups = classifier.find_similar_groups(collected)
        self.queue.put(("done", groups))

    def _poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "total":
                    self.progress.config(maximum=max(msg[1], 1), value=0)
                elif kind == "result":
                    _, result, done, total, eta = msg
                    self.results.append(result)
                    self.progress.config(value=done)
                    counts = self._category_counts()
                    live = "   ".join(f"{c.replace('_', ' ')}: {n}"
                                      for c, n in list(counts.items())[:4])
                    self.status_label.config(
                        text=f"Scanning {done}/{total}  ·  ETA ≈ {int(eta)}s  ·  {live}")
                elif kind == "done":
                    self.dup_groups = msg[1]
                    self.scanning = False
                    self.scan_btn.set_enabled(True)
                    self.stop_btn.set_enabled(False)
                    counts = self._category_counts()
                    summary = "  ·  ".join(f"{n} {c.replace('_', ' ')}"
                                           for c, n in counts.items())
                    self.status_label.config(
                        text=f"Scan complete — {summary}" if counts
                        else "Scan complete — no images found.")
                    self._refresh_category_list()
                    self._update_action_bar()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------- helpers
    def _category_counts(self):
        counts = {}
        for r in self.results:
            counts[r.category] = counts.get(r.category, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def _refresh_category_list(self):
        self.cat_list.delete(0, "end")
        for cat, n in self._category_counts().items():
            self.cat_list.insert("end", f"  {cat.replace('_', ' ')}  ({n})")
        if self.dup_groups:
            self.cat_list.insert("end",
                                 f"  duplicate groups  ({len(self.dup_groups)})")
        self._cats = list(self._category_counts().keys())

    def _on_category_select(self, _event):
        sel = self.cat_list.curselection()
        if not sel:
            return
        idx = sel[0]
        self.active_category = (self._cats[idx] if idx < len(self._cats)
                                else "__dups__")
        self.page = 0
        self._render_grid()
        self._update_action_bar()

    def _current_items(self):
        if self.active_category == "__dups__":
            items = []
            by_path = {r.path: r for r in self.results}
            for g in self.dup_groups:
                items.extend(by_path[p] for p in g["paths"] if p in by_path)
            return items
        return [r for r in self.results if r.category == self.active_category]

    def _change_page(self, delta):
        items = self._current_items()
        max_page = max((len(items) - 1) // PAGE_SIZE, 0)
        self.page = min(max(self.page + delta, 0), max_page)
        self._render_grid()

    def _render_grid(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self._cells.clear()
        items = self._current_items()
        max_page = max((len(items) - 1) // PAGE_SIZE, 0)
        self.page_label.config(
            text=f"Page {self.page + 1} of {max_page + 1}  ·  {len(items)} images")
        page_items = items[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]

        if not page_items:
            tk.Label(self.inner,
                     text="Nothing here yet.\nPick a category on the left "
                          "after a scan.",
                     font=FONT_BODY, bg=C["bg"], fg=C["fg_muted"],
                     justify="center").grid(row=0, column=0, padx=40, pady=40)

        for i, r in enumerate(page_items):
            selected = r.path in self.selected
            cell = tk.Frame(self.inner, bd=0,
                            bg=C["accent"] if selected else C["border"],
                            padx=3, pady=3)
            cell.grid(row=i // GRID_COLS, column=i % GRID_COLS,
                      padx=6, pady=6)
            self._cells[r.path] = cell
            body = tk.Frame(cell, bg=C["surface"])
            body.pack()
            photo = self._thumbnail(r.path)
            lbl = tk.Label(body, image=photo, bg=C["surface"], cursor="hand2")
            lbl.image = photo
            lbl.pack()
            # selection checkmark badge
            if selected:
                tk.Label(body, text="✓ selected", font=FONT_SMALL,
                         bg=C["accent"], fg="#FFFFFF").place(x=4, y=4)
            # red→green confidence bar
            conf_canvas = tk.Canvas(body, width=THUMB_SIZE, height=5,
                                    bg=C["border"], highlightthickness=0)
            conf_canvas.pack()
            conf_canvas.create_rectangle(
                0, 0, THUMB_SIZE * r.confidence, 5,
                fill=_conf_color(r.confidence), width=0)
            tk.Label(body, text=os.path.basename(r.path)[:22],
                     fg=C["fg_muted"], bg=C["surface"],
                     font=FONT_SMALL).pack(pady=(1, 2))

            for widget in (lbl, cell, body):
                widget.bind("<Button-1>", lambda e, res=r: self._toggle_select(res))
                widget.bind("<Double-Button-1>", lambda e, res=r: self._open_preview(res))
            lbl.bind("<Enter>", lambda e, c=body: c.config(bg=C["surface_hi"]))
            lbl.bind("<Leave>", lambda e, c=body: c.config(bg=C["surface"]))
        self.canvas.yview_moveto(0)

    def _thumbnail(self, path):
        if path not in self.thumb_cache:
            try:
                with Image.open(path) as img:
                    img.thumbnail((THUMB_SIZE, THUMB_SIZE))
                    self.thumb_cache[path] = ImageTk.PhotoImage(img.convert("RGB"))
            except Exception:
                placeholder = Image.new("RGB", (THUMB_SIZE, THUMB_SIZE),
                                        C["surface_hi"])
                self.thumb_cache[path] = ImageTk.PhotoImage(placeholder)
        return self.thumb_cache[path]

    def _toggle_select(self, result):
        if result.path in self.selected:
            self.selected.discard(result.path)
        else:
            self.selected.add(result.path)
        self._render_grid()
        self._update_action_bar()

    def _update_action_bar(self):
        n = len(self.selected)
        total = len(self._current_items()) if self.active_category else 0
        if n:
            self.sel_label.config(text=f"{n} selected", fg=C["accent_hi"])
        elif self.active_category:
            self.sel_label.config(
                text=f"{total} images — click thumbnails to select",
                fg=C["fg_muted"])
        else:
            self.sel_label.config(text="No category selected",
                                  fg=C["fg_muted"])
        self.remove_sel_btn.set_enabled(n > 0)
        self.clear_sel_btn.set_enabled(n > 0)
        self.remove_all_btn.set_enabled(total > 0)
        self.select_all_btn.set_enabled(total > 0)
        self.select_low_btn.set_enabled(total > 0)

    def _open_preview(self, result):
        win = tk.Toplevel(self.root)
        win.title(os.path.basename(result.path))
        win.configure(bg=C["bg"])
        sw, sh = win.winfo_screenwidth() - 100, win.winfo_screenheight() - 140
        try:
            with Image.open(result.path) as img:
                img.thumbnail((sw, sh))  # immediate downscale to screen size
                photo = ImageTk.PhotoImage(img.convert("RGB"))
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            win.destroy()
            return
        lbl = tk.Label(win, image=photo, bg=C["bg"])
        lbl.image = photo
        lbl.pack()
        tk.Label(win,
                 text=f"{result.category.replace('_', ' ')}  ·  "
                      f"confidence {result.confidence:.0%}  ·  {result.stage}",
                 font=FONT_BODY, bg=C["bg"], fg=C["fg_muted"]).pack(pady=6)
        win.bind("<Escape>", lambda e: win.destroy())

    # ------------------------------------------------------------ commands
    def select_all_in_category(self):
        for r in self._current_items():
            self.selected.add(r.path)
        self._render_grid()
        self._update_action_bar()

    def clear_selection(self):
        if self.selected:
            self.selected.clear()
            self._render_grid()
            self._update_action_bar()

    def select_low_confidence(self):
        for r in self._current_items():
            if r.confidence < 0.70:
                self.selected.add(r.path)
        self._render_grid()
        self._update_action_bar()

    def remove_selected(self):
        if not self.selected:
            return
        self._remove_paths(list(self.selected),
                           f"Move {len(self.selected)} selected images "
                           f"to trash?\n(Recoverable from .trash)")

    def remove_all_in_category(self):
        items = self._current_items()
        if not items:
            return
        name = ("duplicate groups" if self.active_category == "__dups__"
                else self.active_category.replace("_", " "))
        self._remove_paths([r.path for r in items],
                           f"Move ALL {len(items)} images in "
                           f"“{name}” to trash?\n"
                           f"(Recoverable from .trash)")

    def _remove_paths(self, paths, prompt):
        if not messagebox.askyesno("Confirm removal", prompt):
            return
        moved = file_ops.move_to_trash(self.folder, paths)
        gone = set(paths)
        self.results = [r for r in self.results if r.path not in gone]
        self.selected -= gone
        self.dup_groups = [
            {**g, "paths": [p for p in g["paths"] if p not in gone]}
            for g in self.dup_groups]
        self.dup_groups = [g for g in self.dup_groups if len(g["paths"]) > 1]
        self._refresh_category_list()
        self._render_grid()
        self._update_action_bar()
        self.status_label.config(
            text=f"Moved {moved} images to trash — use "
                 f"“Restore all from trash” to undo.")

    def restore_trash(self):
        n = file_ops.restore_from_trash(self.folder)
        self.status_label.config(text=f"Restored {n} images from trash. "
                                      f"Re-scan to include them again.")

    def empty_trash(self):
        entries = file_ops.list_trash(self.folder)
        if not entries:
            messagebox.showinfo("Trash", "Trash is already empty.")
            return
        if messagebox.askyesno(
                "Permanently delete",
                f"Permanently delete {len(entries)} files?\n"
                f"THIS CANNOT BE UNDONE."):
            n = file_ops.empty_trash(self.folder)
            self.status_label.config(text=f"Permanently deleted {n} files.")

    def export_csv(self):
        if not self.results:
            messagebox.showinfo("Export", "Nothing to export — scan first.")
            return
        dest = filedialog.asksaveasfilename(defaultextension=".csv",
                                            initialfile="gallery_report.csv")
        if dest:
            file_ops.export_csv(dest, self.results)
            self.status_label.config(text=f"Report exported to {dest}")


def main():
    root = tk.Tk()
    GalleryCleanerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
