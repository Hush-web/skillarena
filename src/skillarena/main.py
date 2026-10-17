from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import date, datetime
from pathlib import Path
import httpx
import base64
import json
import time
import os
from . import generator

app = FastAPI(title="Merit")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

JUDGE0_URL = "https://ce.judge0.com"
LANGUAGE_MAP = {"python": 71, "javascript": 63, "cpp": 54}
PLAYERS_FILE = Path(__file__).parent / "players.json"
GENERATED_TASKS_FILE = Path(__file__).parent / "generated_tasks.json"

DIFFICULTY_POINTS = {"easy": 10, "medium": 25, "hard": 50, "expert": 100}

# ---------- Seed challenges ----------
CHALLENGES = {
    1: {
        "title": "Add Two Numbers",
        "prompt": "Write a function `add(a, b)` that returns the sum of a and b.",
        "function": "add",
        "task_type": "build",
        "difficulty": "easy",
        "target_seconds": 60,
        "tests": [
            {"input": (2, 3), "expected": 5},
            {"input": (-1, 1), "expected": 0},
            {"input": (10, 10), "expected": 20},
        ],
        "starters": {
            "python": "def add(a, b):\n    pass\n",
            "javascript": "function add(a, b) {\n    // your code here\n}\n",
            "cpp": "#include <iostream>\nusing namespace std;\n\nint add(int a, int b) {\n    return 0;\n}\n",
        },
    },
    2: {
        "title": "Reverse a String",
        "prompt": "Write a function `reverse(s)` that returns s reversed.",
        "function": "reverse",
        "task_type": "build",
        "difficulty": "easy",
        "target_seconds": 90,
        "tests": [
            {"input": ("hello",), "expected": "olleh"},
            {"input": ("",), "expected": ""},
            {"input": ("ab",), "expected": "ba"},
        ],
        "starters": {
            "python": "def reverse(s):\n    pass\n",
            "javascript": "function reverse(s) {\n    // your code here\n}\n",
            "cpp": "#include <iostream>\n#include <string>\nusing namespace std;\n\nstring reverse(string s) {\n    return \"\";\n}\n",
        },
    },
    3: {
        "title": "Max of List",
        "prompt": "The function below should return the maximum value in a list, but it has a bug. Find and fix it.",
        "function": "max_of_list",
        "task_type": "fix",
        "difficulty": "easy",
        "target_seconds": 60,
        "tests": [
            {"input": ([1, 2, 3, 4],), "expected": 4},
            {"input": ([5],), "expected": 5},
            {"input": ([-1, -5, -3],), "expected": -1},
        ],
        "starters": {
            "python": "def max_of_list(lst):\n    if not lst:\n        return None\n    m = lst[0]\n    for x in lst:\n        if x < m:  # BUG: should this be > ?\n            m = x\n    return m\n",
            "javascript": "function max_of_list(lst) {\n    if (lst.length === 0) return null;\n    let m = lst[0];\n    for (const x of lst) {\n        if (x < m) {  // BUG here\n            m = x;\n        }\n    }\n    return m;\n}\n",
            "cpp": "#include <iostream>\n#include <vector>\nusing namespace std;\n\nint max_of_list(vector<int> lst) {\n    if (lst.empty()) return 0;\n    int m = lst[0];\n    for (int x : lst) {\n        if (x < m) {  // BUG here\n            m = x;\n        }\n    }\n    return m;\n}\n",
        },
    },
    4: {
        "title": "Count Vowels",
        "prompt": "The function below should count vowels (a, e, i, o, u) in a string, case-insensitive. It has a bug. Fix it.",
        "function": "count_vowels",
        "task_type": "fix",
        "difficulty": "easy",
        "target_seconds": 90,
        "tests": [
            {"input": ("hello",), "expected": 2},
            {"input": ("AEIOU",), "expected": 5},
            {"input": ("xyz",), "expected": 0},
        ],
        "starters": {
            "python": "def count_vowels(s):\n    vowels = 'aeiou'\n    count = 0\n    for c in s:  # BUG: not lowercased\n        if c in vowels:\n            count += 1\n    return count\n",
            "javascript": "function count_vowels(s) {\n    const vowels = 'aeiou';\n    let count = 0;\n    for (const c of s) {  // BUG: not lowercased\n        if (vowels.includes(c)) {\n            count += 1;\n        }\n    }\n    return count;\n}\n",
            "cpp": "#include <iostream>\n#include <string>\nusing namespace std;\n\nint count_vowels(string s) {\n    string vowels = \"aeiou\";\n    int count = 0;\n    for (char c : s) {  // BUG: not lowercased\n        if (vowels.find(c) != string::npos) {\n            count += 1;\n        }\n    }\n    return count;\n}\n",
        },
    },
    5: {
        "title": "Fibonacci (fast)",
        "prompt": "Return the nth Fibonacci number (F(0)=0, F(1)=1). Naive recursion will time out on the largest test case. Use iteration or memoization.",
        "function": "fib",
        "task_type": "optimize",
        "difficulty": "medium",
        "target_seconds": 180,
        "tests": [
            {"input": (10,), "expected": 55},
            {"input": (20,), "expected": 6765},
            {"input": (35,), "expected": 9227465},
        ],
        "starters": {
            "python": "def fib(n):\n    pass\n",
            "javascript": "function fib(n) {\n    // your code here\n}\n",
            "cpp": "#include <iostream>\nusing namespace std;\n\nlong fib(int n) {\n    return 0;\n}\n",
        },
    },
}

