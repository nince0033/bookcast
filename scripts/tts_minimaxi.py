"""
Stage 3: Text-to-speech via MiniMax T2A v2 API.

Reads shots from script.json, generates one mp3 per shot under audio/.

Usage:
    python scripts/tts_minimaxi.py              # all shots, skip done
    python scripts/tts_minimaxi.py --shot 5     # single shot
    python scripts/tts_minimaxi.py --force      # regenerate everything
    python scripts/tts_minimaxi.py --project <dir>

Environment:
    MINIMAX_API_KEY    (required)
    MINIMAX_GROUP_ID   (optional, defaults to "placeholder")
"""
import os, sys, time, json
import urllib.request, urllib.error
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
AUDIO   = PROJECT / "audio"
STATE   = PROJECT / ".pipeline_state.json"

API_URL  = "https://api.minimax.chat/v1/t2a_v2"
API_KEY  = os.environ.get("MINIMAX_API_KEY", "")


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def tts_shot(shot, voice_id, speed=1.0, emotion="calm"):
    out = AUDIO / f"shot_{shot['id']:03d}.mp3"
    payload = {
        "model": "speech-02-hd",
        "text": shot["narration"],
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": 1.0,
            "pitch": 0,
            "emotion": emotion,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
        },
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=True).encode("ascii")

    for attempt in range(5):
        try:
            req = urllib.request.Request(
                API_URL,
                data=body,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            status_code = data.get("base_resp", {}).get("status_code", 0)
            if status_code == 1002:
                print(f"  rate limited, waiting 60s (attempt {attempt+1}/5)...")
                time.sleep(60)
                continue
            if "data" not in data or "audio" not in data["data"]:
                print(f"  shot {shot['id']}: unexpected response: {str(data)[:200]}")
                return False
            audio_hex = data["data"]["audio"]
            out.write_bytes(bytes.fromhex(audio_hex))
            print(f"  OK shot_{shot['id']:03d}.mp3  ({len(shot['narration'])} chars)")
            return True

        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            print(f"  shot {shot['id']} attempt {attempt+1}: HTTP {e.code}: {err[:200]}")
            time.sleep(5)
        except Exception as e:
            print(f"  shot {shot['id']} attempt {attempt+1}: {e}")
            time.sleep(5)
    return False


def main():
    if not API_KEY:
        print("ERROR: MINIMAX_API_KEY not set (put it in config.env or env)")
        sys.exit(1)

    AUDIO.mkdir(exist_ok=True)
    script  = json.loads(SCRIPT.read_text(encoding="utf-8"))
    shots   = script["shots"]
    voice   = script.get("voice_id", "audiobook_male_1")
    speed   = script.get("voice_speed", 1.0)
    emotion = script.get("voice_emotion", "calm")

    force_shot = None
    force_all  = "--force" in sys.argv
    if "--shot" in sys.argv:
        idx = sys.argv.index("--shot")
        force_shot = int(sys.argv[idx + 1])

    state    = load_state()
    done_ids = set(state.get("tts_done", []))

    if force_shot is not None:
        targets = [s for s in shots if s["id"] == force_shot]
    elif force_all:
        targets = shots
    else:
        targets = [s for s in shots if s["id"] not in done_ids]

    if not targets:
        print("[tts] All shots already done. Use --force to regenerate.")
        return

    print(f"[tts] Generating {len(targets)} shot(s) | voice={voice} speed={speed} emotion={emotion}")
    ok = 0
    for shot in targets:
        if tts_shot(shot, voice_id=voice, speed=speed, emotion=emotion):
            done_ids.add(shot["id"])
            ok += 1
        time.sleep(3)

    state["tts_done"] = sorted(done_ids)
    save_state(state)

    total_chars = sum(len(s["narration"]) for s in shots)
    print(f"[tts] Done {ok}/{len(targets)} | total text ~{total_chars} chars")


if __name__ == "__main__":
    main()
