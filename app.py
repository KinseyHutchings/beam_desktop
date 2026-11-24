"""Tkinter desktop application for beam analysis and section selection."""

from __future__ import annotations

import csv
import json
import math
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np

from calculations import MATERIALS, Load, analyze


ACCENT = "#2867e8"
TEAL = "#0e9f9a"
PURPLE = "#8b5bd6"


class SafeFigureCanvasTkAgg(FigureCanvasTkAgg):
    """Avoid a Tk/Aqua abort when Matplotlib requests an unsupported cursor."""

    def set_cursor(self, cursor):
        if sys.platform == "darwin":
            return
        super().set_cursor(cursor)


class ToolTip:
    def __init__(self, widget: tk.Widget, message: str):
        self.widget = widget
        self.message = message
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event=None):
        if self.window or not self.message:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self.window,
            text=self.message,
            justify="left",
            background="#182337",
            foreground="white",
            padx=10,
            pady=7,
            wraplength=300,
            font=("TkDefaultFont", 9),
        ).pack()

    def hide(self, _event=None):
        if self.window:
            self.window.destroy()
            self.window = None


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, width: int = 320):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, width=width, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=(12, 12, 10, 16))
        self.window_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body.bind("<Configure>", self._update_scrollregion)
        self.canvas.bind("<Configure>", self._resize_body)
        self.canvas.bind_all("<MouseWheel>", self._wheel, add="+")

    def _update_scrollregion(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_body(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _wheel(self, event):
        if self.winfo_ismapped() and self.winfo_containing(event.x_root, event.y_root):
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class BeamDesigner:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Beam Designer")
        self.root.geometry("1380x920")
        self.root.minsize(980, 680)
        self.dark_mode = False
        self._updating_controls = False
        self._dragging_index: int | None = None
        self._hover_lines = []
        self._hover_label = None
        self.analysis = None
        self.colors = {}

        self.span = 20.0
        self.support = "simply_supported"
        self.material = "Steel"
        self.section = "W12x26"
        self.deflection_divisor = 360
        self.loads = [Load("uniform", 1.0, start=0.0, end=20.0)]
        self.current_file: str | None = None

        self.style = ttk.Style()
        self._build_shell()
        self._build_inputs()
        self._build_results()
        self._apply_theme()
        self.render()

    def _build_shell(self):
        self.root.configure(background="#f3f6fb")
        self._build_menu()
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        self.header = ttk.Frame(self.root, padding=(18, 13, 20, 10))
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.header.columnconfigure(0, weight=1)
        title_area = ttk.Frame(self.header)
        title_area.grid(row=0, column=0, sticky="w")
        ttk.Label(title_area, text="STRUCTURAL ANALYSIS", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(title_area, text="Beam Designer", style="Title.TLabel").pack(anchor="w", pady=(1, 0))
        ttk.Label(
            title_area,
            text="Set up your beam, place loads, and check strength and stiffness.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        self.dark_var = tk.BooleanVar(value=False)
        self.dark_toggle = ttk.Checkbutton(
            self.header, text="Dark mode", variable=self.dark_var, command=self.toggle_dark
        )
        self.dark_toggle.grid(row=0, column=1, rowspan=3, sticky="e", padx=(10, 0))

        self.left_outer = ttk.Frame(self.root, style="Panel.TFrame")
        self.left_outer.grid(row=1, column=0, sticky="nsew", padx=(14, 8), pady=(0, 14))
        self.left_outer.configure(width=330)
        self.left_outer.grid_propagate(False)
        self.left_outer.rowconfigure(0, weight=1)
        self.left_outer.columnconfigure(0, weight=1)
        self.inputs_scroll = ScrollableFrame(self.left_outer, width=320)
        self.inputs_scroll.grid(row=0, column=0, sticky="nsew")

        self.right = ttk.Frame(self.root, padding=(0, 0, 14, 14))
        self.right.grid(row=1, column=1, sticky="nsew")
        self.right.rowconfigure(1, weight=1)
        self.right.columnconfigure(0, weight=1)
        self.right_header = ttk.Frame(self.right)
        self.right_header.grid(row=0, column=0, sticky="ew", pady=(2, 7))
        self.right_header.columnconfigure(0, weight=1)
        self.right_meta = ttk.Label(self.right_header, style="Meta.TLabel")
        self.right_meta.grid(row=0, column=0, sticky="w")
        self.export_button = ttk.Button(
            self.right_header, text="Export CSV", command=self.export_results
        )
        self.export_button.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.pdf_button = ttk.Button(
            self.right_header, text="Export PDF", command=self.export_pdf
        )
        self.pdf_button.grid(row=0, column=2, sticky="e", padx=(6, 0))

    def _build_menu(self):
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Open", accelerator="Ctrl+O", command=self.open_file)
        menu.add_cascade(label="File", menu=file_menu)
        self.root.configure(menu=menu)
        self.root.bind("<Command-s>", lambda _event: self.save_file())
        self.root.bind("<Command-o>", lambda _event: self.open_file())
        self.root.bind("<Control-s>", lambda _event: self.save_file())
        self.root.bind("<Control-o>", lambda _event: self.open_file())

    def _build_inputs(self):
        body = self.inputs_scroll.body
        body.columnconfigure(0, weight=1)

        ttk.Label(body, text="BEAM", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        support_box = ttk.Frame(body)
        support_box.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(support_box, text="Support type").pack(anchor="w")
        self.support_var = tk.StringVar(value="Simply supported")
        support_combo = ttk.Combobox(
            support_box,
            textvariable=self.support_var,
            values=("Simply supported", "Cantilever"),
            state="readonly",
            width=25,
        )
        support_combo.pack(fill="x", pady=(3, 0))
        support_combo.bind("<<ComboboxSelected>>", self._on_support_change)

        span_frame = ttk.Frame(body)
        span_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        span_frame.columnconfigure(0, weight=1)
        ttk.Label(span_frame, text="Span (ft)").grid(row=0, column=0, sticky="w")
        self.span_var = tk.StringVar(value="20")
        self.span_var.trace_add("write", lambda *_args: self._on_span_text())
        self.span_entry = ttk.Entry(span_frame, textvariable=self.span_var, width=8)
        self.span_entry.grid(row=0, column=1, sticky="e")
        self.span_entry.bind("<FocusOut>", self._normalize_span)
        self.span_entry.bind("<Return>", self._normalize_span)
        self.span_scale = tk.Scale(
            span_frame,
            from_=4,
            to=40,
            resolution=0.25,
            orient="horizontal",
            showvalue=False,
            highlightthickness=0,
            bd=0,
            command=self._on_span_slider,
        )
        self.span_scale.set(20)
        self.span_scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        ttk.Separator(body).grid(row=3, column=0, sticky="ew", pady=(7, 11))
        ttk.Label(body, text="LOADS", style="Section.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 5))
        self.loads_frame = ttk.Frame(body)
        self.loads_frame.grid(row=5, column=0, sticky="ew")
        self.loads_frame.columnconfigure(0, weight=1)
        self.load_rows = []
        self._rebuild_load_rows()

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, sticky="ew", pady=(6, 8))
        for column in (0, 1):
            buttons.columnconfigure(column, weight=1)
        ttk.Button(buttons, text="+ Point load", command=self.add_point_load).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="+ Uniform load", command=self.add_uniform_load).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Separator(body).grid(row=7, column=0, sticky="ew", pady=(7, 11))
        ttk.Label(body, text="SECTION", style="Section.TLabel").grid(row=8, column=0, sticky="w", pady=(0, 5))
        self.material_var = tk.StringVar(value=self.material)
        self.material_combo = ttk.Combobox(
            body, textvariable=self.material_var, values=tuple(MATERIALS), state="readonly"
        )
        self.material_combo.grid(row=9, column=0, sticky="ew", pady=(0, 8))
        self.material_combo.bind("<<ComboboxSelected>>", self._on_material_change)
        self.section_var = tk.StringVar(value=self.section)
        self.section_combo = ttk.Combobox(body, textvariable=self.section_var, state="readonly")
        self.section_combo.grid(row=10, column=0, sticky="ew")
        self.section_combo.bind("<<ComboboxSelected>>", self._on_section_change)
        self.section_meta = ttk.Label(body, text="", style="Meta.TLabel", wraplength=270)
        self.section_meta.grid(row=11, column=0, sticky="w", pady=(4, 9))

        ttk.Label(body, text="Deflection limit").grid(row=12, column=0, sticky="w", pady=(2, 3))
        self.limit_var = tk.StringVar(value="L/360")
        limit_combo = ttk.Combobox(
            body, textvariable=self.limit_var, values=("L/240", "L/360"), state="readonly"
        )
        limit_combo.grid(row=13, column=0, sticky="ew")
        limit_combo.bind("<<ComboboxSelected>>", self._on_limit_change)
        ttk.Label(body, text="Downward loads are positive · Self-weight ignored", style="Footnote.TLabel", wraplength=280).grid(
            row=14, column=0, sticky="w", pady=(12, 0)
        )
        self._update_section_choices()

    def _build_results(self):
        self.plot_card = ttk.Frame(self.right, style="Card.TFrame", padding=(10, 8, 10, 7))
        self.plot_card.grid(row=1, column=0, sticky="nsew")
        self.plot_card.rowconfigure(0, weight=1)
        self.plot_card.columnconfigure(0, weight=1)

        self.figure = Figure(figsize=(9, 6.7), dpi=100, constrained_layout=True)
        grid = self.figure.add_gridspec(4, 1, height_ratios=(0.95, 1, 1, 1), hspace=0.06)
        self.beam_ax = self.figure.add_subplot(grid[0])
        self.shear_ax = self.figure.add_subplot(grid[1], sharex=self.beam_ax)
        self.moment_ax = self.figure.add_subplot(grid[2], sharex=self.beam_ax)
        self.deflection_ax = self.figure.add_subplot(grid[3], sharex=self.beam_ax)
        self.axes = (self.beam_ax, self.shear_ax, self.moment_ax, self.deflection_ax)
        self.canvas = SafeFigureCanvasTkAgg(self.figure, master=self.plot_card)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.canvas.mpl_connect("motion_notify_event", self._on_plot_motion)
        self.canvas.mpl_connect("button_press_event", self._on_plot_press)
        self.canvas.mpl_connect("button_release_event", self._on_plot_release)

        self.hover_readout = ttk.Label(self.right, text="Hover over a diagram to inspect values.", style="Meta.TLabel")
        self.hover_readout.grid(row=2, column=0, sticky="ew", pady=(5, 7))
        cards = ttk.Frame(self.right)
        cards.grid(row=3, column=0, sticky="ew")
        for column in (0, 1):
            cards.columnconfigure(column, weight=1)
        self.bending_card, self.bending_value, self.bending_allow, self.bending_status, self.bending_bar = self._make_check_card(
            cards, 0, "Bending", "fb = |Mmax| × 12 / Sx. Pass when fb ≤ Fb."
        )
        self.deflection_card, self.deflection_value, self.deflection_allow, self.deflection_status, self.deflection_bar = self._make_check_card(
            cards, 1, "Deflection", "Pass when |ymax| ≤ L/240 or L/360, with L in inches."
        )
        self.recommend_frame = ttk.Frame(self.right, style="Card.TFrame", padding=(12, 8))
        self.recommend_frame.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        self.recommend_frame.columnconfigure(0, weight=1)
        self.recommend_title = ttk.Label(self.recommend_frame, text="", style="Recommend.TLabel")
        self.recommend_title.grid(row=0, column=0, sticky="w")
        self.recommend_text = ttk.Label(self.recommend_frame, text="", style="Meta.TLabel")
        self.recommend_text.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.use_recommendation = ttk.Button(
            self.recommend_frame, text="Use section", command=self._use_recommended
        )
        self.use_recommendation.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 0))

    def _make_check_card(self, parent, column, title, tooltip):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(11, 8))
        card.grid(row=0, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0))
        card.columnconfigure(0, weight=1)
        top = ttk.Frame(card)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text=title, style="CardTitle.TLabel").pack(side="left")
        status = ttk.Label(top, text="PASS", style="Pass.TLabel", padding=(6, 2))
        status.pack(side="right")
        value = ttk.Label(card, text="", style="Metric.TLabel")
        value.grid(row=1, column=0, sticky="w", pady=(3, 0))
        allow = ttk.Label(card, text="", style="Meta.TLabel")
        allow.grid(row=2, column=0, sticky="w")
        bar = tk.Canvas(card, height=8, highlightthickness=0, bd=0)
        bar.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        bar.bind("<Configure>", lambda _event, c=bar: self._draw_bar(c, 0, "#45a56b"))
        for widget in (card, top, value, allow):
            ToolTip(widget, tooltip)
        return card, value, allow, status, bar

    def _rebuild_load_rows(self):
        for child in self.loads_frame.winfo_children():
            child.destroy()
        self.load_rows = []
        for index, load in enumerate(self.loads):
            row = ttk.Frame(self.loads_frame, style="LoadRow.TFrame", padding=(7, 6))
            row.grid(row=index, column=0, sticky="ew", pady=(0, 5))
            row.columnconfigure(1, weight=1)
            row.columnconfigure(3, weight=1)
            label = "Point load" if load.kind == "point" else "Uniform load"
            ttk.Label(row, text=label, style="LoadTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
            ttk.Button(row, text="×", width=3, command=lambda i=index: self.remove_load(i)).grid(
                row=0, column=3, sticky="e", padx=(2, 0)
            )
            entries: dict[str, tk.StringVar] = {}
            unit = "k" if load.kind == "point" else "k/ft"
            self._make_load_entry(row, entries, index, "magnitude", unit, 1, 0)
            if load.kind == "point":
                self._make_load_entry(row, entries, index, "position", "ft", 1, 2)
            else:
                self._make_load_entry(row, entries, index, "start", "ft", 2, 0)
                self._make_load_entry(row, entries, index, "end", "ft", 2, 2)
            self.load_rows.append(entries)

    def _make_load_entry(self, parent, entries, index, key, unit, row, column):
        cell = ttk.Frame(parent)
        cell.grid(row=row, column=column, sticky="ew", padx=(0, 4) if column == 0 else (3, 0), pady=(3, 0))
        ttk.Label(cell, text=unit, style="Unit.TLabel").pack(side="right", padx=(3, 0))
        var = tk.StringVar(value=str(getattr(self.loads[index], key)))
        entry = ttk.Entry(cell, textvariable=var, width=8)
        entry.pack(side="right", fill="x", expand=True)
        entries[key] = var
        var.trace_add("write", lambda *_args, i=index, field=key, v=var: self._on_load_edit(i, field, v))
        entry.bind("<FocusOut>", lambda _event, i=index, field=key, v=var: self._normalize_load_field(i, field, v))
        entry.bind("<Return>", lambda _event, i=index, field=key, v=var: self._normalize_load_field(i, field, v))

    def _on_load_edit(self, index, key, variable):
        if self._updating_controls or index >= len(self.loads):
            return
        try:
            value = float(variable.get())
        except ValueError:
            return
        if not math.isfinite(value):
            return
        value = max(0.0, value)
        if key in ("position", "start", "end"):
            value = min(self.span, value)
        setattr(self.loads[index], key, value)
        self.render()

    def _normalize_load_field(self, index, key, variable):
        if index >= len(self.loads):
            return
        try:
            value = max(0.0, float(variable.get()))
        except ValueError:
            value = getattr(self.loads[index], key)
        if key in ("position", "start", "end"):
            value = min(self.span, value)
        setattr(self.loads[index], key, value)
        load = self.loads[index]
        if load.kind == "uniform" and load.end < load.start:
            load.start, load.end = load.end, load.start
            self._updating_controls = True
            self.load_rows[index]["start"].set(f"{load.start:g}")
            self.load_rows[index]["end"].set(f"{load.end:g}")
            self._updating_controls = False
        else:
            self._updating_controls = True
            variable.set(f"{value:g}")
            self._updating_controls = False
        self.render()

    def _on_span_slider(self, value):
        if self._updating_controls:
            return
        self._set_span(float(value), update_entry=True)

    def _normalize_span(self, _event=None):
        try:
            value = float(self.span_var.get())
        except ValueError:
            value = self.span
        self._set_span(value, update_entry=True)

    def _on_span_text(self):
        if self._updating_controls:
            return
        try:
            value = float(self.span_var.get())
        except ValueError:
            return
        if math.isfinite(value):
            self._set_span(value, update_entry=False)

    def _set_span(self, value, update_entry):
        value = min(40.0, max(4.0, value if math.isfinite(value) else 20.0))
        if abs(value - self.span) < 1e-9:
            if update_entry:
                self._updating_controls = True
                self.span_var.set(f"{value:g}")
                self.span_scale.set(value)
                self._updating_controls = False
            return
        self.span = value
        for load in self.loads:
            if load.kind == "point":
                load.position = min(value, load.position)
            else:
                load.start = min(value, load.start)
                load.end = min(value, load.end)
        self._updating_controls = True
        if update_entry:
            self.span_var.set(f"{value:g}")
        self.span_scale.set(value)
        self._updating_controls = False
        self._sync_load_entry_values()
        self.render()

    def _sync_load_entry_values(self):
        self._updating_controls = True
        for index, row in enumerate(self.load_rows):
            if index >= len(self.loads):
                continue
            for key, variable in row.items():
                variable.set(f"{getattr(self.loads[index], key):g}")
        self._updating_controls = False

    def _on_support_change(self, _event=None):
        self.support = "simply_supported" if self.support_var.get() == "Simply supported" else "cantilever"
        self.render()

    def _on_material_change(self, _event=None):
        self.material = self.material_var.get()
        sections = MATERIALS[self.material]["sections"]
        if self.section not in [item["name"] for item in sections]:
            self.section = sections[0]["name"]
        self._update_section_choices()
        self.render()

    def _on_section_change(self, _event=None):
        self.section = self.section_var.get()
        self.render()

    def _on_limit_change(self, _event=None):
        self.deflection_divisor = int(self.limit_var.get().split("/")[1])
        self.render()

    def _update_section_choices(self):
        sections = MATERIALS[self.material]["sections"]
        self.section_combo.configure(values=[item["name"] for item in sections])
        self.section_var.set(self.section)
        data = next(item for item in sections if item["name"] == self.section)
        weight = f" · {data['weight']:g} lb/ft" if data["weight"] is not None else ""
        self.section_meta.configure(text=f"Ix {data['ix']:g} in⁴ · Sx {data['sx']:g} in³{weight}")

    def add_point_load(self):
        position = self.span if self.support == "cantilever" else self.span / 2.0
        self.loads.append(Load("point", 1.0, position=position))
        self._rebuild_load_rows()
        self.render()

    def add_uniform_load(self):
        self.loads.append(Load("uniform", 0.1, start=0.0, end=self.span))
        self._rebuild_load_rows()
        self.render()

    def remove_load(self, index):
        if 0 <= index < len(self.loads):
            self.loads.pop(index)
            self._rebuild_load_rows()
            self.render()

    def _design_payload(self):
        loads = []
        for load in self.loads:
            item = {"type": load.kind, "magnitude": float(load.magnitude)}
            if load.kind == "point":
                item["position"] = float(load.position)
            else:
                item["start"] = float(load.start)
                item["end"] = float(load.end)
            loads.append(item)
        return {
            "support_type": self.support,
            "span": float(self.span),
            "material": self.material,
            "section": self.section,
            "deflection_limit": f"L/{self.deflection_divisor}",
            "loads": loads,
        }

    def save_file(self):
        path = self.current_file
        if not path:
            path = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save beam design",
                initialfile="beam_design.json",
                defaultextension=".json",
                filetypes=(
                    ("Beam design", "*.json"),
                    ("JSON files", "*.json"),
                    ("All files", "*"),
                ),
            )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as design_file:
                json.dump(self._design_payload(), design_file, indent=2)
                design_file.write("\n")
        except (OSError, TypeError) as error:
            messagebox.showerror("Save failed", f"Could not save the beam design.\n\n{error}")
            return
        self.current_file = path

    def open_file(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open beam design",
            filetypes=(
                ("Beam design", "*.json"),
                ("JSON files", "*.json"),
                ("All files", "*"),
            ),
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as design_file:
                data = json.load(design_file)
            support = data["support_type"]
            if support not in ("simply_supported", "cantilever"):
                raise ValueError("The file has an unknown support type.")
            span = float(data["span"])
            if not math.isfinite(span) or not 4 <= span <= 40:
                raise ValueError("The span must be between 4 and 40 ft.")
            material = data.get("material", "Steel")
            if material not in MATERIALS:
                raise ValueError("The file has an unknown material.")
            section = data["section"]
            sections = MATERIALS[material]["sections"]
            if section not in {item["name"] for item in sections}:
                raise ValueError("The file has an unknown section for its material.")
            limit = data["deflection_limit"]
            if limit not in ("L/240", "L/360"):
                raise ValueError("The deflection limit must be L/240 or L/360.")
            saved_loads = data.get("loads", [])
            if not isinstance(saved_loads, list):
                raise ValueError("The loads value must be a list.")
            loads = []
            for item in saved_loads:
                kind = item["type"]
                magnitude = float(item["magnitude"])
                if kind == "point":
                    loads.append(Load("point", magnitude, position=float(item["position"])))
                elif kind == "uniform":
                    loads.append(
                        Load(
                            "uniform",
                            magnitude,
                            start=float(item["start"]),
                            end=float(item["end"]),
                        )
                    )
                else:
                    raise ValueError("The file contains an unknown load type.")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            messagebox.showerror("Open failed", f"Could not open the beam design.\n\n{error}")
            return

        self._updating_controls = True
        self.span = span
        self.support = support
        self.material = material
        self.section = section
        self.deflection_divisor = int(limit.split("/")[1])
        self.loads = loads
        self.span_var.set(f"{span:g}")
        self.span_scale.set(span)
        self.support_var.set("Simply supported" if support == "simply_supported" else "Cantilever")
        self.material_var.set(material)
        self.limit_var.set(limit)
        self._updating_controls = False
        self._update_section_choices()
        self._rebuild_load_rows()
        self.current_file = path
        self.render()

    def export_results(self):
        if self.analysis is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export beam results",
            initialfile="beam_results.csv",
            defaultextension=".csv",
            filetypes=(("CSV files", "*.csv"), ("All files", "*")),
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as results_file:
                writer = csv.writer(results_file)
                writer.writerow(
                    [
                        "Position (ft)",
                        "Shear (kips)",
                        "Moment (kip-ft)",
                        "Deflection (in)",
                    ]
                )
                writer.writerows(
                    zip(
                        self.analysis.x.tolist(),
                        self.analysis.shear.tolist(),
                        self.analysis.moment.tolist(),
                        self.analysis.deflection.tolist(),
                    )
                )
        except (OSError, csv.Error) as error:
            messagebox.showerror(
                "Export failed", f"Could not export the beam results.\n\n{error}"
            )

    def export_pdf(self):
        if self.analysis is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export calculation sheet",
            initialfile="beam_calculation_sheet.pdf",
            defaultextension=".pdf",
            filetypes=(("PDF files", "*.pdf"), ("All files", "*")),
        )
        if not path:
            return

        try:
            report = Figure(figsize=(8.5, 11), dpi=150, facecolor="white")
            report.text(
                0.08,
                0.965,
                "Beam Designer — Calculation Sheet",
                fontsize=16,
                fontweight="bold",
                color="#25344c",
                va="top",
            )
            report.text(
                0.08,
                0.938,
                "Structural analysis report",
                fontsize=9,
                color="#738198",
                va="top",
            )
            support_label = "Simply supported" if self.support == "simply_supported" else "Cantilever"
            report.text(
                0.08,
                0.900,
                f"Inputs    Support: {support_label}    Span: {self.span:g} ft    "
                f"Material: {self.material}    Section: {self.section}    "
                f"Deflection limit: L/{self.deflection_divisor}",
                fontsize=8.5,
                color="#25344c",
                va="top",
            )
            load_text = "Loads: " + ("None" if not self.loads else "; ".join(self._format_load(load) for load in self.loads))
            report.text(
                0.08,
                0.866,
                load_text,
                fontsize=8,
                color="#4f6078",
                va="top",
                wrap=True,
            )
            reaction_text = (
                f"Reactions: Rₗ {self.analysis.reaction_left:.2f} k, "
                f"Rᵣ {self.analysis.reaction_right:.2f} k"
                if self.support == "simply_supported"
                else f"Reaction: {self.analysis.reaction_left:.2f} k    "
                f"Fixed-end moment: {self.analysis.fixed_end_moment:.2f} kip-ft"
            )
            report.text(0.08, 0.837, reaction_text, fontsize=8, color="#4f6078", va="top")

            beam_axis = report.add_axes([0.12, 0.700, 0.80, 0.105])
            self._draw_report_beam(beam_axis)
            self._draw_report_diagram(
                report.add_axes([0.12, 0.515, 0.80, 0.135]),
                self.analysis.shear,
                "Shear",
                "kips",
                ACCENT,
                self.analysis.max_shear,
            )
            self._draw_report_diagram(
                report.add_axes([0.12, 0.335, 0.80, 0.135]),
                self.analysis.moment,
                "Moment",
                "kip-ft",
                TEAL,
                self.analysis.max_moment,
            )
            self._draw_report_diagram(
                report.add_axes([0.12, 0.155, 0.80, 0.135]),
                self.analysis.deflection,
                "Deflection",
                "in",
                PURPLE,
                self.analysis.max_deflection,
                invert=True,
                x_label=True,
            )

            report.text(0.12, 0.112, "Design checks", fontsize=10, fontweight="bold", color="#25344c")
            bending_pass = self.analysis.bending_ratio <= 1.0
            deflection_pass = self.analysis.deflection_ratio <= 1.0
            report.text(
                0.12,
                0.082,
                f"Bending: {self.analysis.bending_stress:.2f} ksi / "
                f"{self.analysis.allowable_bending:.2f} ksi allowable    "
                f"{'PASS' if bending_pass else 'FAIL'}",
                fontsize=8.5,
                color="#287747" if bending_pass else "#a62c34",
                fontweight="bold",
            )
            report.text(
                0.12,
                0.058,
                f"Deflection: {abs(self.analysis.deflection[self.analysis.max_deflection]):.3f} in / "
                f"{self.analysis.deflection_limit:.3f} in allowable    "
                f"{'PASS' if deflection_pass else 'FAIL'}",
                fontsize=8.5,
                color="#287747" if deflection_pass else "#a62c34",
                fontweight="bold",
            )
            if self.analysis.recommendation:
                report.text(
                    0.58,
                    0.082,
                    f"Lightest passing section: {self.analysis.recommendation}",
                    fontsize=8,
                    color="#4f6078",
                )
            report.text(0.08, 0.025, "Generated by Beam Designer", fontsize=7, color="#9aa7b8")

            with PdfPages(path) as pdf:
                pdf.infodict()["Title"] = "Beam Designer Calculation Sheet"
                pdf.infodict()["Subject"] = "Beam design inputs, diagrams, and checks"
                pdf.savefig(report, facecolor="white")
        except (OSError, ValueError) as error:
            messagebox.showerror(
                "PDF export failed", f"Could not export the calculation sheet.\n\n{error}"
            )

    @staticmethod
    def _format_load(load):
        if load.kind == "point":
            return f"Point {load.magnitude:g} k @ {load.position:g} ft"
        return f"Uniform {load.magnitude:g} k/ft from {load.start:g} to {load.end:g} ft"

    def _draw_report_beam(self, axis):
        axis.set_xlim(0, self.span)
        axis.set_ylim(0, 1)
        axis.axis("off")
        y = 0.48
        axis.plot([0, self.span], [y, y], color="#25344c", lw=4, solid_capstyle="round")
        if self.support == "simply_supported":
            for x in (0, self.span):
                width = max(self.span * 0.018, 0.18)
                axis.fill(
                    [x - width, x, x + width],
                    [0.22, 0.42, 0.22],
                    facecolor="#dbe4f3",
                    edgecolor="#71819c",
                    lw=0.7,
                )
                axis.plot([x - width * 1.6, x + width * 1.6], [0.20, 0.20], color="#71819c", lw=0.7)
        else:
            axis.plot([0, 0], [0.20, 0.78], color="#71819c", lw=3)
        for load in self.loads:
            if load.kind == "point":
                x = min(self.span, max(0.0, load.position))
                axis.annotate(
                    "",
                    xy=(x, y + 0.02),
                    xytext=(x, 0.87),
                    arrowprops={"arrowstyle": "-|>", "color": ACCENT, "lw": 1.2},
                )
                axis.text(x, 0.90, f"{load.magnitude:g} k", ha="center", va="bottom", fontsize=7, color=ACCENT)
            elif load.end > load.start:
                a, b = max(0.0, load.start), min(self.span, load.end)
                axis.plot([a, b], [0.80, 0.80], color=TEAL, lw=1.2)
                count = max(2, int((b - a) / max(self.span / 14, 0.1)) + 1)
                for x in np.linspace(a, b, count):
                    axis.annotate(
                        "",
                        xy=(x, y + 0.02),
                        xytext=(x, 0.79),
                        arrowprops={"arrowstyle": "-|>", "color": TEAL, "lw": 0.7},
                    )
                axis.text((a + b) / 2, 0.83, f"{load.magnitude:g} k/ft", ha="center", va="bottom", fontsize=7, color=TEAL)
        axis.text(0, 0.02, "0 ft", ha="left", va="bottom", fontsize=6.5, color="#738198")
        axis.text(self.span, 0.02, f"{self.span:g} ft", ha="right", va="bottom", fontsize=6.5, color="#738198")
        axis.text(0, 1.02, "Beam and applied loads", ha="left", va="bottom", fontsize=8, fontweight="bold", color="#4f6078")

    def _draw_report_diagram(self, axis, values, title, unit, color, data_index, invert=False, x_label=False):
        x = self.analysis.x
        axis.set_facecolor("#f2f7fc")
        axis.axhline(0, color="#cfd7e3", lw=0.7)
        axis.fill_between(x, values, 0, color=color, alpha=0.14)
        axis.plot(x, values, color=color, lw=1.4)
        axis.scatter([x[data_index]], [values[data_index]], color=color, s=12, zorder=3)
        axis.annotate(
            f"{values[data_index]:.3f} {unit}" if unit == "in" else f"{values[data_index]:.2f} {unit}",
            (x[data_index], values[data_index]),
            xytext=(4, 5 if values[data_index] >= 0 else -12),
            textcoords="offset points",
            fontsize=7,
            color=color,
            fontweight="bold",
        )
        extent = max(npmax_abs(values), 1e-6)
        axis.set_ylim(-extent * 1.28, extent * 1.28)
        if invert:
            axis.set_ylim(extent * 1.28, -extent * 1.28)
        axis.set_xlim(0, self.span)
        axis.set_ylabel(f"{title}\n({unit})", rotation=0, ha="right", va="center", fontsize=7, color="#738198")
        axis.yaxis.set_label_coords(-0.025, 0.5)
        axis.tick_params(axis="both", labelsize=6.5, colors="#738198", length=2)
        axis.grid(axis="x", color="#dce4ef", lw=0.4)
        if not x_label:
            axis.tick_params(axis="x", labelbottom=False)
        else:
            axis.set_xlabel("Position along beam (ft)", fontsize=7, color="#738198")
        for edge in axis.spines.values():
            edge.set_visible(False)

    def _draw_bar(self, canvas, ratio, color):
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        canvas.create_rectangle(0, 1, width, 7, fill=self.colors.get("bar_bg", "#e7edf5"), outline="")
        if ratio > 0:
            canvas.create_rectangle(0, 1, width * min(1.0, ratio), 7, fill=color, outline="")

    def _set_check(self, value_label, allow_label, status_label, bar, actual, allowable, unit, ratio, digits):
        value_label.configure(text=f"{actual:.{digits}f} {unit}")
        allow_label.configure(text=f"Allowable {allowable:.{digits}f} {unit}")
        passed = ratio <= 1.0
        status_label.configure(text="PASS" if passed else "FAIL", style="Pass.TLabel" if passed else "Fail.TLabel")
        color = "#45a56b" if ratio < 0.7 else "#e4a124" if ratio <= 1.0 else "#d95359"
        self._draw_bar(bar, ratio, color)

    def _build_diagram(self, axis, values, title, unit, color, data_index, show_x=False):
        axis.clear()
        x = self.analysis.x
        axis.set_facecolor(self.colors["plot"])
        axis.axhline(0, color=self.colors["grid"], lw=0.8, zorder=1)
        axis.fill_between(x, values, 0, color=color, alpha=0.14, zorder=2)
        axis.plot(x, values, color=color, lw=1.8, zorder=3)
        index = data_index
        max_value = values[index]
        axis.scatter([x[index]], [max_value], s=16, color=color, zorder=4)
        axis.annotate(
            f"{max_value:.3f} {unit}" if unit == "in" else f"{max_value:.2f} {unit}",
            (x[index], max_value),
            xytext=(5, 7 if max_value >= 0 else -13),
            textcoords="offset points",
            fontsize=8,
            color=color,
            fontweight="bold",
            clip_on=True,
        )
        extent = max(float(npmax_abs(values)), 1e-6)
        axis.set_ylim(-extent * 1.28, extent * 1.28)
        if unit == "in":
            axis.set_ylim(extent * 1.28, -extent * 1.28)
        axis.set_xlim(0, self.span)
        axis.set_ylabel(f"{title}\n({unit})", rotation=0, ha="right", va="center", fontsize=8, color=self.colors["muted"])
        axis.yaxis.set_label_coords(-0.025, 0.5)
        axis.tick_params(axis="y", labelsize=7, colors=self.colors["muted"], length=2)
        axis.tick_params(axis="x", labelsize=8, colors=self.colors["muted"], length=2, labelbottom=show_x)
        axis.grid(axis="x", color=self.colors["grid"], lw=0.5, alpha=0.65)
        for edge in axis.spines.values():
            edge.set_visible(False)
        if show_x:
            axis.set_xlabel("Position along beam (ft)", fontsize=8, color=self.colors["muted"])

    def _draw_beam(self):
        axis = self.beam_ax
        axis.clear()
        axis.set_facecolor(self.colors["plot"])
        axis.set_xlim(0, self.span)
        axis.set_ylim(0, 1)
        axis.axis("off")
        y = 0.50
        axis.plot([0, self.span], [y, y], color=self.colors["ink"], lw=5, solid_capstyle="round", zorder=3)
        if self.support == "simply_supported":
            for x in (0, self.span):
                axis.fill([x - self.span * 0.018, x, x + self.span * 0.018], [0.25, 0.45, 0.25],
                          facecolor=self.colors["support"], edgecolor=self.colors["muted"], lw=0.8, zorder=2)
                axis.plot([x - self.span * 0.03, x + self.span * 0.03], [0.23, 0.23], color=self.colors["muted"], lw=0.8)
            self._up_arrow(axis, 0, y - 0.02, 0.27, self.colors["reaction"])
            self._up_arrow(axis, self.span, y - 0.02, 0.27, self.colors["reaction"])
            axis.text(0, 0.04, f"Rₗ {self.analysis.reaction_left:.2f} k", ha="left", va="bottom", fontsize=8, color=self.colors["muted"])
            axis.text(self.span, 0.04, f"Rᵣ {self.analysis.reaction_right:.2f} k", ha="right", va="bottom", fontsize=8, color=self.colors["muted"])
        else:
            axis.plot([0, 0], [0.25, 0.78], color=self.colors["muted"], lw=4)
            self._up_arrow(axis, 0, y - 0.02, 0.26, self.colors["reaction"])
            axis.text(0, 0.04, f"R {self.analysis.reaction_left:.2f} k  ·  M {self.analysis.fixed_end_moment:.2f} kip-ft",
                      ha="left", va="bottom", fontsize=8, color=self.colors["muted"])

        for index, load in enumerate(self.loads):
            if load.kind == "point":
                x = min(self.span, max(0.0, load.position))
                axis.annotate("", xy=(x, y + 0.025), xytext=(x, 0.90),
                              arrowprops={"arrowstyle": "-|>", "color": ACCENT, "lw": 1.5, "mutation_scale": 9}, zorder=5)
                axis.text(x, 0.94, f"{load.magnitude:g} k", ha="center", va="bottom", fontsize=8, color=ACCENT)
                axis.scatter([x], [y + 0.03], s=70, color="none", edgecolor="none", picker=True, zorder=6)
            elif load.end > load.start:
                a, b = max(0.0, load.start), min(self.span, load.end)
                axis.plot([a, b], [0.84, 0.84], color=TEAL, lw=1.5)
                count = max(2, int((b - a) / max(self.span / 14, 0.1)) + 1)
                for x in np.linspace(a, b, count):
                    axis.annotate("", xy=(x, y + 0.025), xytext=(x, 0.83),
                                  arrowprops={"arrowstyle": "-|>", "color": TEAL, "lw": 0.9, "mutation_scale": 7}, zorder=4)
                axis.text((a + b) / 2, 0.87, f"{load.magnitude:g} k/ft", ha="center", va="bottom", fontsize=8, color=TEAL)
        axis.text(0, 0.01, "0 ft", ha="left", va="bottom", fontsize=7, color=self.colors["muted"])
        axis.text(self.span, 0.01, f"{self.span:g} ft", ha="right", va="bottom", fontsize=7, color=self.colors["muted"])
        axis.text(0.01, 0.99, "BEAM & APPLIED LOADS", transform=axis.transAxes,
                  ha="left", va="top", fontsize=8, fontweight="bold", color=self.colors["muted"])

    @staticmethod
    def _up_arrow(axis, x, y, height, color):
        axis.annotate("", xy=(x, y + height), xytext=(x, y),
                      arrowprops={"arrowstyle": "-|>", "color": color, "lw": 1.1, "mutation_scale": 8}, zorder=4)

    def render(self):
        if not hasattr(self, "canvas"):
            return
        self.analysis = analyze(
            self.span, self.support, self.loads, self.material, self.section, self.deflection_divisor
        )
        self.right_meta.configure(
            text=f"{self.span:g} ft  ·  {'Simply supported' if self.support == 'simply_supported' else 'Cantilever'}  ·  {self.section}"
        )
        self._draw_beam()
        self._build_diagram(self.shear_ax, self.analysis.shear, "Shear", "kips", ACCENT, self.analysis.max_shear)
        self._build_diagram(self.moment_ax, self.analysis.moment, "Moment", "kip-ft", TEAL, self.analysis.max_moment)
        self._build_diagram(self.deflection_ax, self.analysis.deflection, "Deflection", "in", PURPLE, self.analysis.max_deflection, True)
        self._hover_lines = [axis.axvline(0, color=self.colors["crosshair"], lw=0.9, ls="--", visible=False) for axis in
                             (self.shear_ax, self.moment_ax, self.deflection_ax)]
        self._set_check(
            self.bending_value, self.bending_allow, self.bending_status, self.bending_bar,
            self.analysis.bending_stress, self.analysis.allowable_bending, "ksi",
            self.analysis.bending_ratio, 2,
        )
        self._set_check(
            self.deflection_value, self.deflection_allow, self.deflection_status, self.deflection_bar,
            abs(self.analysis.deflection[self.analysis.max_deflection]), self.analysis.deflection_limit,
            "in", self.analysis.deflection_ratio, 3,
        )
        recommendation = self.analysis.recommendation
        if recommendation:
            self.recommend_title.configure(text=f"Lightest passing section · {recommendation}")
            self.recommend_text.configure(text=f"{recommendation} meets both bending and deflection checks for this design.")
            self.use_recommendation.state(["!disabled"])
        else:
            self.recommend_title.configure(text="No listed section passes")
            self.recommend_text.configure(text="Consider a larger section or review the loads and span.")
            self.use_recommendation.state(["disabled"])
        self.canvas.draw_idle()

    def _on_plot_press(self, event):
        if event.inaxes != self.beam_ax or event.xdata is None:
            return
        candidates = [(abs(load.position - event.xdata), index) for index, load in enumerate(self.loads) if load.kind == "point"]
        if candidates:
            distance, index = min(candidates)
            if distance <= max(0.5, self.span * 0.025):
                self._dragging_index = index

    def _on_plot_release(self, _event):
        if self._dragging_index is not None:
            self._dragging_index = None
            self._sync_load_entry_values()

    def _on_plot_motion(self, event):
        if self._dragging_index is not None:
            if event.x is not None and 0 <= self._dragging_index < len(self.loads):
                x = self.beam_ax.transData.inverted().transform((event.x, event.y))[0]
                x = min(self.span, max(0.0, round(x * 4.0) / 4.0))
                self.loads[self._dragging_index].position = x
                self._sync_load_entry_values()
                self.render()
            return
        if event.inaxes not in (self.shear_ax, self.moment_ax, self.deflection_ax) or event.xdata is None:
            return
        x = min(self.span, max(0.0, event.xdata))
        for line in self._hover_lines:
            line.set_xdata((x, x))
            line.set_visible(True)
        index = int(npsearch(self.analysis.x, x))
        i0, i1 = max(0, index - 1), min(len(self.analysis.x) - 1, index)
        if abs(self.analysis.x[i0] - x) <= abs(self.analysis.x[i1] - x):
            index = i0
        else:
            index = i1
        self.hover_readout.configure(
            text=(f"{self.analysis.x[index]:.2f} ft  ·  V {self.analysis.shear[index]:.2f} k  ·  "
                  f"M {self.analysis.moment[index]:.2f} kip-ft  ·  y {self.analysis.deflection[index]:.3f} in")
        )
        self.canvas.draw_idle()

    def _use_recommended(self):
        if self.analysis and self.analysis.recommendation:
            self.section = self.analysis.recommendation
            self._update_section_choices()
            self.render()

    def toggle_dark(self):
        self.dark_mode = self.dark_var.get()
        self._apply_theme()
        self.render()

    def _apply_theme(self):
        if self.dark_mode:
            bg, card, text, muted, entry, plot = "#111827", "#1b2638", "#e8edf5", "#9aa9bd", "#222f43", "#151f30"
            grid, ink, support, crosshair = "#354258", "#d4deec", "#344660", "#a5b5ca"
        else:
            bg, card, text, muted, entry, plot = "#f3f6fb", "#ffffff", "#243247", "#738198", "#ffffff", "#f2f7fc"
            grid, ink, support, crosshair = "#dce4ef", "#25344c", "#dbe4f3", "#475569"
        self.colors = {
            "bg": bg, "card": card, "text": text, "muted": muted, "entry": entry,
            "plot": plot, "grid": grid, "ink": ink, "support": support,
            "crosshair": crosshair, "reaction": "#45a56b", "bar_bg": "#354258" if self.dark_mode else "#e7edf5",
        }
        self.root.configure(background=bg)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background=bg)
        self.style.configure("Panel.TFrame", background=card)
        self.style.configure("Card.TFrame", background=card)
        self.style.configure("LoadRow.TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=text, font=("TkDefaultFont", 9))
        self.style.configure("Eyebrow.TLabel", background=bg, foreground=ACCENT, font=("TkDefaultFont", 8, "bold"))
        self.style.configure("Title.TLabel", background=bg, foreground=text, font=("TkDefaultFont", 22, "bold"))
        self.style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=("TkDefaultFont", 9))
        self.style.configure("Meta.TLabel", background=bg, foreground=muted, font=("TkDefaultFont", 8))
        self.style.configure("Section.TLabel", background=card, foreground=muted, font=("TkDefaultFont", 8, "bold"))
        self.style.configure("Footnote.TLabel", background=card, foreground=muted, font=("TkDefaultFont", 8))
        self.style.configure("Unit.TLabel", background=bg, foreground=muted, font=("TkDefaultFont", 8))
        self.style.configure("CardTitle.TLabel", background=card, foreground=text, font=("TkDefaultFont", 9, "bold"))
        self.style.configure("Metric.TLabel", background=card, foreground=text, font=("TkDefaultFont", 15, "bold"))
        self.style.configure("Recommend.TLabel", background=card, foreground=text, font=("TkDefaultFont", 10, "bold"))
        self.style.configure("LoadTitle.TLabel", background=bg, foreground=text, font=("TkDefaultFont", 9, "bold"))
        self.style.configure("TEntry", fieldbackground=entry, foreground=text, padding=4)
        self.style.configure("TCombobox", fieldbackground=entry, foreground=text, padding=4)
        self.style.configure("TButton", padding=(7, 4))
        self.style.configure("TCheckbutton", background=bg, foreground=text)
        self.style.configure("TSeparator", background=grid)
        self.style.configure("Pass.TLabel", background="#e4f5eb", foreground="#287747", font=("TkDefaultFont", 8, "bold"))
        self.style.configure("Fail.TLabel", background="#fde9e9", foreground="#a62c34", font=("TkDefaultFont", 8, "bold"))
        self.inputs_scroll.canvas.configure(background=card)
        self.span_scale.configure(background=card, fg=text, troughcolor=grid, activebackground=ACCENT)


def npmax_abs(values):
    return max(abs(float(value)) for value in values)


def npsearch(values, target):
    """Return the first sample at or to the right of target."""
    low, high = 0, len(values)
    while low < high:
        middle = (low + high) // 2
        if values[middle] < target:
            low = middle + 1
        else:
            high = middle
    return min(low, len(values) - 1)


def main():
    root = tk.Tk()
    BeamDesigner(root)
    root.mainloop()


if __name__ == "__main__":
    main()
