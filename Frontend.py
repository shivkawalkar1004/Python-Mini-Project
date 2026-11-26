"""SideQuest - pure Python (tkinter) frontend.

Put this file beside the quiz CSV files and Analysis.py, then run:  python Frontend.py
The Analysis page shows charts for your latest attempt and lets you download them.
"""
import csv, math, random, shutil, subprocess, sys, threading, time, tkinter as tk, zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:  # Pillow ships with matplotlib; it gives sharper chart previews
    from PIL import Image, ImageTk
    RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS
except ImportError:
    Image = None

BASE = Path(__file__).resolve().parent
ANALYSIS_SCRIPT = BASE / "Analysis.py"


def resolve_data_dir():
    candidates = [BASE / "Datasets", BASE / "datasets", BASE / "data", BASE]
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        required = [
            "quiz_easy.csv", "Quiz_Easy.csv",
            "quiz_medium.csv", "Quiz_Medium.csv",
            "quiz_hard.csv", "Quiz_Hard.csv",
            "attempts.csv", "answers.csv",
        ]
        if candidate == BASE or any((candidate / name).exists() for name in required):
            return candidate
    return BASE


def resolve_quiz_file(level):
    candidates = [
        f"quiz_{level}.csv",
        f"Quiz_{level}.csv",
        f"quiz_{level.capitalize()}.csv",
        f"Quiz_{level.capitalize()}.csv",
        f"quiz_{level.title()}.csv",
        f"Quiz_{level.title()}.csv",
    ]
    for directory in (resolve_data_dir(), BASE):
        for name in candidates:
            path = directory / name
            if path.exists():
                return path
    return resolve_data_dir() / candidates[0]


DATA_DIR = resolve_data_dir()
QUESTIONS_PER_ROUND = 10
ATTEMPT_FIELDS = ["timestamp", "player", "difficulty", "score", "total", "percentage", "total_time_sec", "subject"]
ANSWER_FIELDS = ["timestamp", "player", "difficulty", "category", "question", "chosen",
                 "correct_answer", "is_correct", "time_taken_sec"]

PAPER, INK, MUTED = "#f5f6f1", "#182821", "#7b8980"
GREEN, LIME, LINE = "#28634a", "#d6f36a", "#e5e9e1"
WHITE, RED, SOFT = "#ffffff", "#c25e4b", "#edf4eb"
FONT = "Helvetica"


# ---------- data helpers (same CSV formats as the web version) ----------
def category_of(q):
    return (q.get("category") or "General").strip()


def canonical_question(text):
    """Normalize generated lead-ins so copies of the same prompt share one key."""
    text = " ".join((text or "").split())
    prefixes = (
        "Select the correct answer: ",
        "Which option best answers this quiz question? ",
        "Choose the response that correctly completes this question: ",
        "Pick the correct choice for: ",
    )
    for prefix in prefixes:
        if text.casefold().startswith(prefix.casefold()):
            text = text[len(prefix):].strip()
            break
    opening = "A quiz asks, '"
    ending = "' What is the right answer?"
    if text.casefold().startswith(opening.casefold()) and text.casefold().endswith(ending.casefold()):
        text = text[len(opening):-len(ending)].strip()
    return " ".join(text.split()).casefold()


def unique_questions(pool):
    """Keep the first row for each underlying question."""
    seen = set()
    unique = []
    for question in pool:
        key = canonical_question(question.get("question"))
        if key and key not in seen:
            seen.add(key)
            unique.append(question)
    return unique


def subjects_of(pool):
    """Subjects found in the question file, in alphabetical order."""
    return sorted({category_of(q) for q in pool}, key=str.lower)


def append_rows(path, fields, rows):
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerows(rows)


