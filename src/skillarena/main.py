from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

app = FastAPI(title="SkillArena")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Challenge bank (hardcoded for now) ----------
CHALLENGES = {
    1: {
        "title": "Add Two Numbers",
        "prompt": "Write a function `add(a, b)` that returns the sum of a and b.",
        "starter": "def add(a, b):\n    # your code here\n    pass\n",
        "function": "add",
        "tests": [
            {"input": (2, 3), "expected": 5},
            {"input": (-1, 1), "expected": 0},
            {"input": (10, 10), "expected": 20},
        ],
    },
    2: {
        "title": "Reverse a String",
        "prompt": "Write a function `reverse(s)` that returns s reversed.",
        "starter": "def reverse(s):\n    # your code here\n    pass\n",
        "function": "reverse",
        "tests": [
            {"input": ("hello",), "expected": "olleh"},
            {"input": ("",), "expected": ""},
            {"input": ("ab",), "expected": "ba"},
        ],
    },
    3: {
        "title": "Is Palindrome",
        "prompt": "Write a function `is_palindrome(s)` that returns True if s reads the same forwards and backwards, ignoring case.",
        "starter": "def is_palindrome(s):\n    # your code here\n    pass\n",
        "function": "is_palindrome",
        "tests": [
            {"input": ("racecar",), "expected": True},
            {"input": ("Hello",), "expected": False},
            {"input": ("",), "expected": True},
        ],
    },
}


# ---------- Models ----------
class Submission(BaseModel):
    challenge_id: int
    code: str


# ---------- Routes ----------
@app.get("/")
def root():
    return {"status": "alive", "service": "SkillArena"}


@app.get("/challenges")
def list_challenges():
    return [
        {"id": cid, "title": ch["title"]}
        for cid, ch in CHALLENGES.items()
    ]


@app.get("/challenge/{challenge_id}")
def get_challenge(challenge_id: int):
    ch = CHALLENGES.get(challenge_id)
    if not ch:
        return {"error": "not found"}
    return {
        "id": challenge_id,
        "title": ch["title"],
        "prompt": ch["prompt"],
        "starter": ch["starter"],
    }


@app.post("/submit")
def submit(sub: Submission):
    ch = CHALLENGES.get(sub.challenge_id)
    if not ch:
        return {"error": "challenge not found"}

    # WARNING: exec is NOT safe. For local testing only.
    results = []
    try:
        namespace = {}
        exec(sub.code, namespace)
        func = namespace.get(ch["function"])
        if not func:
            return {"error": f"function '{ch['function']}' not found in your code"}

        for test in ch["tests"]:
            try:
                got = func(*test["input"])
                results.append(got == test["expected"])
            except Exception:
                results.append(False)
    except Exception as e:
        return {"error": f"failed to run: {e}"}

    passed = sum(results)
    total = len(results)
    return {
        "correct": passed == total,
        "passed": passed,
        "total": total,
    }


@app.get("/app")
def app_ui():
    return FileResponse(Path(__file__).parent / "index.html")