TIERS = [("Diamond", 5000), ("Platinum", 1500), ("Gold", 500), ("Silver", 100), ("Bronze", 0)]


def tier_for(score):
    for name, threshold in TIERS:
        if score >= threshold:
            return name
    return "Bronze"


def streak_multiplier(streak):
    if streak >= 8: return 1.5
    if streak >= 4: return 1.25
    if streak >= 2: return 1.1
    return 1.0


# ---------- Player storage ----------
def load_players():
    if not PLAYERS_FILE.exists(): return {}
    try: return json.loads(PLAYERS_FILE.read_text())
    except Exception: return {}


def save_players(p):
    try: PLAYERS_FILE.write_text(json.dumps(p, indent=2))
    except Exception: pass


def new_player():
    return {"score": 0, "streak": 0, "last_solve_date": None, "solved": [], "attempts": {}}


def update_streak(player):
    today = date.today().isoformat()
    last = player.get("last_solve_date")
    if last == today: return player["streak"]
    if last:
        delta = (date.today() - date.fromisoformat(last)).days
        player["streak"] = player["streak"] + 1 if delta == 1 else 1
    else:
        player["streak"] = 1
    player["last_solve_date"] = today
    return player["streak"]


# ---------- Generated task storage ----------
def load_generated() -> dict:
    if not GENERATED_TASKS_FILE.exists():
        return {}
    try:
        return json.loads(GENERATED_TASKS_FILE.read_text())
    except Exception:
        return {}


def save_generated(tasks: dict) -> None:
    try:
        GENERATED_TASKS_FILE.write_text(json.dumps(tasks, indent=2))
    except Exception:
        pass


def all_challenges() -> dict:
    merged = dict(CHALLENGES)
    for k, v in load_generated().items():
        merged[int(k)] = v
    return merged


def next_task_id() -> int:
    return max([99] + list(all_challenges().keys())) + 1


# ---------- Scoring ----------
def compute_award(player, challenge, challenge_id, elapsed_seconds, first_in_world):
    base = DIFFICULTY_POINTS[challenge["difficulty"]]
    attempts = player["attempts"].get(str(challenge_id), 0)
    quality_bonus = int(base * 0.5) if attempts == 1 else 0
    speed_bonus = 0
    target = challenge.get("target_seconds")
    if elapsed_seconds is not None and target and elapsed_seconds <= target:
        speed_bonus = int(base * 0.5)
    subtotal = base + quality_bonus + speed_bonus
    mult = streak_multiplier(player["streak"])
    after = int(round(subtotal * mult))
    first_bonus = base if first_in_world else 0
    return {"base": base, "quality_bonus": quality_bonus, "speed_bonus": speed_bonus,
            "streak_mult": mult, "streak": player["streak"], "first_bonus": first_bonus,
            "total": after + first_bonus}


class Submission(BaseModel):
    challenge_id: int
    language: str
    code: str
    player: str = "anonymous"
    elapsed_seconds: float | None = None


# ---------- Harnesses ----------
def build_harness(language, user_code, fn, tests):
    if language == "python": return build_python(user_code, fn, tests)
    if language == "javascript": return build_javascript(user_code, fn, tests)
    if language == "cpp": return build_cpp(user_code, fn, tests)
    raise ValueError(f"unsupported language: {language}")


def build_python(code, fn, tests):
    lines = [code, "", "import json, sys", "",
             f"if not callable(globals().get('{fn}')):",
             "    print('__MISSING__')", "    sys.exit(0)", "", "results = []"]
    for i, t in enumerate(tests):
        args = ", ".join(repr(a) for a in t["input"])
        lines.append("try:\n"
                     f"    results.append({{'i': {i}, 'got': {fn}({args})}})\n"
                     "except Exception as e:\n"
                     f"    results.append({{'i': {i}, 'err': str(e)}})")
    lines.append("print('__RESULTS__' + json.dumps(results, default=str))")
    return "\n".join(lines)


