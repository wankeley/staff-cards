"""
Staff QR Code Generator (tkinter GUI + Windows .exe friendly)

Generates one QR-code PNG per staff member in staff.json. Each QR encodes
that person's card URL, e.g.:
    https://wankeley.github.io/staff-cards/index.html?id=emp001

staff.json may be either:
  * a LIST of records  [{"employeeId": "...", "fullName": "...", ...}, ...], or
  * a DICT keyed by employee id  {"emp001": {"name": "...", ...}, ...}

Setup:
    pip install "qrcode[pil]" pillow

Usage:
    python generate_qr_codes.py
"""

import csv
import glob
import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from urllib.parse import quote

import qrcode
from PIL import Image, ImageDraw, ImageFont

# --- Configuration ---------------------------------------------------------

DEFAULT_BASE_URL = "https://wankeley.github.io/staff-cards/index.html"
DEFAULT_STAFF_FILE = "staff.json"
DEFAULT_OUTPUT_DIR = "qr_codes"

TEXT_COLOR = "#111111"
BG_COLOR = "#ffffff"

# ---------------------------------------------------------------------------


def resource_path(relative):
    """Path to a resource bundled with a PyInstaller exe, or next to the script."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


def app_dir():
    """Folder used as the default place for staff.json / qr_codes when frozen."""
    return os.getcwd()


def font_candidates():
    """Bundled fonts first (assets/fonts/*.ttf|otf), then common Windows fonts."""
    found = sorted(
        glob.glob(resource_path(os.path.join("assets", "fonts", "*.ttf")))
        + glob.glob(resource_path(os.path.join("assets", "fonts", "*.otf")))
    )
    return found + ["arial.ttf", "segoeui.ttf", "tahoma.ttf"]


def load_font(size, cache={}):
    if size in cache:
        return cache[size]
    font = None
    for path in font_candidates():
        try:
            font = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    cache[size] = font
    return font


def load_staff(path):
    """Return a list of record dicts, accepting either a JSON list or dict."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                records.append(dict(item))
    elif isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                rec = dict(value)
                if not str(rec.get("employeeId") or "").strip():
                    rec["employeeId"] = key
                if not str(rec.get("fullName") or "").strip():
                    rec["fullName"] = str(value.get("name") or key)
                records.append(rec)
    else:
        raise ValueError(
            "staff.json must contain a list of records or a dict keyed by employee id."
        )
    return records


def display_name(rec):
    name = str(rec.get("fullName") or "").strip()
    if not name:
        name = " ".join(
            str(rec.get(part) or "").strip()
            for part in ("firstName", "surname")
        ).strip()
    return name


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:100] or "unknown"


def build_qr_image(url, line1, line2):
    """QR (black on white, scannable) with centred name + ID text below."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    qw, qh = qr_img.size
    margin = 24
    gap = 16
    canvas_w = qw + 2 * margin
    max_text_w = qw

    probe = ImageDraw.Draw(qr_img)
    size = max(18, int(qh * 0.07))
    while size > 10:
        f1 = load_font(size)
        f2 = load_font(max(12, size - 6))
        w1 = probe.textlength(line1, font=f1)
        w2 = probe.textlength(line2, font=f2)
        if w1 <= max_text_w and w2 <= max_text_w:
            break
        size -= 2
    else:
        f1 = load_font(10)
        f2 = load_font(10)

    line_h1 = size + 4
    line_h2 = max(12, size - 6) + 4
    canvas_h = margin + qh + gap + line_h1 + 4 + line_h2 + margin

    img = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
    img.paste(qr_img, (margin, margin))
    draw = ImageDraw.Draw(img)
    cx = canvas_w // 2
    y = margin + qh + gap
    draw.text((cx, y + line_h1 // 2), line1, font=f1, fill=TEXT_COLOR, anchor="mm")
    draw.text((cx, y + line_h1 + 4 + line_h2 // 2), line2, font=f2, fill=TEXT_COLOR, anchor="mm")
    return img


def generate_all(staff_path, output_dir, base_url, log):
    """Core generation. Returns (generated, skipped, failed) lists."""
    base_url = base_url.strip().rstrip("?").rstrip("&")
    records = load_staff(staff_path)
    os.makedirs(output_dir, exist_ok=True)

    generated, skipped, failed = [], [], []
    used_names = set()

    csv_path = os.path.join(output_dir, "index.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["employeeId", "fullName", "url", "filename"])

        for i, rec in enumerate(records, 1):
            name = display_name(rec) or "(unnamed)"
            emp_id = str(rec.get("employeeId") or "").strip()
            if not emp_id:
                skipped.append(name)
                log(f"SKIPPED {name}: record has no employeeId.")
                continue

            url = f"{base_url}?id={quote(emp_id)}"
            filename = sanitize_filename(f"{emp_id}_{name}") + ".png"
            if filename in used_names:
                filename = sanitize_filename(f"{emp_id}_{name}_{i}") + ".png"
            used_names.add(filename)

            try:
                img = build_qr_image(url, name, f"ID: {emp_id}")
                img.save(os.path.join(output_dir, filename))
                writer.writerow([emp_id, name, url, filename])
                generated.append((name, filename))
                log(f"Generated {filename}  ->  {url}")
            except Exception as exc:
                failed.append((name, str(exc)))
                log(f"FAILED  {name}: {exc}")

    log(f"Index written to {csv_path}")
    return generated, skipped, failed


# --- GUI --------------------------------------------------------------------


class App:
    def __init__(self, root):
        self.root = root
        root.title("Staff QR Code Generator")
        root.geometry("720x560")
        root.minsize(560, 440)

        self.msgs = queue.Queue()
        self.running = False

        pad = {"padx": 10, "pady": 4}
        form = ttk.Frame(root)
        form.pack(fill="x", **pad)
        form.columnconfigure(1, weight=1)

        self.staff_var = tk.StringVar(
            value=os.path.join(app_dir(), DEFAULT_STAFF_FILE)
            if os.path.exists(os.path.join(app_dir(), DEFAULT_STAFF_FILE))
            else DEFAULT_STAFF_FILE
        )
        self.out_var = tk.StringVar(value=os.path.join(app_dir(), DEFAULT_OUTPUT_DIR))
        self.url_var = tk.StringVar(value=DEFAULT_BASE_URL)

        ttk.Label(form, text="Staff JSON file:").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.staff_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(form, text="Browse...", command=self.browse_staff).grid(row=0, column=2)

        ttk.Label(form, text="Output folder:").grid(row=1, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.out_var).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(form, text="Browse...", command=self.browse_output).grid(row=1, column=2)

        ttk.Label(form, text="Base card URL:").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.url_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=6)

        self.warn_label = ttk.Label(
            form,
            text="Warning: the URL contains '/blob/' - that is a GitHub file page. "
                 "Use your GitHub Pages link instead, e.g. "
                 "https://<user>.github.io/<repo>/index.html",
            foreground="#b00020",
            wraplength=640,
            justify="left",
        )
        self.url_var.trace_add("write", lambda *_: self.refresh_warning())
        self.warn_label.grid(row=3, column=0, columnspan=3, sticky="w")

        btns = ttk.Frame(root)
        btns.pack(fill="x", **pad)
        self.gen_btn = ttk.Button(btns, text="Generate QR codes", command=self.start)
        self.gen_btn.pack(side="left")
        ttk.Button(btns, text="Open output folder", command=self.open_output).pack(side="left", padx=8)

        self.progress = ttk.Progressbar(btns, mode="indeterminate", length=140)
        self.progress.pack(side="right")

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(root, textvariable=self.status).pack(fill="x", padx=10)

        self.log_box = scrolledtext.ScrolledText(root, state="disabled", height=16)
        self.log_box.pack(fill="both", expand=True, **pad)

        self.refresh_warning()
        self.root.after(100, self.poll_queue)

    # -- helpers --

    def refresh_warning(self):
        if "/blob/" in self.url_var.get():
            self.warn_label.grid()
        else:
            self.warn_label.grid_remove()

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def browse_staff(self):
        path = filedialog.askopenfilename(
            title="Choose staff.json", filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.staff_var.set(path)

    def browse_output(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.out_var.set(path)

    def open_output(self):
        path = self.out_var.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showwarning("Output folder", "The output folder does not exist yet.")
            return
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    # -- generation --

    def start(self):
        if self.running:
            return
        staff_path = self.staff_var.get().strip()
        out_dir = self.out_var.get().strip()
        base_url = self.url_var.get().strip()

        if not staff_path or not os.path.isfile(staff_path):
            messagebox.showerror("Staff file not found", f"No file at:\n{staff_path}")
            return
        if not base_url.lower().startswith(("http://", "https://")):
            messagebox.showerror(
                "Bad URL", "The base card URL must start with http:// or https://"
            )
            return

        self.running = True
        self.gen_btn.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Generating...")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        t = threading.Thread(target=self._worker, args=(staff_path, out_dir, base_url), daemon=True)
        t.start()

    def _worker(self, staff_path, out_dir, base_url):
        try:
            gen, skip, fail = generate_all(
                staff_path, out_dir, base_url,
                log=lambda m: self.msgs.put(("log", m)),
            )
            self.msgs.put(("done", (gen, skip, fail)))
        except Exception as exc:
            self.msgs.put(("error", f"{type(exc).__name__}: {exc}"))

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.msgs.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "done":
                    self.finish(payload)
                elif kind == "error":
                    self.running = False
                    self.gen_btn.configure(state="normal")
                    self.progress.stop()
                    self.status.set("Failed.")
                    self.log("ERROR: " + payload)
                    messagebox.showerror("Generation failed", payload)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def finish(self, result):
        gen, skip, fail = result
        self.running = False
        self.gen_btn.configure(state="normal")
        self.progress.stop()
        self.status.set("Done.")

        lines = [
            f"Generated: {len(gen)}",
            f"Skipped (no employeeId): {len(skip)}",
            f"Failed: {len(fail)}",
        ]
        if skip:
            lines.append("\nSkipped people:\n  - " + "\n  - ".join(skip))
        if fail:
            lines.append("\nFailures:\n  - " + "\n  - ".join(f"{n}: {e}" for n, e in fail))
        summary = "\n".join(lines)
        self.log("\n===== SUMMARY =====\n" + summary)
        messagebox.showinfo("Staff QR Code Generator", summary)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
