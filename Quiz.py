"""
SideQuest
---------
A terminal quiz that asks 10 random questions from the level you pick
(easy / medium / hard) and saves every attempt so Analysis.py can chart it.

Files it needs (same folder or Datasets):  quiz_easy.csv, quiz_medium.csv, quiz_hard.csv
Files it creates:                           attempts.csv  (one row per quiz attempt)
                                            answers.csv   (one row per question answered)
"""
import csv
import os
import random
import subprocess
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS_SCRIPT = os.path.join(BASE, "Analysis.py")


def resolve_data_dir():
    candidates = [os.path.join(BASE, "Datasets"), os.path.join(BASE, "datasets"), os.path.join(BASE, "data"), BASE]
    for candidate in candidates:
        if os.path.isdir(candidate):
            required = [
                "quiz_easy.csv", "Quiz_Easy.csv",
                "quiz_medium.csv", "Quiz_Medium.csv",
                "quiz_hard.csv", "Quiz_Hard.csv",
                "attempts.csv", "answers.csv",
            ]
            if candidate == BASE or any(os.path.exists(os.path.join(candidate, name)) for name in required):
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
            path = os.path.join(directory, name)
            if os.path.exists(path):
                return path
    return os.path.join(resolve_data_dir(), candidates[0])


DATA_DIR = resolve_data_dir()
LEVELS = {"1": "easy", "2": "medium", "3": "hard"}
QUESTIONS_PER_ROUND = 10
ATTEMPTS_FILE = os.path.join(DATA_DIR, "attempts.csv")
ANSWERS_FILE = os.path.join(DATA_DIR, "answers.csv")

ATTEMPT_FIELDS = ["timestamp", "player", "difficulty", "score", "total",
                  "percentage", "total_time_sec", "subject"]
ANSWER_FIELDS = ["timestamp", "player", "difficulty", "category", "question",
                 "chosen", "correct_answer", "is_correct", "time_taken_sec"]


def load_questions(level):
    path = resolve_quiz_file(level)
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"question", "answer", "option_a", "option_b", "option_c", "option_d"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{os.path.basename(path)} is missing required columns: {', '.join(sorted(missing))}")
        return unique_questions(list(reader))


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


def pick_subject(level):
    """Ask which subject to play. Returns None for a mixed round."""
    pool = load_questions(level)
    subjects = sorted({category_of(q) for q in pool}, key=str.lower)
    if len(subjects) <= 1:
        return None
    print("\nPick a subject:")
    print("  1) Mixed")
    for i, name in enumerate(subjects, 2):
        print(f"  {i}) {name}")
    choice = ask("Subject: ", {str(n) for n in range(1, len(subjects) + 2)})
    return None if choice == "1" else subjects[int(choice) - 2]


def ensure_subject_column():
    """Older attempts.csv files have no 'subject' column. Add it once, working out each old round's
    subject from answers.csv (one subject -> that subject, several -> Mixed)."""
    if not os.path.exists(ATTEMPTS_FILE):
        return
    try:
        with open(ATTEMPTS_FILE, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if "subject" in (reader.fieldnames or []):
                return
        seen = {}
        if os.path.exists(ANSWERS_FILE):
            with open(ANSWERS_FILE, newline="", encoding="utf-8-sig") as f:
                for a in csv.DictReader(f):
                    key = (a.get("timestamp"), a.get("player"))
                    seen.setdefault(key, set()).add((a.get("category") or "General").strip())
        for r in rows:
            cats = seen.get((r.get("timestamp"), r.get("player")), set())
            r["subject"] = next(iter(cats)) if len(cats) == 1 else "Mixed"
        tmp = ATTEMPTS_FILE + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ATTEMPT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, ATTEMPTS_FILE)
    except (OSError, csv.Error):
        pass


def append_rows(path, fieldnames, rows):
    """Add rows to a CSV, writing the header only if the file is new."""
    is_new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def read_input(prompt, default=""):
    try:
        return input(prompt).strip() or default
    except EOFError:
        print("\nNo input detected. Exiting the quiz.")
        raise SystemExit(0)
    except KeyboardInterrupt:
        print("\nQuiz cancelled.")
        raise SystemExit(0)


def ask(prompt, valid):
    """Keep asking until the player types one of the valid choices."""
    while True:
        value = read_input(prompt).lower()
        if value in valid:
            return value
        print(f"  Please enter one of: {', '.join(sorted(valid))}")


