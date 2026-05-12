"""
Stage 4: Image generation via Apimart (gpt-image-2 by default).

Reads shots from script.json, submits one image task per shot, polls until
ready, and saves to images/shot_NNN.png.

Usage:
    python scripts/img_apimart.py             # all shots, skip done
    python scripts/img_apimart.py --shot 5    # single shot
    python scripts/img_apimart.py --force     # regenerate all
    python scripts/img_apimart.py --project <dir>

Environment:
    APIMART_API_KEY    (required)
"""
import os, sys, json, time, hashlib, requests
from pathlib import Path

# --- project resolution & env loading -------------------------------
def _resolve_project():
    args = sys.argv
    if "--project" in args:
        return Path(args[args.index("--project") + 1]).resolve()
    return Path(__file__).resolve().parent.parent

PROJECT = _resolve_project()
_env_file = PROJECT / "config.env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
# --------------------------------------------------------------------

SCRIPT  = PROJECT / "script.json"
IMAGES  = PROJECT / "images"
STATE   = PROJECT / ".pipeline_state.json"

BASE_URL = "https://api.apimart.ai"
GEN_URL  = f"{BASE_URL}/v1/images/generations"
TASK_URL = f"{BASE_URL}/v1/tasks"
API_KEY  = os.environ.get("APIMART_API_KEY", "")

RATIO_MAP = {"16:9": "16:9", "9:16": "9:16", "1:1": "1:1"}


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def prompt_hash(p):
    return hashlib.md5(p.encode()).hexdigest()[:8]


def submit_task(prompt, size, model="gpt-image-2"):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "prompt": prompt, "size": size, "n": 1}
    r = requests.post(GEN_URL, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    task_id = (
        data.get("task_id")
        or data.get("id")
        or (data.get("data", [{}])[0].get("task_id") if isinstance(data.get("data"), list) else None)
        or (data.get("data", {}).get("task_id") if isinstance(data.get("data"), dict) else None)
    )
    if not task_id:
        raise ValueError(f"No task_id in response: {data}")
    return task_id


def poll_task(task_id, timeout=300, interval=5):
    headers = {"Authorization": f"Bearer {API_KEY}"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{TASK_URL}/{task_id}", headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        inner = data.get("data", data)
        if isinstance(inner, list):
            inner = inner[0]
        status = inner.get("status", data.get("status", ""))
        if status == "completed":
            result = inner.get("result") or {}
            images = result.get("images") or []
            if images:
                raw_url = images[0].get("url")
                url = raw_url[0] if isinstance(raw_url, list) and raw_url else raw_url
            else:
                url = inner.get("url") or inner.get("image_url")
            if not url:
                raise ValueError(f"Task completed but no image URL: {data}")
            return url
        elif status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Task {task_id} failed: {data}")
        print(f"    ... {status} waiting {interval}s", end="\r")
        time.sleep(interval)
    raise TimeoutError(f"Task {task_id} timed out after {timeout}s")


def download_image(url, out_path):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    out_path.write_bytes(r.content)


def generate_image(shot, style_anchor, size, model):
    out = IMAGES / f"shot_{shot['id']:03d}.png"
    # If style_anchor contains {scene} placeholder, use it as a wrap template.
    # Otherwise fall back to simple prefix concatenation.
    if "{scene}" in style_anchor:
        full_prompt = style_anchor.replace("{scene}", shot["image_prompt"])
    else:
        full_prompt = f"{style_anchor}, {shot['image_prompt']}"
    if len(full_prompt) > 4000:
        full_prompt = full_prompt[:4000]

    for attempt in range(3):
        try:
            print(f"  -> submit shot_{shot['id']:03d} ... ", end="", flush=True)
            task_id = submit_task(full_prompt, size, model)
            print(f"task {task_id[:16]}...", flush=True)
            img_url = poll_task(task_id)
            print(f"  -> download ...", end="", flush=True)
            download_image(img_url, out)
            print(f" OK shot_{shot['id']:03d}.png")
            return True
        except Exception as e:
            print(f"\n  FAIL shot {shot['id']} attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    return False


def main():
    if not API_KEY:
        print("ERROR: APIMART_API_KEY not set (put it in config.env or env)")
        sys.exit(1)

    IMAGES.mkdir(exist_ok=True)
    script       = json.loads(SCRIPT.read_text(encoding="utf-8"))
    shots        = script["shots"]
    style_anchor = script.get("style_anchor", "")
    ar           = script.get("aspect_ratio", "16:9")
    model        = script.get("image_model", "gpt-image-2")
    size         = RATIO_MAP.get(ar, "16:9")

    force_all  = "--force" in sys.argv
    force_shot = None
    if "--shot" in sys.argv:
        idx = sys.argv.index("--shot")
        force_shot = int(sys.argv[idx + 1])

    state      = load_state()
    img_hashes = state.get("img_hashes", {})

    targets = []
    if force_shot is not None:
        targets = [s for s in shots if s["id"] == force_shot]
    else:
        for s in shots:
            key      = str(s["id"])
            ph       = prompt_hash(s["image_prompt"])
            img_path = IMAGES / f"shot_{s['id']:03d}.png"
            if force_all:
                targets.append(s)
            elif not img_path.exists() or img_hashes.get(key) != ph:
                targets.append(s)

    if not targets:
        print("[img] All images already generated. Use --force to regenerate.")
        return

    print(f"[img] Generating {len(targets)} image(s) via {model} ({size})")
    print(f"      Style anchor: {style_anchor[:80]}...")

    ok = 0
    for shot in targets:
        if generate_image(shot, style_anchor, size, model):
            img_hashes[str(shot["id"])] = prompt_hash(shot["image_prompt"])
            ok += 1
        time.sleep(1)

    state["img_hashes"] = img_hashes
    save_state(state)
    print(f"\n[img] Done {ok}/{len(targets)}")


if __name__ == "__main__":
    main()