def build_javascript(code, fn, tests):
    lines = [code, "", f"if (typeof {fn} !== 'function') {{",
             "  console.log('__MISSING__');", "  process.exit(0);", "}", "const results = [];"]
    for i, t in enumerate(tests):
        args = ", ".join(json.dumps(a) for a in t["input"])
        lines.append(f"try {{ results.push({{i: {i}, got: {fn}({args})}}); }} "
                     f"catch (e) {{ results.push({{i: {i}, err: String(e)}}); }}")
    lines.append("console.log('__RESULTS__' + JSON.stringify(results));")
    return "\n".join(lines)


def build_cpp(code, fn, tests):
    lines = ["#include <iostream>", "#include <string>", "#include <vector>",
             "using namespace std;", "", code, "", "int main() {", '    cout << "__RESULTS__[";']
    for i, t in enumerate(tests):
        args = [json.dumps(a) if isinstance(a, str) else str(a) for a in t["input"]]
        lines.append(f'    try {{ cout << "{i}," << {fn}({", ".join(args)}) << ";"; }} '
                     f'catch (...) {{ cout << "{i},ERR;"; }}')
    lines += ['    cout << "]";', "    return 0;", "}"]
    return "\n".join(lines)


def b64_decode(s):
    if not s: return ""
    try: return base64.b64decode(s).decode("utf-8", errors="replace")
    except Exception: return ""


def run_judge0(source_code, language_id):
    encoded = base64.b64encode(source_code.encode("utf-8")).decode("utf-8")
    payload = {"source_code": encoded, "language_id": language_id,
               "cpu_time_limit": 5, "wall_time_limit": 10, "memory_limit": 128000}
    try:
        r = httpx.post(f"{JUDGE0_URL}/submissions?base64_encoded=true", json=payload, timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"submit failed: {e}")
    token = r.json().get("token")
    if not token: raise RuntimeError("no token returned from judge")
    deadline = time.time() + 45
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            r = httpx.get(f"{JUDGE0_URL}/submissions/{token}?base64_encoded=true", timeout=30)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        data = r.json()
        status = data.get("status", {}) or {}
        status_id = status.get("id")
        if status_id not in (1, 2):
            return {"stdout": b64_decode(data.get("stdout")),
                    "stderr": b64_decode(data.get("stderr")),
                    "compile_output": b64_decode(data.get("compile_output")),
                    "status_id": status_id,
                    "status_desc": status.get("description", "")}
    raise RuntimeError("judge timed out")


# ---------- API ----------
@app.get("/api/health")
def health(): return {"status": "alive", "service": "Merit"}


@app.get("/api/challenges")
def list_challenges():
    merged = all_challenges()
    return [
        {"id": cid, "title": ch["title"], "difficulty": ch["difficulty"],
         "task_type": ch.get("task_type", "build"),
         "points": DIFFICULTY_POINTS[ch["difficulty"]],
         "generated": ch.get("generated", False)}
        for cid, ch in merged.items()
    ]


@app.get("/api/challenge/{challenge_id}")
def get_challenge(challenge_id: int):
    ch = all_challenges().get(challenge_id)
    if not ch: return {"error": "not found"}
    return {"id": challenge_id, "title": ch["title"], "prompt": ch["prompt"],
            "difficulty": ch["difficulty"], "task_type": ch.get("task_type", "build"),
            "points": DIFFICULTY_POINTS[ch["difficulty"]],
            "target_seconds": ch.get("target_seconds"), "starters": ch["starters"]}


@app.get("/api/leaderboard")
def leaderboard():
    players = load_players()
    rows = [{"player": name, "score": p["score"], "tier": tier_for(p["score"]),
             "streak": p["streak"], "solved": len(p["solved"])}
            for name, p in players.items()]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


@app.get("/api/player/{name}")
def player_profile(name: str):
    players = load_players()
    p = players.get(name)
    if not p: return {"error": "not found"}
    rank = 1 + sum(1 for q in players.values() if q["score"] > p["score"])
    merged = all_challenges()
    solved = []
    for s in p["solved"]:
        task = merged.get(s["challenge_id"])
        solved.append({
            **s,
            "title": task["title"] if task else f"Challenge #{s['challenge_id']}",
            "difficulty": task["difficulty"] if task else "unknown",
        })
    return {"player": name, "score": p["score"], "tier": tier_for(p["score"]),
            "streak": p["streak"], "solved": solved, "rank": rank,
            "last_solve_date": p["last_solve_date"]}