def play_round(player, level, subject=None):
    pool = load_questions(level)
    if subject:
        pool = [q for q in pool if category_of(q) == subject]
    if not pool:
        print("\nNo unique questions are available for this level and subject.")
        return
    print(f"\nSubject: {subject or 'Mixed'}")
    questions = random.sample(pool, min(QUESTIONS_PER_ROUND, len(pool)))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    answer_rows, score = [], 0
    round_start = time.time()

    for n, q in enumerate(questions, 1):
        print(f"\nQ{n}/{len(questions)}  [{category_of(q)}]")
        print(q["question"])
        for letter in "abcd":
            print(f"  {letter.upper()}) {q['option_' + letter]}")

        start = time.time()
        choice = ask("Your answer (A-D): ", set("abcd"))
        taken = round(time.time() - start, 2)

        chosen = q["option_" + choice]
        correct = chosen == q["answer"]
        score += correct
        print("  Correct!" if correct else f"  Wrong. The answer is: {q['answer']}")

        answer_rows.append({
            "timestamp": stamp, "player": player, "difficulty": level,
            "category": category_of(q), "question": q["question"],
            "chosen": chosen, "correct_answer": q["answer"],
            "is_correct": int(correct), "time_taken_sec": taken,
        })

    total = len(questions)
    attempt = {
        "timestamp": stamp, "player": player, "difficulty": level,
        "score": score, "total": total,
        "percentage": round(100 * score / total, 1),
        "total_time_sec": round(time.time() - round_start, 1),
        "subject": subject or "Mixed",
    }
    ensure_subject_column()
    append_rows(ANSWERS_FILE, ANSWER_FIELDS, answer_rows)
    append_rows(ATTEMPTS_FILE, ATTEMPT_FIELDS, [attempt])
    print(f"\n{player}, you scored {score}/{total} ({attempt['percentage']}%) "
          f"on {level.upper()} ({subject or 'Mixed'}) in {attempt['total_time_sec']}s.")


def show_leaderboard(top_n=5):
    if not os.path.exists(ATTEMPTS_FILE):
        print("\nNo attempts yet.")
        return
    ensure_subject_column()
    with open(ATTEMPTS_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print("\nWhich level?  1) Easy   2) Medium   3) Hard")
    level = LEVELS[ask("Level: ", set(LEVELS))]
    at_level = [r for r in rows if r.get("difficulty", "").strip().lower() == level]

    names = {(r.get("subject") or "Mixed").strip() for r in at_level}
    try:
        names |= {category_of(q) for q in load_questions(level)}
    except (OSError, csv.Error):
        pass
    names.discard("Mixed")
    boards = ["Mixed"] + sorted(names, key=str.lower)

    print(f"\n=== {level.upper()} leaderboards ===")
    for board in boards:
        leaders = [r for r in at_level if (r.get("subject") or "Mixed").strip().lower() == board.lower()]
        leaders.sort(key=lambda r: (-float(r["percentage"]), float(r["total_time_sec"])))
        print(f"\n{'MIXED BUNCH' if board == 'Mixed' else board.upper()}")
        if not leaders:
            print("  No scores yet.")
            continue
        print(f"  {'RANK':<5} {'PLAYER':<15} {'SCORE':>7} {'TIME':>8}")
        for i, r in enumerate(leaders[:top_n], 1):
            print(f"  {i:<5} {r['player']:<15} {r['percentage']:>6}% "
                  f"{r['total_time_sec']:>6}s")


def reset_results():
    files = [path for path in (ATTEMPTS_FILE, ANSWERS_FILE)
             if os.path.exists(path)]
    if not files:
        print("\nNo saved results to reset.")
        return

    confirm = ask("Delete all saved attempts and answers? (y/n): ", {"y", "n"})
    if confirm != "y":
        print("Reset cancelled.")
        return

    for path in files:
        os.remove(path)
    print("All attempts and answers have been reset.")


def main():
    analysis_script = ANALYSIS_SCRIPT if os.path.exists(ANALYSIS_SCRIPT) else None
    ensure_subject_column()
    print("=" * 36)
    print("          SideQuest")
    print("=" * 36)
    while True:
        print("\n1) Play   2) Leaderboard   3) Analysis   4) Reset results   5) Quit")
        action = ask("Choose: ", {"1", "2", "3", "4", "5"})
        if action == "5":
            print("Thanks for playing!")
            break
        if action == "2":
            show_leaderboard()
            continue
        if action == "3":
            if analysis_script is None:
                print("Analysis script not found.")
                continue
            result = subprocess.run([sys.executable, analysis_script, "--show"], check=False)
            if result.returncode:
                print(f"Analysis failed with exit code {result.returncode}.")
            continue
        if action == "4":
            reset_results()
            continue

        player = read_input("Your name: ", "Player")
        print("\nPick a level:  1) Easy   2) Medium   3) Hard")
        level = LEVELS[ask("Level: ", set(LEVELS))]
        subject = pick_subject(level)
        play_round(player, level, subject)


if __name__ == "__main__":
    main()