def ensure_subject_column():
    """Older attempts.csv files have no 'subject' column. Add it once, working out each old round's
    subject from answers.csv (one subject -> that subject, several -> Mixed)."""
    path = DATA_DIR / "attempts.csv"
    if not path.exists():
        return
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if "subject" in (reader.fieldnames or []):
                return
        seen = {}
        answers = DATA_DIR / "answers.csv"
        if answers.exists():
            with answers.open(newline="", encoding="utf-8-sig") as f:
                for a in csv.DictReader(f):
                    key = (a.get("timestamp"), a.get("player"))
                    seen.setdefault(key, set()).add((a.get("category") or "General").strip())
        for r in rows:
            cats = seen.get((r.get("timestamp"), r.get("player")), set())
            r["subject"] = next(iter(cats)) if len(cats) == 1 else "Mixed"
        tmp = path.with_name("attempts.csv.tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=ATTEMPT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        tmp.replace(path)
    except (OSError, csv.Error):
        pass


def subjects_for_level(level):
    """Subjects with a leaderboard at this level: those in the question file plus any already played."""
    names = set()
    try:
        with resolve_quiz_file(level).open(newline="", encoding="utf-8-sig") as f:
            names |= {category_of(q) for q in csv.DictReader(f)}
    except (OSError, csv.Error):
        pass
    names |= {r["subject"] for r in read_attempts() if r.get("difficulty", "").strip().lower() == level}
    names.discard("Mixed")
    return sorted(names, key=str.lower)


def read_attempts():
    p = DATA_DIR / "attempts.csv"
    if not p.exists():
        return []
    try:
        with p.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []
    for r in rows:
        r["subject"] = (r.get("subject") or "Mixed").strip() or "Mixed"
    return rows


def stats(difficulty=None, subject=None):
    rows = read_attempts()
    for r in rows:
        try:
            r["percentage"] = float(r.get("percentage", 0))
            r["total_time_sec"] = float(r.get("total_time_sec", 0))
        except ValueError:
            r["percentage"] = 0
            r["total_time_sec"] = 0
    if difficulty:
        rows = [r for r in rows if r.get("difficulty", "").lower() == difficulty]
    if subject:
        rows = [r for r in rows if r["subject"].lower() == subject.lower()]
    order = {"hard": 0, "medium": 1, "easy": 2}
    rows.sort(key=lambda r: (-r["percentage"], order.get(r.get("difficulty", "").lower(), 3), r["total_time_sec"]))
    return {
        "attempts": len(rows),
        "players": len(set(r.get("player", "") for r in rows)),
        "average": round(sum(r["percentage"] for r in rows) / len(rows), 1) if rows else 0,
        "leaders": rows[:20],
    }


# ---------- small UI helpers ----------
def button(parent, text, command, bg=LIME, fg=INK, hover=None, font=(FONT, 11, "bold"), padx=18, pady=10, **kw):
    """Label-based button: looks the same on Windows, macOS and Linux."""
    hover = hover or bg
    b = tk.Label(parent, text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady, cursor="hand2", **kw)
    b.bind("<Enter>", lambda e: b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    b.bind("<Button-1>", lambda e: command())
    return b


def card(parent, **kw):
    return tk.Frame(parent, bg=WHITE, highlightbackground=LINE, highlightthickness=1, padx=24, pady=22, **kw)


def tile(parent, title, subtitle, command, bg=WHITE, fg=INK, sub=MUTED, hover=SOFT, border=LINE):
    """A big clickable card (frame + two labels that all react to the mouse)."""
    f = tk.Frame(parent, bg=bg, highlightbackground=border, highlightthickness=1, padx=22, pady=20, cursor="hand2")
    t = tk.Label(f, text=title, bg=bg, fg=fg, font=(FONT, 15, "bold"), anchor="w", cursor="hand2")
    t.pack(anchor="w")
    s = tk.Label(f, text=subtitle, bg=bg, fg=sub, font=(FONT, 10), anchor="w", cursor="hand2")
    s.pack(anchor="w", pady=(5, 0))
    parts = (f, t, s)
    for w in parts:
        w.bind("<Button-1>", lambda e: command())
        w.bind("<Enter>", lambda e: [x.config(bg=hover) for x in parts])
        w.bind("<Leave>", lambda e: [x.config(bg=bg) for x in parts])
    return f


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SideQuest")
        self.geometry("1000x700")
        self.minsize(780, 600)
        self.configure(bg=PAPER)
        self.level = "easy"
        self.subject = None      # None means a mixed round
        self.pool = []
        self.subjects = []
        self.current = "home"
        self.locked = False
        self.nav = {}
        ensure_subject_column()

        shell = tk.Frame(self, bg=PAPER, padx=30, pady=22)
        shell.pack(fill="both", expand=True)

        top = tk.Frame(shell, bg=PAPER)
        top.pack(fill="x", pady=(0, 28))
        tk.Label(top, text="S", bg=GREEN, fg=LIME, font=(FONT, 16, "bold"), width=2, height=1).pack(side="left")
        tk.Label(top, text=" SideQuest", bg=PAPER, fg=INK, font=(FONT, 17, "bold")).pack(side="left")
        for key, text, cmd in [("exit", "Exit", self.exit_app), ("reset", "Reset", self.reset_data),
                               ("analysis", "Analysis", lambda: self.go("analysis")),
                               ("leaderboard", "Leaderboard", lambda: self.go("leaderboard")),
                               ("home", "Home", lambda: self.go("home"))]:
            b = button(top, text, cmd, bg=PAPER, fg=MUTED, hover="#e9ede6", font=(FONT, 10, "bold"), padx=12, pady=8)
            b.pack(side="right")
            self.nav[key] = b

        self.body = tk.Frame(shell, bg=PAPER)
        self.body.pack(fill="both", expand=True)
        self.go("home")

    # ---------- navigation ----------
    def go(self, page):
        self.current = page
        for w in self.body.winfo_children():
            w.destroy()
        for key, b in self.nav.items():
            active = key == page
            base = "#e9ede6" if active else PAPER
            b.config(bg=base, fg=INK if active else MUTED)
            if key in ("home", "leaderboard", "analysis"):
                b.bind("<Leave>", lambda e, b=b, base=base: b.config(bg=base))
        getattr(self, f"page_{page}")()

    def notice(self, text):
        t = tk.Label(self, text=text, bg=INK, fg="white", font=(FONT, 10), padx=16, pady=10)
        t.place(relx=0.5, rely=0.97, anchor="s")
        self.after(2600, t.destroy)

    def exit_app(self):
        if messagebox.askyesno("SideQuest", "Close SideQuest?"):
            self.destroy()

    def reset_data(self):
        if not messagebox.askyesno("SideQuest", "Delete all saved quiz attempts and answers? This cannot be undone."):
            return
        for name in ("attempts.csv", "answers.csv"):
            p = DATA_DIR / name
            if p.exists():
                p.unlink()
        self.notice("Saved results have been reset.")
        if self.current in ("home", "leaderboard"):
            self.go(self.current)

    # ---------- home ----------
    def page_home(self):
        self.body.columnconfigure(0, weight=6, uniform="c")
        self.body.columnconfigure(1, weight=4, uniform="c")
        self.body.rowconfigure(0, weight=3)
        self.body.rowconfigure(1, weight=2)

        hero = tk.Frame(self.body, bg=GREEN, padx=40, pady=36)
        hero.grid(row=0, column=0, sticky="nsew", padx=(0, 11), pady=(0, 22))
        tk.Label(hero, text="A LITTLE BRAIN WORKOUT", bg=GREEN, fg="#b6d4bd", font=(FONT, 9, "bold")).pack(anchor="w")
        tk.Label(hero, text="Knowledge looks good on you.", bg=GREEN, fg="white", font=(FONT, 30, "bold"),
                 wraplength=380, justify="left").pack(anchor="w", pady=(18, 12))
        tk.Label(hero, text="Pick a level, trust your first thought, and see where curiosity takes you.",
                 bg=GREEN, fg="#d2e0d6", font=(FONT, 11), wraplength=360, justify="left").pack(anchor="w")

        start = card(self.body)
        start.grid(row=0, column=1, sticky="nsew", padx=(11, 0), pady=(0, 22))
        tk.Label(start, text="Ready when you are.", bg=WHITE, fg=INK, font=(FONT, 16, "bold")).pack(anchor="w")
        tk.Label(start, text="10 questions · one satisfying score", bg=WHITE, fg=MUTED, font=(FONT, 10)).pack(anchor="w", pady=(2, 8))
        tk.Label(start, text="Your name", bg=WHITE, fg=INK, font=(FONT, 9, "bold")).pack(anchor="w", pady=(8, 4))
        self.name_entry = tk.Entry(start, font=(FONT, 12), relief="flat", highlightthickness=1,
                                   highlightbackground=LINE, highlightcolor=GREEN)
        self.name_entry.pack(fill="x", ipady=7)
        if getattr(self, "player", None):
            self.name_entry.insert(0, self.player)
        tk.Label(start, text="Choose your level", bg=WHITE, fg=INK, font=(FONT, 9, "bold")).pack(anchor="w", pady=(14, 4))
        row = tk.Frame(start, bg=WHITE)
        row.pack(fill="x")
        self.level_btns = {}
        for i, (key, text) in enumerate([("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")]):
            row.columnconfigure(i, weight=1, uniform="lv")
            lb = tk.Label(row, text=text, font=(FONT, 10, "bold"), pady=10, cursor="hand2",
                          highlightthickness=1)
            lb.grid(row=0, column=i, sticky="ew", padx=3)
            lb.bind("<Button-1>", lambda e, k=key: self.set_level(k))
            self.level_btns[key] = lb
        self.set_level(self.level)
        button(start, "Choose a subject  →", self.start_quiz, hover="#c9e85c").pack(fill="x", pady=(18, 0))
        self.name_entry.bind("<Return>", lambda e: self.start_quiz())

        s = stats()
        left = card(self.body)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 11))
        tk.Label(left, text="Your quiz room", bg=WHITE, fg=INK, font=(FONT, 14, "bold")).pack(anchor="w")
        nums = tk.Frame(left, bg=WHITE)
        nums.pack(anchor="w", pady=(16, 0))
        for value, caption in [(s["attempts"], "Attempts"), (s["players"], "Players"), (f"{s['average']}%", "Average score")]:
            box = tk.Frame(nums, bg=WHITE)
            box.pack(side="left", padx=(0, 30))
            tk.Label(box, text=str(value), bg=WHITE, fg=INK, font=(FONT, 22, "bold")).pack(anchor="w")
            tk.Label(box, text=caption, bg=WHITE, fg=MUTED, font=(FONT, 9)).pack(anchor="w")

        right = card(self.body)
        right.grid(row=1, column=1, sticky="nsew", padx=(11, 0))
        head = tk.Frame(right, bg=WHITE)
        head.pack(fill="x")
        tk.Label(head, text="Top scores", bg=WHITE, fg=INK, font=(FONT, 14, "bold")).pack(side="left")
        button(head, "View all →", lambda: self.go("leaderboard"), bg=WHITE, fg=GREEN, hover=SOFT,
               font=(FONT, 9, "bold"), padx=8, pady=3).pack(side="right")
        if not s["leaders"]:
            tk.Label(right, text="No scores yet. Yours could be first.", bg=WHITE, fg=MUTED,
                     font=(FONT, 10)).pack(anchor="w", pady=14)
        for i, r in enumerate(s["leaders"][:3], 1):
            line = tk.Frame(right, bg=WHITE)
            line.pack(fill="x", pady=4)
            tk.Label(line, text=f"{i}.  {r['player']}  · {r['difficulty']}", bg=WHITE, fg=INK,
                     font=(FONT, 10)).pack(side="left")
            tk.Label(line, text=f"{r['percentage']}%", bg=WHITE, fg=GREEN, font=(FONT, 10, "bold")).pack(side="right")

    def set_level(self, key):
        self.level = key
        for k, lb in self.level_btns.items():
            if k == key:
                lb.config(bg=SOFT, fg=GREEN, highlightbackground="#82a992")
            else:
                lb.config(bg=WHITE, fg=MUTED, highlightbackground=LINE)

    # ---------- quiz ----------
    def start_quiz(self):
        player = self.name_entry.get().strip()[:40]
        if not player:
            self.notice("Please enter your name to start.")
            self.name_entry.focus_set()
            return
        path = resolve_quiz_file(self.level)
        if not path.exists():
            messagebox.showerror("SideQuest", f"Missing {path.name}. Put the quiz CSV files in {DATA_DIR} or beside this app.")
            return
        try:
            with path.open(newline="", encoding="utf-8-sig") as f:
                pool = unique_questions(list(csv.DictReader(f)))
        except (OSError, csv.Error) as e:
            messagebox.showerror("SideQuest", f"Could not read {path.name}: {e}")
            return
        if not pool:
            messagebox.showerror("SideQuest", f"{path.name} has no questions.")
            return
        needed = {"question", "answer", "option_a", "option_b", "option_c", "option_d"}
        if not needed.issubset(pool[0].keys()):
            messagebox.showerror("SideQuest", f"{path.name} needs these columns: {', '.join(sorted(needed))}")
            return
        self.player = player
        self.pool = pool
        self.subjects = subjects_of(pool)
        if len(self.subjects) <= 1:      # nothing to choose between
            self.begin_round(None)
        else:
            self.go("subjects")

    # ---------- subject picker (shown after the level is chosen) ----------
    def page_subjects(self):
        c = card(self.body)
        c.pack(fill="both", expand=True)
        head = tk.Frame(c, bg=WHITE)
        head.pack(fill="x")
        left = tk.Frame(head, bg=WHITE)
        left.pack(side="left")
        tk.Label(left, text="Choose your subject", bg=WHITE, fg=INK, font=(FONT, 19, "bold")).pack(anchor="w")
        tk.Label(left, text=f"{self.level.title()} level  ·  pick one topic or take a mixed round", bg=WHITE,
                 fg=MUTED, font=(FONT, 10)).pack(anchor="w", pady=(3, 0))
        button(head, "←  Back", lambda: self.go("home"), bg=WHITE, hover=SOFT, highlightthickness=1,
               highlightbackground=LINE, font=(FONT, 10, "bold"), padx=14, pady=8).pack(side="right")

        grid = tk.Frame(c, bg=WHITE)
        grid.pack(fill="both", expand=True, pady=(22, 0))
        grid.columnconfigure(0, weight=1, uniform="subj")
        grid.columnconfigure(1, weight=1, uniform="subj")

        tile(grid, "Mixed", f"{min(QUESTIONS_PER_ROUND, len(self.pool))} questions from every subject",
             lambda: self.begin_round(None), bg=GREEN, fg="white", sub="#d2e0d6", hover="#2f7355",
             border=GREEN).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        for i, subject in enumerate(self.subjects):
            have = sum(1 for q in self.pool if category_of(q) == subject)
            note = (f"{QUESTIONS_PER_ROUND} questions" if have >= QUESTIONS_PER_ROUND
                    else f"{have} questions (all there are)")
            tile(grid, subject, note, lambda s=subject: self.begin_round(s)).grid(
                row=1 + i // 2, column=i % 2, sticky="ew",
                padx=(0, 6) if i % 2 == 0 else (6, 0), pady=6)

    def begin_round(self, subject):
        pool = self.pool if subject is None else [q for q in self.pool if category_of(q) == subject]
        pool = unique_questions(pool)
        if not pool:
            messagebox.showerror("SideQuest", "No unique questions are available for this level and subject.")
            return
        self.subject = subject
        self.questions = random.sample(pool, min(QUESTIONS_PER_ROUND, len(pool)))
        self.idx = 0
        self.records = []
        self.began = time.time()
        self.show_question()

    def show_question(self):
        for w in self.body.winfo_children():
            w.destroy()
        for b in self.nav.values():
            pass
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=0)
        self.body.rowconfigure(1, weight=0)
        q = self.questions[self.idx]
        total, n = len(self.questions), self.idx + 1
        self.locked = False
        self.q_started = time.time()

        wrap = tk.Frame(self.body, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=70)

        meta = tk.Frame(wrap, bg=PAPER)
        meta.pack(fill="x")
        tk.Label(meta, text=f"{self.level.upper()}  ·  {q.get('category', 'General')}", bg=PAPER, fg=MUTED,
                 font=(FONT, 9, "bold")).pack(side="left")
        tk.Label(meta, text=f"{n} / {total}", bg=PAPER, fg=MUTED, font=(FONT, 9, "bold")).pack(side="right")

        track = tk.Frame(wrap, bg=LINE, height=6)
        track.pack(fill="x", pady=(10, 20))
        track.pack_propagate(False)
        self.bar = tk.Frame(track, bg=GREEN)
        self.bar.place(relx=0, rely=0, relheight=1, relwidth=(n - 1) / total)

        c = card(wrap)
        c.config(padx=34, pady=30)
        c.pack(fill="x")
        tk.Label(c, text=f"QUESTION {n:02d}", bg=WHITE, fg=MUTED, font=(FONT, 9, "bold")).pack(anchor="w")
        tk.Label(c, text=q["question"], bg=WHITE, fg=INK, font=(FONT, 20, "bold"), wraplength=700,
                 justify="left").pack(anchor="w", pady=(14, 20))

        self.choice_btns = []
        for i, letter in enumerate("ABCD"):
            b = button(c, f"  {letter}    {q[f'option_{letter.lower()}']}", lambda i=i: self.answer(i), bg=WHITE,
                       fg=INK, hover="#f9fbf7", font=(FONT, 11), anchor="w", justify="left", wraplength=680,
                       padx=14, pady=12, highlightthickness=1, highlightbackground=LINE)
            b.pack(fill="x", pady=5)
            self.choice_btns.append(b)

        self.feedback = tk.Label(c, text="", bg=WHITE, font=(FONT, 11, "bold"))
        self.feedback.pack(anchor="w", pady=(12, 0))
        self.next_slot = tk.Frame(c, bg=WHITE)
        self.next_slot.pack(fill="x")

    def answer(self, i):
        if self.locked:
            return
        self.locked = True
        q = self.questions[self.idx]
        chosen = q[f"option_{'abcd'[i]}"]
        correct = chosen == q["answer"]
        correct_i = next((k for k, x in enumerate("abcd") if q[f"option_{x}"] == q["answer"]), 0)
        self.records.append({
            "category": q.get("category", "General"), "question": q["question"], "chosen": chosen,
            "correct_answer": q["answer"], "is_correct": int(correct),
            "time_taken_sec": round(max(0.1, time.time() - self.q_started), 2),
        })
        for b in self.choice_btns:
            b.unbind("<Enter>")
            b.unbind("<Leave>")
            b.config(cursor="arrow")
        good = dict(bg="#eff8f0", highlightbackground="#56a072")
        bad = dict(bg="#fff3f0", highlightbackground="#d99081")
        self.choice_btns[i].config(**(good if correct else bad))
        if not correct:
            self.choice_btns[correct_i].config(**good)
        if correct:
            self.feedback.config(text="Correct. Nicely done.", fg=GREEN)
        else:
            self.feedback.config(text=f"The answer was {q['answer']}.", fg=RED)
        total = len(self.questions)
        self.bar.place_configure(relwidth=(self.idx + 1) / total)
        label = "See your score" if self.idx == total - 1 else "Next question"
        button(self.next_slot, f"{label}  →", self.next_question, hover="#c9e85c").pack(side="right", pady=(14, 0))

    def next_question(self):
        self.idx += 1
        if self.idx < len(self.questions):
            self.show_question()
        else:
            self.finish()

    def finish(self):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        total = len(self.records)
        score = sum(r["is_correct"] for r in self.records)
        pct = round(100 * score / total, 1)
        elapsed = round(time.time() - self.began, 1)
        try:
            ensure_subject_column()
            append_rows(DATA_DIR / "answers.csv", ANSWER_FIELDS,
                        [{"timestamp": stamp, "player": self.player, "difficulty": self.level, **r} for r in self.records])
            append_rows(DATA_DIR / "attempts.csv", ATTEMPT_FIELDS,
                        [{"timestamp": stamp, "player": self.player, "difficulty": self.level, "score": score,
                          "total": total, "percentage": pct, "total_time_sec": elapsed,
                          "subject": self.subject or "Mixed"}])
        except OSError as e:
            messagebox.showerror("SideQuest", f"Could not save your results: {e}")

        for w in self.body.winfo_children():
            w.destroy()
        c = card(self.body)
        c.pack(pady=30, ipadx=40, ipady=20)
        tk.Label(c, text=f"ROUND COMPLETE · {self.level.upper()} · {(self.subject or 'Mixed').upper()}", bg=SOFT, fg=GREEN, font=(FONT, 9, "bold"),
                 padx=10, pady=5).pack()
        tk.Label(c, text=f"{pct}%", bg=WHITE, fg=GREEN, font=(FONT, 60, "bold")).pack(pady=(14, 6))
        tk.Label(c, text=f"{self.player}, nicely played.", bg=WHITE, fg=INK, font=(FONT, 16, "bold")).pack()
        tk.Label(c, text=f"You got {score} out of {total} right in {elapsed} seconds.", bg=WHITE, fg=MUTED,
                 font=(FONT, 11)).pack(pady=(6, 18))
        row = tk.Frame(c, bg=WHITE)
        row.pack()
        button(row, "Back to home", lambda: self.go("home"), hover="#c9e85c").pack(side="left", padx=5)
        button(row, "See my charts", lambda: self.go("analysis"), bg=WHITE, hover=SOFT,
               highlightthickness=1, highlightbackground=LINE).pack(side="left", padx=5)
        button(row, "Leaderboard", lambda: self.go("leaderboard"), bg=WHITE, hover=SOFT,
               highlightthickness=1, highlightbackground=LINE).pack(side="left", padx=5)

    # ---------- leaderboard (one board for every difficulty + subject) ----------
    def page_leaderboard(self):
        c = card(self.body)
        c.pack(fill="both", expand=True)

        header = tk.Frame(c, bg=WHITE)
        header.pack(fill="x", pady=(0, 16))
        title = tk.Frame(header, bg=WHITE)
        title.pack(side="left")
        tk.Label(title, text="Leaderboard", bg=WHITE, fg=INK, font=(FONT, 19, "bold")).pack(anchor="w")
        tk.Label(title, text="Pick a difficulty, then a subject. Each combination has its own board.", bg=WHITE,
                 fg=MUTED, font=(FONT, 10)).pack(anchor="w", pady=(3, 0))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Leaderboard.TNotebook", background=WHITE, borderwidth=0)
        style.configure("Leaderboard.TNotebook.Tab", font=(FONT, 9, "bold"), padding=(16, 9))
        style.map("Leaderboard.TNotebook.Tab",
                  background=[("selected", GREEN), ("!selected", "#f5f6f1")],
                  foreground=[("selected", WHITE), ("!selected", MUTED)])
        style.configure("Leaderboard.Treeview", rowheight=32, font=(FONT, 10), background=WHITE,
                        fieldbackground=WHITE, foreground=INK, borderwidth=0)
        style.configure("Leaderboard.Treeview.Heading", font=(FONT, 9, "bold"), background="#f5f6f1",
                        foreground=MUTED, relief="flat", padding=(10, 8))
        style.map("Leaderboard.Treeview", background=[("selected", SOFT)], foreground=[("selected", INK)])

        notebook = ttk.Notebook(c, style="Leaderboard.TNotebook")
        notebook.pack(fill="both", expand=True)
        levels = (("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard"))
        for difficulty, tab_title in levels:
            view = tk.Frame(notebook, bg=WHITE, padx=4, pady=12)
            notebook.add(view, text=tab_title)
            self.build_level_boards(view, difficulty)
        notebook.select([d for d, _ in levels].index(self.level) if self.level in dict(levels) else 0)

    def build_level_boards(self, view, difficulty):
        """Subject chips (Mixed + each subject) with the chosen subject's board underneath."""
        subjects = ["Mixed"] + subjects_for_level(difficulty)
        start = self.subject if (difficulty == self.level and self.subject in subjects) else "Mixed"
        chips = tk.Frame(view, bg=WHITE)
        chips.pack(fill="x", pady=(0, 14))
        content = tk.Frame(view, bg=WHITE)
        content.pack(fill="both", expand=True)
        labels = {}

        def select(name):
            for key, lb in labels.items():
                if key == name:
                    lb.config(bg=GREEN, fg=WHITE, highlightbackground=GREEN)
                else:
                    lb.config(bg=WHITE, fg=MUTED, highlightbackground=LINE)
            self.render_board(content, difficulty, name)

        for name in subjects:
            lb = tk.Label(chips, text=name, font=(FONT, 10, "bold"), padx=14, pady=8,
                          cursor="hand2", highlightthickness=1)
            lb.pack(side="left", padx=(0, 8))
            lb.bind("<Button-1>", lambda e, n=name: select(n))
            labels[name] = lb
        select(start)

    def render_board(self, view, difficulty, subject):
        for w in view.winfo_children():
            w.destroy()
        leaders = stats(difficulty, subject)["leaders"]
        label = subject
        tk.Label(view, text=f"{difficulty.upper()}  ·  {label.upper()}  ·  TOP {len(leaders)} SCORES", bg=WHITE,
                 fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="e", pady=(0, 8))

        if not leaders:
            empty = tk.Frame(view, bg=SOFT, padx=24, pady=28)
            empty.pack(fill="x", pady=(8, 0))
            tk.Label(empty, text=f"No {difficulty.title()} {label} runs yet.", bg=SOFT, fg=GREEN,
                     font=(FONT, 14, "bold")).pack(anchor="w")
            tk.Label(empty, text="Play a round with this level and subject to claim the first spot.",
                     bg=SOFT, fg=MUTED, font=(FONT, 10)).pack(anchor="w", pady=(5, 0))
            return

        podium = tk.Frame(view, bg=WHITE)
        podium.pack(fill="x", pady=(0, 18))
        for column in range(3):
            podium.columnconfigure(column, weight=1, uniform="podium")
        podium_colors = [
            (GREEN, WHITE, LIME, GREEN),
            ("#f5f6f1", INK, GREEN, LINE),
            (SOFT, INK, GREEN, "#dbe8dc"),
        ]
        for i, (r, colors) in enumerate(zip(leaders[:3], podium_colors)):
            bg, fg, accent, border = colors
            slot = tk.Frame(podium, bg=bg, highlightbackground=border, highlightthickness=1, padx=16, pady=14)
            slot.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            tk.Label(slot, text=f"#{i + 1}  TOP SCORE" if i == 0 else f"#{i + 1}",
                     bg=bg, fg=accent, font=(FONT, 9, "bold")).pack(anchor="w")
            tk.Label(slot, text=r["player"], bg=bg, fg=fg, font=(FONT, 13, "bold"),
                     anchor="w", justify="left", wraplength=220).pack(anchor="w", pady=(8, 2))
            tk.Label(slot, text=f"{str(r['difficulty']).title()} · {label}", bg=bg, fg=accent,
                     font=(FONT, 9, "bold")).pack(anchor="w")
            score = tk.Frame(slot, bg=bg)
            score.pack(fill="x", pady=(8, 0))
            tk.Label(score, text=f"{r['percentage']:g}%", bg=bg, fg=fg,
                     font=(FONT, 22, "bold")).pack(side="left")
            tk.Label(score, text=f"{r['total_time_sec']:g}s", bg=bg, fg=accent,
                     font=(FONT, 10, "bold")).pack(side="right", pady=(7, 0))

        if len(leaders) > 3:
            list_header = tk.Frame(view, bg=WHITE)
            list_header.pack(fill="x", pady=(0, 8))
            tk.Label(list_header, text="More great runs", bg=WHITE, fg=INK,
                     font=(FONT, 12, "bold")).pack(side="left")
            tk.Label(list_header, text="RANKED BY SCORE", bg=WHITE, fg=MUTED,
                     font=(FONT, 8, "bold")).pack(side="right")

            table = tk.Frame(view, bg=WHITE)
            table.pack(fill="both", expand=True)
            tree = ttk.Treeview(table, columns=("rank", "player", "date", "score", "time"),
                                show="headings", selectmode="none", style="Leaderboard.Treeview")
            for col, text, width, anchor in (
                ("rank", "RANK", 70, "center"), ("player", "PLAYER", 260, "w"),
                ("date", "DATE", 120, "center"), ("score", "SCORE", 110, "center"),
                ("time", "TIME", 110, "center"),
            ):
                tree.heading(col, text=text, anchor=anchor)
                tree.column(col, width=width, anchor=anchor)
            tree.tag_configure("odd", background="#f8faf7")
            tree.tag_configure("even", background=WHITE)
            for i, r in enumerate(leaders[3:], 4):
                tree.insert("", "end", values=(i, r["player"], str(r.get("timestamp", ""))[:10],
                                               f"{r['percentage']}%", f"{r['total_time_sec']}s"),
                            tags=("odd" if i % 2 else "even",))
            scrollbar = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=scrollbar.set)
            tree.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

    # ---------- analysis (latest attempt) ----------
    def page_analysis(self):
        c = card(self.body)
        c.pack(fill="both", expand=True)
        head = tk.Frame(c, bg=WHITE)
        head.pack(fill="x")
        left = tk.Frame(head, bg=WHITE)
        left.pack(side="left")
        tk.Label(left, text="Your latest attempt", bg=WHITE, fg=INK, font=(FONT, 16, "bold")).pack(anchor="w")
        self.chart_sub = tk.Label(left, text="Charts for your most recent quiz round.", bg=WHITE, fg=MUTED,
                                  font=(FONT, 10))
        self.chart_sub.pack(anchor="w", pady=(2, 0))
        self.save_row = tk.Frame(head, bg=WHITE)
        self.save_row.pack(side="right")
        self.chart_area = tk.Frame(c, bg=WHITE)
        self.chart_area.pack(fill="both", expand=True, pady=(14, 0))
        self.chart_files = []
        self.run_analysis()

    def chart_message(self, text):
        for w in self.chart_area.winfo_children():
            w.destroy()
        tk.Label(self.chart_area, text=text, bg=WHITE, fg=MUTED, font=(FONT, 10), wraplength=700,
                 justify="left").pack(pady=30)

    def run_analysis(self):
        script = ANALYSIS_SCRIPT if ANALYSIS_SCRIPT.is_file() else None
        if script is None:
            self.chart_message("No analysis script was found beside this file.")
            return
        self.chart_message("Building your charts...")
        cmd = [sys.executable, str(script)]
        if getattr(self, "player", None):
            cmd += ["--player", self.player]
        result = {}

        def work():
            result["p"] = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True)

        threading.Thread(target=work, daemon=True).start()

        def poll():
            if self.current != "analysis":
                return
            if "p" not in result:
                self.after(150, poll)
                return
            p = result["p"]
            if p.returncode:
                self.chart_message((p.stderr or p.stdout or "Analysis failed.").strip()[-1200:])
                return
            for line in p.stdout.splitlines():
                if line.startswith("Latest attempt:"):
                    self.chart_sub.config(text=line.replace("Latest attempt:", "").strip())
            folder = BASE / "charts"
            self.show_charts(sorted(folder.glob("*.png")) if folder.exists() else [])

        poll()

    def show_charts(self, files):
        if not files:
            self.chart_message("No charts were created.")
            return
        for w in self.chart_area.winfo_children():
            w.destroy()
        for w in self.save_row.winfo_children():
            w.destroy()
        self.chart_files, self.chart_i = files, 0
        outline = dict(bg=WHITE, hover=SOFT, highlightthickness=1, highlightbackground=LINE,
                       font=(FONT, 10, "bold"), padx=14, pady=8)
        button(self.save_row, "Save this chart", self.save_current_chart, **outline).pack(side="left", padx=(0, 8))
        button(self.save_row, "Download all (.zip)", self.download_all, hover="#c9e85c",
               font=(FONT, 10, "bold"), padx=14, pady=8).pack(side="left")

        row = tk.Frame(self.chart_area, bg=WHITE)
        row.pack(fill="both", expand=True)
        arrow = dict(bg=WHITE, fg=GREEN, hover=SOFT, font=(FONT, 20, "bold"), padx=12, pady=6)
        button(row, "<", lambda: self.step_chart(-1), **arrow).pack(side="left")
        button(row, ">", lambda: self.step_chart(1), **arrow).pack(side="right")
        self.chart_img = tk.Label(row, bg=WHITE)
        self.chart_img.pack(side="left", expand=True, fill="both")
        self.chart_count = tk.Label(self.chart_area, bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.chart_count.pack(pady=(8, 0))
        self.update_idletasks()
        self.step_chart(0)

    def step_chart(self, d):
        self.chart_i = (self.chart_i + d) % len(self.chart_files)
        f = self.chart_files[self.chart_i]
        max_w = max(300, self.winfo_width() - 240)
        max_h = max(220, self.winfo_height() - 300)
        try:
            if Image:
                im = Image.open(f)
                scale = min(max_w / im.width, max_h / im.height, 1)
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), RESAMPLE)
                img = ImageTk.PhotoImage(im)
            else:
                img = tk.PhotoImage(file=str(f))
                factor = max(math.ceil(img.width() / max_w), math.ceil(img.height() / max_h), 1)
                if factor > 1:
                    img = img.subsample(factor)
        except (tk.TclError, OSError):
            self.chart_img.config(image="", text=f"Could not open {f.name}")
            return
        self._photo = img  # keep a reference so it isn't garbage-collected
        self.chart_img.config(image=img, text="")
        name = f.stem.split("_", 1)[-1].replace("_", " ").capitalize()
        self.chart_count.config(text=f"{name}   |   {self.chart_i + 1} of {len(self.chart_files)}")

    def save_current_chart(self):
        f = self.chart_files[self.chart_i]
        dest = filedialog.asksaveasfilename(parent=self, title="Save chart", defaultextension=".png",
                                            initialfile=f.name, filetypes=[("PNG image", "*.png")])
        if not dest:
            return
        try:
            shutil.copyfile(f, dest)
            self.notice("Chart saved.")
        except OSError as e:
            messagebox.showerror("SideQuest", f"Could not save the chart: {e}")

    def download_all(self):
        player = getattr(self, "player", None)
        if not player:
            attempts = read_attempts()
            if attempts:
                player = max(enumerate(attempts),
                             key=lambda item: (item[1].get("timestamp", ""), item[0]))[1].get("player")
        player = (player or "user").strip()
        safe_player = "".join(
            "_" if char in '<>:"/\\|?*' or ord(char) < 32 else char
            for char in player
        ).strip(" .")[:80] or "user"
        initial_file = f"{safe_player}_quiz_analysis.zip"
        dest = filedialog.asksaveasfilename(parent=self, title="Download all charts", defaultextension=".zip",
                                            initialfile=initial_file, filetypes=[("ZIP file", "*.zip")])
        if not dest:
            return
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                for f in self.chart_files:
                    z.write(f, f.name)
            self.notice(f"Saved {len(self.chart_files)} charts.")
        except OSError as e:
            messagebox.showerror("SideQuest", f"Could not create the zip: {e}")


if __name__ == "__main__":
    App().mainloop()
