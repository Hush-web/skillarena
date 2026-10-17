import json
import httpx
import base64
import time

JUDGE0_URL = "https://ce.judge0.com"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Try these in order until one works.
# As of Oct 2026, these are Groq's recommended production models.
MODELS = [
    "openai/gpt-oss-20b",    # fast, cheap, good for task generation
    "openai/gpt-oss-120b",   # stronger, still fast
]

PROMPT_TEMPLATE = """You generate coding tasks for a competitive programming platform.

You MUST respond with a single valid JSON object. No markdown, no prose, no code fences.

Schema:
{
  "title": "Short title, max 5 words",
  "prompt": "One or two sentences. Use backticks for code. Under 200 chars.",
  "function_name": "snake_case_name",
  "tests": [{"input": [arg1, arg2], "expected": result}],
  "reference_solution": "def name(arg1, arg2):\\n    return result",
  "starters": {
    "python": "def name(arg1, arg2):\\n    pass\\n",
    "javascript": "function name(arg1, arg2) {\\n    // your code\\n}\\n",
    "cpp": "#include <iostream>\\nusing namespace std;\\n\\nint name(int arg1, int arg2) {\\n    return 0;\\n}\\n"
  }
}

CRITICAL RULES — violations will cause rejection:
1. "input" is ALWAYS a LIST of arguments. If the function takes one argument that is itself a list, input must be [[1,2,3]] (nested list).
2. Exactly 3 test cases.
3. All test inputs/outputs must be JSON primitives: int, string, bool, flat list of ints/strings.
4. reference_solution must be a valid Python 3 function that returns the correct answer for ALL 3 tests.
5. function_name must match the function name in all 3 starters.
6. No print(), no input(), no file I/O. Pure computation only.
7. Difficulty: {difficulty}

Example response for difficulty=easy:
{"title": "Multiply Numbers", "prompt": "Write `multiply(a, b)` that returns a times b.", "function_name": "multiply", "tests": [{"input": [2, 3], "expected": 6}, {"input": [0, 5], "expected": 0}, {"input": [-1, 4], "expected": -4}], "reference_solution": "def multiply(a, b):\\n    return a * b", "starters": {"python": "def multiply(a, b):\\n    pass\\n", "javascript": "function multiply(a, b) {\\n    // your code\\n}\\n", "cpp": "#include <iostream>\\nusing namespace std;\\n\\nint multiply(int a, int b) {\\n    return 0;\\n}\\n"}}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    return json.loads(text)


def _b64_decode(s: str) -> str:
    if not s:
        return ""
    try:
        return base64.b64decode(s).decode("utf-8", errors="replace")
    except Exception:
        return ""


def verify_task(task: dict) -> tuple[bool, str]:
    """Returns (ok, reason). Runs reference solution against tests via Judge0."""
    ref = task.get("reference_solution", "")
    tests = task.get("tests", [])
    fn = task.get("function_name", "")
    starters = task.get("starters", {})

    if not ref:
        return False, "missing reference_solution"
    if not fn:
        return False, "missing function_name"
    if len(tests) != 3:
        return False, f"expected 3 tests, got {len(tests)}"
    if not all(k in starters for k in ("python", "javascript", "cpp")):
        return False, "missing one or more starters"

    lines = [ref, "", "import json, sys", "",
             f"if not callable(globals().get('{fn}')):",
             "    print('__MISSING__')", "    sys.exit(0)", "", "results = []"]
    for i, t in enumerate(tests):
        args_list = t.get("input", [])
        if not isinstance(args_list, list):
            return False, f"test {i} input must be a list"
        args = ", ".join(repr(a) for a in args_list)
        lines.append(
            "try:\n"
            f"    results.append({{'i': {i}, 'got': {fn}({args})}})\n"
            "except Exception as e:\n"
            f"    results.append({{'i': {i}, 'err': str(e)}})"
        )
    lines.append("print('__RESULTS__' + json.dumps(results, default=str))")
    code = "\n".join(lines)

    encoded = base64.b64encode(code.encode()).decode()
    payload = {"source_code": encoded, "language_id": 71,
               "cpu_time_limit": 5, "wall_time_limit": 10}

    try:
        r = httpx.post(f"{JUDGE0_URL}/submissions?base64_encoded=true", json=payload, timeout=30)
        r.raise_for_status()
        token = r.json()["token"]
    except Exception as e:
        return False, f"judge submit failed: {e}"

    deadline = time.time() + 30
    data = None
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            r = httpx.get(f"{JUDGE0_URL}/submissions/{token}?base64_encoded=true", timeout=30)
            data = r.json()
        except Exception:
            continue
        if (data.get("status") or {}).get("id") not in (1, 2):
            break
    else:
        return False, "judge timed out"

    stdout = _b64_decode(data.get("stdout", ""))
    stderr = _b64_decode(data.get("stderr", ""))
    compile_out = _b64_decode(data.get("compile_output", ""))

    if "__MISSING__" in stdout:
        return False, f"reference_solution does not define '{fn}'"
    if "__RESULTS__" not in stdout:
        detail = (stderr or compile_out or stdout or "no output").strip()[:200]
        return False, f"reference run failed: {detail}"

    try:
        results = json.loads(stdout.split("__RESULTS__", 1)[1].strip())
    except Exception:
        return False, "could not parse reference output"

    mismatches = []
    for item in results:
        i = item["i"]
        if "err" in item:
            mismatches.append(f"test {i} error: {item['err']}")
            continue
        if item.get("got") != tests[i]["expected"]:
            mismatches.append(f"test {i}: got {item.get('got')!r}, expected {tests[i]['expected']!r}")

    if mismatches:
        return False, "reference does not match tests: " + "; ".join(mismatches[:2])
    return True, "ok"


def _try_generate(difficulty: str, groq_key: str, model: str) -> tuple[dict | None, str]:
    """Single attempt with one model. Returns (task, reason)."""
    try:
        r = httpx.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROMPT_TEMPLATE.replace("{difficulty}", difficulty)}],
                "temperature": 0.7,
                "max_tokens": 1500,
                "response_format": {"type": "json_object"},
            },
            timeout=45,
        )
    except Exception as e:
        return None, f"network: {e}"

    if r.status_code != 200:
        return None, f"{model} HTTP {r.status_code}: {r.text[:200]}"

    try:
        content = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return None, f"{model} bad response shape: {e}"

    try:
        task = _extract_json(content)
    except Exception as e:
        return None, f"{model} JSON parse: {e}. Raw: {content[:200]}"

    ok, reason = verify_task(task)
    if not ok:
        return None, f"{model} verification: {reason}"

    return task, "ok"


def generate_task(difficulty: str, groq_key: str) -> tuple[dict | None, str]:
    """Try multiple models × 2 attempts each. Returns (task, reason)."""
    last = "no models tried"
    for model in MODELS:
        for attempt in range(2):
            task, reason = _try_generate(difficulty, groq_key, model)
            if task:
                return task, "ok"
            last = f"attempt {attempt + 1}: {reason}"
    return None, last