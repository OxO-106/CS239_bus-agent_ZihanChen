"""Schedule-extraction bench: field-level accuracy against a hand-written truth file.

Each sample is <name>.png or <name>.txt next to <name>.truth.json (a list of class objects).
Usage: python -m bench.extract_schedule [samples...] [--runs N]
Default samples: everything in data/local/ (real schedule, untracked) and data/samples/ (committed, fake).
"""
import argparse
import json
import time
from pathlib import Path

from bus_agent.llm import ROOT, chat, encode_image
from bus_agent.tools import EXTRACT_PROMPT, SCHEDULE_SCHEMA

FIELDS = ["course", "section", "days", "start", "end", "building", "room"]


def extract(sample):
    if sample.suffix == ".txt":
        msg = {"role": "user", "content": EXTRACT_PROMPT + "\n\nSchedule:\n" + sample.read_text()}
    else:
        msg = {"role": "user", "content": EXTRACT_PROMPT, "images": [encode_image(sample)]}
    out = chat([msg], format=SCHEDULE_SCHEMA, agent="schedule")
    return json.loads(out["message"]["content"])["classes"]


def norm(field, value):
    if field == "days":
        return sorted(value or [])
    return " ".join(str(value).lower().split()) if value is not None else None


def score(got, truth):
    """Match each truth class to the extracted class with the same course+days; count correct fields."""
    correct, errors = 0, []
    for t in truth:
        key = (norm("course", t["course"]), norm("days", t["days"]))
        match = next((g for g in got if (norm("course", g["course"]), norm("days", g["days"])) == key), None)
        if match is None:
            errors.append(f"missing {t['course']} {t['days']}")
            continue
        for f in FIELDS:
            if norm(f, match.get(f)) == norm(f, t[f]):
                correct += 1
            else:
                errors.append(f"{t['course']} {''.join(t['days'])} {f}: got {match.get(f)!r}, want {t[f]!r}")
    if len(got) > len(truth):
        errors.append(f"{len(got) - len(truth)} extra classes")
    return correct, len(truth) * len(FIELDS), errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", nargs="*", type=Path)
    ap.add_argument("--runs", type=int, default=3)
    opts = ap.parse_args()
    samples = opts.samples or sorted(
        p for d in ("data/local", "data/samples") for p in (ROOT / d).glob("*")
        if p.suffix in (".png", ".jpg", ".txt") and p.with_suffix(".truth.json").exists())

    for sample in samples:
        truth = json.loads(sample.with_suffix(".truth.json").read_text())
        for run in range(1, opts.runs + 1):
            t = time.time()
            correct, total, errors = score(extract(sample), truth)
            print(f"{sample.name} run {run}: {correct}/{total} fields  {time.time() - t:.1f}s")
            for e in errors:
                print("    " + e)


if __name__ == "__main__":
    main()
