"""HWP Make Basic: native Windows launcher, also the frozen worker entry point."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid

from app.desktop_convert import SUPPORTED, validate_source, worker

VERSION = "1.0.0"


class BasicApp:
    def __init__(self, root: tk.Tk, data_dir: Path | None = None):
        self.root = root
        self.data = data_dir or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HWP Make Basic"
        self.data.mkdir(parents=True, exist_ok=True)
        self.process = None
        self.log = None
        self.job = None
        self.source = None
        self.output = None
        self.started = 0.0
        self.history = self.load_history()
        root.title("HWP Make · 기본 변환")
        root.geometry("700x680")
        root.minsize(620, 600)
        root.configure(bg="#f4f5fa")
        root.protocol("WM_DELETE_WINDOW", self.close)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent / "packaging")) / "app.ico"
        if icon.is_file():
            root.iconbitmap(str(icon))
        root.option_add("*Font", ("맑은 고딕", 10))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f5fa")
        style.configure("TLabel", background="#f4f5fa", foreground="#202539")
        style.configure("Title.TLabel", font=("맑은 고딕", 23, "bold"))
        style.configure("Muted.TLabel", foreground="#626b80")
        style.configure("TButton", padding=(15, 9))
        style.configure("Primary.TButton", background="#505ac9", foreground="white", padding=(18, 12))
        style.map("Primary.TButton", background=[("active", "#424bb3"), ("disabled", "#dce0eb")],
                  foreground=[("disabled", "#737b90")])
        body = ttk.Frame(root, padding=28)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="HWP MAKE   /   BASIC", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(body, text="파일을 문서로 변환", style="Title.TLabel").pack(anchor="w", pady=(16, 5))
        ttk.Label(body, text="파일을 선택하고 저장할 형식을 고르세요.", style="Muted.TLabel").pack(anchor="w")
        self.file_text = tk.StringVar(value="선택한 파일이 없습니다.")
        self.pick = ttk.Button(body, text="파일 선택", command=self.choose)
        self.pick.pack(fill="x", pady=(22, 8))
        ttk.Label(body, textvariable=self.file_text, wraplength=585).pack(anchor="w")
        ttk.Label(body, text="PDF · HWP · HWPX · DOCX · TXT · 이미지  /  최대 64MB", style="Muted.TLabel").pack(anchor="w", pady=(5, 15))
        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Label(row, text="저장 형식").pack(side="left", padx=(0, 12))
        self.format = tk.StringVar(value="HWPX")
        self.formats = ttk.Combobox(row, textvariable=self.format, values=("HWPX", "DOCX"), state="readonly", width=12)
        self.formats.pack(side="left")
        self.formats.bind("<<ComboboxSelected>>", lambda _: self.update_hint())
        self.hint = tk.StringVar()
        ttk.Label(body, textvariable=self.hint, wraplength=585, style="Muted.TLabel").pack(anchor="w", pady=(8, 12))
        self.update_hint()
        self.convert_button = ttk.Button(body, text="변환하고 저장", style="Primary.TButton", command=self.start, state="disabled")
        self.convert_button.pack(fill="x")
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x", pady=(12, 8))
        self.status = tk.StringVar(value="파일을 선택해 주세요.")
        ttk.Label(body, textvariable=self.status, wraplength=585).pack(anchor="w")
        self.review = tk.StringVar(value="로그인·API 키 없이 이 컴퓨터에서 처리합니다.")
        ttk.Label(body, textvariable=self.review, style="Muted.TLabel", wraplength=585).pack(anchor="w", pady=(5, 10))
        actions = ttk.Frame(body)
        actions.pack(fill="x")
        self.open_button = ttk.Button(actions, text="결과 열기", command=self.open_output, state="disabled")
        self.open_button.pack(side="left")
        self.folder_button = ttk.Button(actions, text="저장 폴더", command=self.open_folder, state="disabled")
        self.folder_button.pack(side="left", padx=8)
        ttk.Button(actions, text="도움말", command=self.help).pack(side="right")
        ttk.Label(body, text="최근 변환", font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(18, 7))
        self.recent = tk.Listbox(body, height=3, bd=0, highlightthickness=1, highlightbackground="#dce0eb",
                                 activestyle="none", selectbackground="#e4e7fb", selectforeground="#202539")
        self.recent.pack(fill="both", expand=True)
        self.recent.bind("<<ListboxSelect>>", self.select_recent)
        self.recent.bind("<Double-Button-1>", lambda _: self.open_output())
        self.render_history()
        root.bind("<Control-o>", lambda _: self.choose())
        self.poll_id = root.after(250, self.poll)

    def load_history(self):
        try:
            rows = json.loads((self.data / "history.json").read_text(encoding="utf-8"))
            return [x for x in rows if isinstance(x, dict) and isinstance(x.get("output"), str)][:20]
        except (OSError, ValueError, TypeError):
            return []

    def render_history(self):
        self.recent.delete(0, "end")
        for item in self.history:
            self.recent.insert("end", f"  {Path(item['output']).name}    ·    {item.get('date', '')}")

    def update_hint(self):
        self.hint.set("PDF → HWPX는 원본 전체 페이지 배치를 유지해 변환합니다."
                      if self.format.get() == "HWPX" else "DOCX는 문항 내용 중심으로 다시 구성하며, 원본 배치와 다를 수 있습니다.")

    def choose(self):
        if self.process:
            return
        path = filedialog.askopenfilename(title="변환할 파일 선택", filetypes=[
            ("지원 문서와 이미지", " ".join("*" + x for x in SUPPORTED)), ("모든 파일", "*.*")])
        if path:
            self.set_source(Path(path))

    def set_source(self, source: Path):
        try:
            validate_source(source)
        except (OSError, ValueError) as exc:
            messagebox.showerror("파일 확인", str(exc), parent=self.root)
            return
        self.source = source
        self.output = None
        self.file_text.set(source.name)
        self.status.set("저장 위치를 고르면 변환이 시작됩니다.")
        self.review.set("원본 파일은 그대로 유지됩니다.")
        self.convert_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")

    def start(self):
        if not self.source or self.process:
            return
        ext = "." + self.format.get().lower()
        target = filedialog.asksaveasfilename(title="변환 결과 저장", initialfile=self.source.stem + "_변환" + ext,
                                            defaultextension=ext, filetypes=[(self.format.get(), "*" + ext)])
        if target:
            self.start_to(Path(target))

    def start_to(self, target: Path):
        if self.process or not self.source:
            return
        if target.resolve() == self.source.resolve():
            messagebox.showerror("저장 위치", "원본과 다른 파일명을 선택해 주세요.", parent=self.root)
            return
        self.job = self.data / "jobs" / uuid.uuid4().hex
        self.job.mkdir(parents=True)
        spec = self.job / "spec.json"
        spec.write_text(json.dumps({"source": str(self.source.resolve()), "destination": str(target.resolve())}), encoding="utf-8")
        command = ([sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]) + ["--worker", str(spec)]
        try:
            self.log = (self.job / "worker.log").open("w", encoding="utf-8")
            self.process = subprocess.Popen(command, stdout=self.log, stderr=self.log,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            if self.log:
                self.log.close()
            messagebox.showerror("실행 실패", str(exc), parent=self.root)
            return
        self.started = time.monotonic()
        self.output = None
        for widget in (self.pick, self.formats, self.convert_button, self.open_button, self.folder_button):
            widget.configure(state="disabled")
        self.progress.start(12)
        self.review.set("큰 PDF는 수 분이 걸릴 수 있습니다. 이 창을 닫으면 변환을 중단합니다.")

    def poll(self):
        if self.process:
            code = self.process.poll()
            if code is None:
                self.status.set(f"변환 및 문서 검사 중 · {int(time.monotonic() - self.started)}초")
            else:
                self.process = None
                self.log.close()
                # SQLite/native libraries can retain Windows handles until the
                # child exits. Finish cleanup only after observing that exit.
                import shutil
                engine = (self.job / "engine").resolve()
                if engine.is_relative_to((self.data / "jobs").resolve()) and engine.parent == self.job.resolve():
                    shutil.rmtree(engine, ignore_errors=True)
                self.progress.stop()
                self.pick.configure(state="normal")
                self.formats.configure(state="readonly")
                self.convert_button.configure(state="normal")
                try:
                    result = json.loads((self.job / "result.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    result = {"ok": False, "error": "변환 프로세스가 종료되었습니다. 다른 파일로 다시 시도해 주세요."}
                if result.get("ok"):
                    self.output = Path(result["output"])
                    self.status.set("저장 완료 · " + self.output.name)
                    self.review.set(" · ".join(x for x in [f"전체 {result['pages']}쪽" if result.get("pages") else "",
                                    f"{result['problems']}문항" if result.get("problems") else "",
                                    "수식·그림·배치를 확인해 주세요."] if x))
                    result["date"] = time.strftime("%m/%d %H:%M")
                    self.history = ([result] + [x for x in self.history if x["output"] != result["output"]])[:20]
                    self.render_history()
                    try:
                        temp = self.data / "history.tmp"
                        temp.write_text(json.dumps(self.history, ensure_ascii=False), encoding="utf-8")
                        temp.replace(self.data / "history.json")
                    except OSError:
                        self.review.set("파일은 저장되었습니다. 최근 기록을 저장하지 못했습니다.")
                    self.open_button.configure(state="normal")
                    self.folder_button.configure(state="normal")
                else:
                    self.status.set("변환하지 못했습니다.")
                    self.review.set(result.get("error", "파일을 확인하고 다시 시도해 주세요."))
        self.poll_id = self.root.after(250, self.poll)

    def select_recent(self, _=None):
        if self.process or not self.recent.curselection():
            return
        item = self.history[self.recent.curselection()[0]]
        self.output = Path(item["output"])
        self.open_button.configure(state="normal")
        self.folder_button.configure(state="normal")
        self.status.set(self.output.name)
        self.review.set("\n".join(item.get("warnings", [])[:2]))

    def open_output(self):
        if self.output:
            try:
                os.startfile(self.output)
            except OSError:
                messagebox.showinfo("결과 열기", "파일이 없거나 연결된 프로그램이 없습니다. 저장 폴더에서 확인해 주세요.", parent=self.root)

    def open_folder(self):
        if self.output:
            try:
                os.startfile(self.output.parent)
            except OSError as exc:
                messagebox.showerror("저장 폴더", str(exc), parent=self.root)

    def help(self):
        messagebox.showinfo("HWP Make Basic " + VERSION,
            "1. 파일을 선택합니다.\n2. HWPX 또는 DOCX를 고릅니다.\n3. 변환하고 저장을 누릅니다.\n\n"
            "PDF → HWPX는 전체 원본 배치를 보존하는 경로입니다.\n다른 변환은 내용을 다시 구성해 배치가 달라질 수 있습니다.\n"
            "스캔·이미지는 AI OCR 없이 이미지로 보존될 수 있습니다.\n\n"
            "HWPX는 한글에서, DOCX는 Word 등에서 열어 확인하세요.\n"
            "원본은 수정하지 않으며, 인터넷·로그인·API 키가 필요 없습니다.\n"
            "문항 편집·재배열·자동 번호 설정은 포함하지 않습니다.", parent=self.root)

    def close(self):
        if self.process:
            if not messagebox.askyesno("변환 중단", "변환을 중단하고 앱을 닫을까요?", parent=self.root):
                return
            self.process.terminate()
            self.process.wait(timeout=10)
            self.log.close()
            # Job belongs to this app instance and contains no user destination.
            import shutil
            if self.job.resolve().is_relative_to((self.data / "jobs").resolve()):
                shutil.rmtree(self.job, ignore_errors=True)
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return worker(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from app.desktop_selftest import run
        return run(Path(sys.argv[2]), BasicApp)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    BasicApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
