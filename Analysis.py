"""
Quiz Analysis - latest attempt
------------------------------
Reads attempts.csv and answers.csv (created by the quiz) and saves charts for
the MOST RECENT attempt into a 'charts' folder. Old charts are replaced.

Run:     python Analysis.py                    (latest attempt overall)
         python Analysis.py --player "Name"    (latest attempt by that player)
         python Analysis.py --show             (also opens the chart windows)
Install: pip install pandas matplotlib seaborn
"""
import glob
import os
import sys
import textwrap

import matplotlib
SHOW = "--show" in sys.argv
if not SHOW:
    matplotlib.use("Agg")          # no window, just save files
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

BASE = os.path.dirname(os.path.abspath(__file__))


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


DATA_DIR = resolve_data_dir()
OUT = os.path.join(BASE, "charts")
GOOD, BAD, INK, MUTED, SOFT = "#2e7d5b", "#c25e4b", "#182821", "#7b8980", "#8fc2a8"
AMBER = "#d9a441"
sns.set_theme(style="whitegrid", rc={"axes.grid.axis": "y"})


def save(fig_name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, fig_name)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    print("saved", path)
    if not SHOW:
        plt.close()


def get_arg(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


# ---------- charts ----------
def chart_summary(player, level, rnd, total_time):
    score, total = int(rnd["correct"].sum()), len(rnd)
    wrong = total - score
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(["Correct", "Wrong"], [score, wrong], color=[GOOD, BAD], width=0.55)
    for i, v in enumerate([score, wrong]):
        ax.text(i, v + total * 0.02, str(v), ha="center", fontsize=14, fontweight="bold", color=INK)
    ax.set_ylim(0, total * 1.15)
    ax.set_yticks(range(0, total + 1, max(1, total // 5)))
    ax.set_ylabel("Number of questions")
    ax.set_title(f"{player}: {score}/{total} correct ({100 * score / total:.0f}%)\n"
                 f"{level.title()} level, {total_time:g} seconds")
    save("1_score_summary.png")


def chart_topics(rnd):
    cat = rnd.groupby("category").agg(correct=("correct", "sum"), asked=("correct", "size")).reset_index()
    cat["pct"] = 100 * cat["correct"] / cat["asked"]
    cat = cat.sort_values(["pct", "asked"], ascending=[False, False], kind="stable").reset_index(drop=True)
    colors = [GOOD if p >= 70 else AMBER if p >= 40 else BAD for p in cat["pct"]]
    fig, ax = plt.subplots(figsize=(10, max(6, 0.75 * len(cat) + 3)))
    ys = list(range(len(cat)))
    ax.barh(ys, cat["pct"], color=colors, height=0.6)
    for y, (_, r) in zip(ys, cat.iterrows()):
        ax.text(r["pct"] + 1.5, y, f"{int(r['correct'])}/{int(r['asked'])}  ({r['pct']:.0f}%)",
                va="center", fontsize=13, color=INK)
    handles = [Patch(color=GOOD, label="70% or more"), Patch(color=AMBER, label="40 to 69%"),
               Patch(color=BAD, label="Under 40%")]
    ax.set_yticks(ys)
    ax.set_yticklabels(cat["category"], fontsize=13)
    ax.set_ylim(len(cat) - 0.5, -0.5)
    ax.set_xlim(0, 130)
    ax.set_xlabel("Correct answers (%)", fontsize=14)
    ax.grid(True, axis="x")
    ax.grid(False, axis="y")
    title = "Your topics, strongest to weakest"
    if len(cat) > 1 and cat["pct"].iloc[-1] < cat["pct"].iloc[0]:
        weak = cat.iloc[-1]
        title += f"\nWeakest topic: {weak['category']} ({int(weak['correct'])}/{int(weak['asked'])})"
    ax.set_title(title, fontsize=17)
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=len(handles), frameon=False,
              fontsize=12)
    save("2_topics_strongest_to_weakest.png")


def chart_timeline(rnd):
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(rnd["n"], rnd["time_taken_sec"], color=[GOOD if c else BAD for c in rnd["correct"]], width=0.7)
    ax.set_xticks(rnd["n"])
    ax.set_xlabel("Question number")
    ax.set_ylabel("Seconds")
    ax.set_title("Time spent on each question")
    ax.legend(handles=[Patch(color=GOOD, label="Correct"), Patch(color=BAD, label="Wrong")],
              loc="upper right", frameon=False)
    save("3_time_per_question.png")


def chart_speed_accuracy(rnd):
    cats = list(rnd["category"].drop_duplicates())
    fig, ax = plt.subplots(figsize=(10, max(6, 0.8 * len(cats) + 3.6)))
    for yi, cat in enumerate(cats):
        sub = rnd[rnd["category"] == cat].reset_index(drop=True)
        step = min(0.24, 0.85 / max(len(sub) - 1, 1))
        for k, r in sub.iterrows():
            y = yi + (k - (len(sub) - 1) / 2) * step
            ax.scatter(r["time_taken_sec"], y, s=230, color=GOOD if r["correct"] else BAD,
                       edgecolor="white", linewidth=1.2, zorder=3)
            ax.annotate(str(int(r["n"])), (r["time_taken_sec"], y), xytext=(0, 9), textcoords="offset points",
                        ha="center", fontsize=11, color=MUTED)
    right = rnd.loc[rnd["correct"] == 1, "time_taken_sec"]
    wrong = rnd.loc[rnd["correct"] == 0, "time_taken_sec"]
    if len(right) and len(wrong):
        r_avg, w_avg = right.mean(), wrong.mean()
        if w_avg < r_avg * 0.8:
            note = f"Wrong answers were quicker ({w_avg:.1f}s vs {r_avg:.1f}s): you may have rushed those."
        elif w_avg > r_avg * 1.2:
            note = f"Wrong answers took longer ({w_avg:.1f}s vs {r_avg:.1f}s): those questions were tougher."
        else:
            note = f"Right and wrong answers took about the same time ({r_avg:.1f}s vs {w_avg:.1f}s)."
    elif len(wrong) == 0:
        note = "Every answer was correct, so there is no rushing pattern to spot."
    else:
        note = "No answers were correct this round."
    ax.set_yticks(range(len(cats)))
    ax.set_yticklabels(cats, fontsize=13)
    ax.set_ylim(len(cats) - 0.5, -0.5)
    ax.set_xlim(0, rnd["time_taken_sec"].max() * 1.15 + 0.05)
    ax.set_xlabel("Seconds taken (the number above each dot is the question number)", fontsize=14)
    ax.set_title("Speed vs accuracy", fontsize=17, pad=26)
    ax.text(0.5, 1.02, note, transform=ax.transAxes, ha="center", fontsize=12, color=MUTED)
    ax.legend(handles=[Line2D([0], [0], marker="o", color="w", markerfacecolor=GOOD, markersize=10, label="Correct"),
                       Line2D([0], [0], marker="o", color="w", markerfacecolor=BAD, markersize=10, label="Wrong")],
              loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False, fontsize=12)
    save("4_speed_vs_accuracy.png")


def chart_fast_slow(rnd):
    k = max(1, min(3, len(rnd) // 2))
    asc = rnd.sort_values("time_taken_sec", kind="stable")
    fastest, slowest = asc.head(k), asc.tail(k).iloc[::-1]
    xmax = rnd["time_taken_sec"].max() * 1.2 + 0.01
    fig, axes = plt.subplots(2, 1, figsize=(12, 1.45 * k + 3), sharex=True)
    for ax, df, title in ((axes[0], fastest, "Fastest answers"), (axes[1], slowest, "Slowest answers")):
        labels = [f"Q{int(r['n'])}: " + textwrap.shorten(str(r["question"]), width=58, placeholder="...")
                  for _, r in df.iterrows()]
        ax.barh(range(len(df)), df["time_taken_sec"], color=[GOOD if c else BAD for c in df["correct"]], height=0.6)
        for i, t in enumerate(df["time_taken_sec"]):
            ax.text(t + xmax * 0.01, i, f"{t:g}s", va="center", fontsize=13, color=INK)
        ax.set_yticks(range(len(df)))
        ax.set_yticklabels(labels, fontsize=12)
        ax.set_ylim(len(df) - 0.5, -0.5)
        ax.set_xlim(0, xmax)
        ax.set_title(title, loc="left", fontsize=15)
        ax.grid(True, axis="x")
        ax.grid(False, axis="y")
    axes[1].set_xlabel("Seconds", fontsize=14)
    axes[0].legend(handles=[Patch(color=GOOD, label="Correct"), Patch(color=BAD, label="Wrong")],
                   loc="lower right", frameon=False, fontsize=12)
    save("5_fastest_and_slowest.png")


def chart_compare(attempts, player, ts, level, this_pct):
    same = attempts[attempts["difficulty"].str.lower() == level]
    is_this = (same["timestamp"] == ts) & (same["player"] == player)
    before = same[~is_this]
    mine_before = before[before["player"] == player]
    bars = [("This attempt", this_pct, GOOD)]
    if not mine_before.empty:
        bars.append(("Your previous best", mine_before["percentage"].max(), SOFT))
    if not before.empty:
        bars.append(("Average of other attempts", before["percentage"].mean(), MUTED))
    bars.append(("Top score at this level", same["percentage"].max(), INK))
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar([b[0] for b in bars], [b[1] for b in bars], color=[b[2] for b in bars], width=0.6)
    for i, b in enumerate(bars):
        ax.text(i, b[1] + 2, f"{b[1]:.0f}%", ha="center", fontsize=11, color=INK)
    if before.empty:
        ax.text(0.5, 0.92, "Play more rounds to unlock more comparisons.", transform=ax.transAxes,
                ha="center", color=MUTED, fontsize=10)
    ax.set_ylim(0, 115)
    ax.set_ylabel("Score (%)")
    ax.set_title(f"How this attempt compares ({level.title()})")
    plt.xticks(rotation=12)
    save("6_how_you_compare.png")



# ---------- main ----------
def main():
    try:
        attempts = pd.read_csv(os.path.join(DATA_DIR, "attempts.csv"), dtype={"player": str})
        answers = pd.read_csv(os.path.join(DATA_DIR, "answers.csv"), dtype={"player": str})
    except FileNotFoundError:
        sys.exit(f"No results yet. Play a quiz round first, then open this page again. (Looked in {DATA_DIR})")
    if attempts.empty or answers.empty:
        sys.exit("No results yet. Play a quiz round first, then open this page again.")

    attempts["percentage"] = pd.to_numeric(attempts["percentage"], errors="coerce")
    attempts["total_time_sec"] = pd.to_numeric(attempts["total_time_sec"], errors="coerce")
    answers["time_taken_sec"] = pd.to_numeric(answers["time_taken_sec"], errors="coerce")
    answers["correct"] = pd.to_numeric(answers["is_correct"], errors="coerce").fillna(0).astype(int)

    pool = attempts
    wanted = get_arg("--player")
    if wanted:
        pool = attempts[attempts["player"].str.strip().str.lower() == wanted.strip().lower()]
        if pool.empty:
            names = ", ".join(sorted(attempts["player"].dropna().unique()))
            sys.exit(f"No attempts found for '{wanted}'. Players with results: {names}")
    latest = pool.sort_values("timestamp", kind="stable").iloc[-1]

    player, ts = str(latest["player"]), latest["timestamp"]
    level = str(latest["difficulty"]).lower()
    in_round = (answers["timestamp"] == ts) & (answers["player"] == player)
    rnd = answers[in_round].reset_index(drop=True)
    if rnd.empty:
        sys.exit("Found your latest attempt, but not its answers in answers.csv.")
    rnd["n"] = rnd.index + 1

    score, total = int(rnd["correct"].sum()), len(rnd)
    pct = round(100 * score / total, 1)
    total_time = latest["total_time_sec"] if pd.notna(latest["total_time_sec"]) else rnd["time_taken_sec"].sum()
    print(f"Latest attempt: {player} - {level.title()} - {score}/{total} ({pct}%)")

    os.makedirs(OUT, exist_ok=True)
    for old in glob.glob(os.path.join(OUT, "*.png")):
        try:
            os.remove(old)
        except OSError:
            pass

    chart_summary(player, level, rnd, total_time)
    chart_topics(rnd)
    chart_timeline(rnd)
    chart_speed_accuracy(rnd)
    chart_fast_slow(rnd)
    chart_compare(attempts, player, ts, level, pct)

    if SHOW:
        plt.show()


if __name__ == "__main__":
    main()