@app.post("/api/generate-task")
def generate_new_task(difficulty: str = "easy"):
    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        return {"error": "GROQ_API_KEY not set on the server"}
    if difficulty not in ("easy", "medium", "hard"):
        return {"error": "difficulty must be easy, medium, or hard"}

    task, reason = generator.generate_task(difficulty, groq_key)
    if not task:
        return {"error": f"generation failed — {reason}"}

    new_id = next_task_id()
    generated = load_generated()
    generated[str(new_id)] = {
        "title": task["title"],
        "prompt": task["prompt"],
        "function": task["function_name"],
        "task_type": "build",
        "difficulty": difficulty,
        "target_seconds": {"easy": 120, "medium": 240, "hard": 480}[difficulty],
        "tests": task["tests"],
        "starters": task["starters"],
        "generated": True,
    }
    save_generated(generated)

    return {"id": new_id, "title": task["title"]}

    return {"error": "could not generate a valid task after 3 attempts"}


@app.post("/api/submit")
def submit(sub: Submission):
    ch = all_challenges().get(sub.challenge_id)
    if not ch: return {"error": "challenge not found"}
    player_name = (sub.player or "anonymous").strip()[:20] or "anonymous"
    lang_id = LANGUAGE_MAP.get(sub.language)
    if not lang_id: return {"error": f"unsupported language: {sub.language}"}

    players = load_players()
    player = players.setdefault(player_name, new_player())
    cid_key = str(sub.challenge_id)
    player["attempts"][cid_key] = player["attempts"].get(cid_key, 0) + 1
    save_players(players)

    try:
        harness = build_harness(sub.language, sub.code, ch["function"], ch["tests"])
    except ValueError as e: return {"error": str(e)}
    try:
        result = run_judge0(harness, lang_id)
    except Exception as e: return {"error": f"judge unavailable: {e}"}

    stdout = result.get("stdout", "") or ""
    stderr = result.get("stderr", "") or ""
    compile_output = result.get("compile_output", "") or ""
    status_id = result.get("status_id")
    status_desc = result.get("status_desc", "")

    if status_id == 6:
        return {"error": "Compilation Error", "detail": (compile_output or stderr or "compilation failed").strip()[:500]}
    if "__MISSING__" in stdout:
        return {"error": f"function '{ch['function']}' not found in your code"}
    if "__RESULTS__" not in stdout:
        return {"error": f"your code did not run cleanly ({status_desc})",
                "detail": (stderr or compile_output or stdout or "no output").strip()[:400]}

    raw = stdout.split("__RESULTS__", 1)[1].strip()
    total = len(ch["tests"])
    passed = 0

    if sub.language in ("python", "javascript"):
        try: parsed = json.loads(raw)
        except Exception: return {"error": "could not parse judge output", "detail": raw[:400]}
        for item in parsed:
            if not isinstance(item, dict) or "err" in item or "got" not in item: continue
            if item["got"] == ch["tests"][item["i"]]["expected"]: passed += 1
    else:
        body = raw.strip("[]")
        for part in body.split(";"):
            if not part: continue
            try: idx, val = part.split(",", 1); i = int(idx)
            except Exception: continue
            if "ERR:" in val: continue
            if str(ch["tests"][i]["expected"]) == val: passed += 1

    correct = passed == total
    if not correct:
        return {"correct": False, "passed": passed, "total": total,
                "score": player["score"], "tier": tier_for(player["score"])}

    if any(s["challenge_id"] == sub.challenge_id for s in player["solved"]):
        return {"correct": True, "passed": passed, "total": total,
                "already_solved": True, "score": player["score"],
                "tier": tier_for(player["score"])}

    first_in_world = not any(any(s["challenge_id"] == sub.challenge_id for s in p["solved"])
                             for p in players.values())
    update_streak(player)
    breakdown = compute_award(player, ch, sub.challenge_id, sub.elapsed_seconds, first_in_world)
    player["score"] += breakdown["total"]
    player["solved"].append({"challenge_id": sub.challenge_id,
                             "ts": datetime.utcnow().isoformat(),
                             "points": breakdown["total"],
                             "language": sub.language,
                             "breakdown": breakdown})
    save_players(players)
    return {"correct": True, "passed": passed, "total": total, "already_solved": False,
            "points_earned": breakdown["total"], "breakdown": breakdown,
            "score": player["score"], "tier": tier_for(player["score"]),
            "streak": player["streak"]}


# ---------- Pages ----------
@app.get("/")
def page_landing(): return FileResponse(STATIC_DIR / "index.html")

@app.get("/login")
def page_login(): return FileResponse(STATIC_DIR / "login.html")

@app.get("/home")
def page_home(): return FileResponse(STATIC_DIR / "home.html")

@app.get("/leaderboard")
def page_leaderboard(): return FileResponse(STATIC_DIR / "leaderboard.html")

@app.get("/u/{name}")
def page_profile(name: str): return FileResponse(STATIC_DIR / "profile.html")