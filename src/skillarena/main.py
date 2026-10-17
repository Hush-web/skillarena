from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import base64
import json
import time
from pathlib import Path

app = FastAPI(title="Proofed")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Config ----------
JUDGE0_URL = "https://ce.judge0.com"

LANGUAGE_MAP = {
    "python": 71,
    "javascript": 63,
    "cpp": 54,
}

LEADERBOARD_FILE = Path(__file__).parent / "leaderboard.json"

# ---------- Challenge bank ----------
CHALLENGES = {
    1: {
        "title": "Add Two Numbers",
        "prompt": "Write a function `add(a, b)` that returns the sum of a and b.",
        "function": "add",
        "points": 10,
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
        "points": 15,
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
}


# ---------- Leaderboard storage ----------
def load_leaderboard() -> dict:
    if not LEADERBOARD_FILE.exists():
        return {}
    try:
        return json.loads(LEADERBOARD_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_leaderboard(board: dict) -> None:
    try:
        LEADERBOARD_FILE.write_text(json.dumps(board, indent=2))
    except OSError:
        pass


def award(player: str, challenge_id: int, points: int) -> tuple[int, int]:
    """Returns (points_earned, new_score)."""
    board = load_leaderboard()
    entry = board.setdefault(player, {"score": 0, "solved": []})

    if challenge_id in entry["solved"]:
        return 0, entry["score"]

    entry["solved"].append(challenge_id)
    entry["score"] += points
    save_leaderboard(board)
    return points, entry["score"]


# ---------- Models ----------
class Submission(BaseModel):
    challenge_id: int
    language: str
    code: str
    player: str = "anonymous"


# ---------- Harness builders ----------
def build_harness(language: str, user_code: str, fn: str, tests: list) -> str:
    if language == "python":
        return build_python(user_code, fn, tests)
    if language == "javascript":
        return build_javascript(user_code, fn, tests)
    if language == "cpp":
        return build_cpp(user_code, fn, tests)
    raise ValueError(f"unsupported language: {language}")


def build_python(code, fn, tests):
    lines = [
        code,
        "",
        "import json, sys",
        "",
        f"if not callable(globals().get('{fn}')):",
        "    print('__MISSING__')",
        "    sys.exit(0)",
        "",
        "results = []",
    ]
    for i, t in enumerate(tests):
        args = ", ".join(repr(a) for a in t["input"])
        lines.append(
            "try:\n"
            f"    results.append({{'i': {i}, 'got': {fn}({args})}})\n"
            "except Exception as e:\n"
            f"    results.append({{'i': {i}, 'err': str(e)}})"
        )
    lines.append("print('__RESULTS__' + json.dumps(results, default=str))")
    return "\n".join(lines)


def build_javascript(code, fn, tests):
    lines = [
        code,
        "",
        f"if (typeof {fn} !== 'function') {{",
        "  console.log('__MISSING__');",
        "  process.exit(0);",
        "}",
        "const results = [];",
    ]
    for i, t in enumerate(tests):
        args = ", ".join(json.dumps(a) for a in t["input"])
        lines.append(
            f"try {{ results.push({{i: {i}, got: {fn}({args})}}); }} "
            f"catch (e) {{ results.push({{i: {i}, err: String(e)}}); }}"
        )
    lines.append("console.log('__RESULTS__' + JSON.stringify(results));")
    return "\n".join(lines)


def build_cpp(code, fn, tests):
    lines = [
        "#include <iostream>",
        "#include <string>",
        "#include <vector>",
        "using namespace std;",
        "",
        code,
        "",
        "int main() {",
        '    cout << "__RESULTS__[";',
    ]
    for i, t in enumerate(tests):
        args = []
        for a in t["input"]:
            if isinstance(a, str):
                args.append(json.dumps(a))
            else:
                args.append(str(a))
        arg_str = ", ".join(args)
        lines.append(
            f'    try {{ cout << "{i}," << {fn}({arg_str}) << ";"; }} '
            f'catch (...) {{ cout << "{i},ERR;"; }}'
        )
    lines.append('    cout << "]";')
    lines.append("    return 0;")
    lines.append("}")
    return "\n".join(lines)


# ---------- Judge0 runner ----------
def b64_decode(s) -> str:
    if not s:
        return ""
    try:
        return base64.b64decode(s).decode("utf-8", errors="replace")
    except Exception:
        return ""


def run_judge0(source_code: str, language_id: int) -> dict:
    encoded = base64.b64encode(source_code.encode("utf-8")).decode("utf-8")
    payload = {
        "source_code": encoded,
        "language_id": language_id,
        "cpu_time_limit": 5,
        "wall_time_limit": 10,
        "memory_limit": 128000,
    }

    try:
        r = httpx.post(
            f"{JUDGE0_URL}/submissions?base64_encoded=true",
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"submit failed: {e}")

    token = r.json().get("token")
    if not token:
        raise RuntimeError("no token returned from judge")

    deadline = time.time() + 45
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            r = httpx.get(
                f"{JUDGE0_URL}/submissions/{token}?base64_encoded=true",
                timeout=30,
            )
            r.raise_for_status()
        except httpx.HTTPError:
            continue

        data = r.json()
        status = data.get("status", {}) or {}
        status_id = status.get("id")

        if status_id not in (1, 2):
            return {
                "stdout": b64_decode(data.get("stdout")),
                "stderr": b64_decode(data.get("stderr")),
                "compile_output": b64_decode(data.get("compile_output")),
                "status_id": status_id,
                "status_desc": status.get("description", ""),
            }

    raise RuntimeError("judge timed out")


# ---------- Routes ----------
@app.get("/")
def root():
    return {"status": "alive", "service": "Proofed"}


@app.get("/challenges")
def list_challenges():
    return [{"id": cid, "title": ch["title"], "points": ch["points"]}
            for cid, ch in CHALLENGES.items()]


@app.get("/challenge/{challenge_id}")
def get_challenge(challenge_id: int):
    ch = CHALLENGES.get(challenge_id)
    if not ch:
        return {"error": "not found"}
    return {
        "id": challenge_id,
        "title": ch["title"],
        "prompt": ch["prompt"],
        "points": ch["points"],
        "starters": ch["starters"],
    }


@app.get("/leaderboard")
def get_leaderboard():
    board = load_leaderboard()
    rows = [
        {"player": name, "score": data["score"], "solved": len(data["solved"])}
        for name, data in board.items()
    ]
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


@app.post("/submit")
def submit(sub: Submission):
    ch = CHALLENGES.get(sub.challenge_id)
    if not ch:
        return {"error": "challenge not found"}

    player = (sub.player or "anonymous").strip()[:20] or "anonymous"

    lang_id = LANGUAGE_MAP.get(sub.language)
    if not lang_id:
        return {"error": f"unsupported language: {sub.language}"}

    try:
        harness = build_harness(sub.language, sub.code, ch["function"], ch["tests"])
    except ValueError as e:
        return {"error": str(e)}

    try:
        result = run_judge0(harness, lang_id)
    except Exception as e:
        return {"error": f"judge unavailable: {e}"}

    stdout = result.get("stdout", "") or ""
    stderr = result.get("stderr", "") or ""
    compile_output = result.get("compile_output", "") or ""
    status_id = result.get("status_id")
    status_desc = result.get("status_desc", "")

    if status_id == 6:
        detail = (compile_output or stderr or "compilation failed").strip()[:500]
        return {"error": "Compilation Error", "detail": detail}

    if "__MISSING__" in stdout:
        return {"error": f"function '{ch['function']}' not found in your code"}

    if "__RESULTS__" not in stdout:
        detail = (stderr or compile_output or stdout or "no output").strip()[:400]
        return {"error": f"your code did not run cleanly ({status_desc})", "detail": detail}

    raw = stdout.split("__RESULTS__", 1)[1].strip()
    total = len(ch["tests"])
    passed = 0

    if sub.language in ("python", "javascript"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"error": "could not parse judge output", "detail": raw[:400]}

        for item in parsed:
            if not isinstance(item, dict):
                continue
            if "err" in item or "got" not in item:
                continue
            expected = ch["tests"][item["i"]]["expected"]
            if item["got"] == expected:
                passed += 1
    else:
        body = raw.strip("[]")
        for part in body.split(";"):
            if not part:
                continue
            try:
                idx, val = part.split(",", 1)
                i = int(idx)
            except ValueError:
                continue
            if "ERR:" in val:
                continue
            expected = ch["tests"][i]["expected"]
            if str(expected) == val:
                passed += 1

    correct = passed == total
    points_earned = 0
    score = 0

    if correct:
        points_earned, score = award(player, sub.challenge_id, ch["points"])
    else:
        board = load_leaderboard()
        score = board.get(player, {}).get("score", 0)

    return {
        "correct": correct,
        "passed": passed,
        "total": total,
        "points_earned": points_earned,
        "score": score,
    }


@app.get("/app")
def app_ui():
    return FileResponse(Path(__file__).parent / "index.html")