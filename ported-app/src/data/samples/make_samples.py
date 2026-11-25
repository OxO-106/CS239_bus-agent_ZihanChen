"""Generate the fake sample schedules (MyUCLA-style weekly grid images + plain text).

python data/samples/make_samples.py  ->  schedule_clean.png and schedule_clean_text.txt, each with a .truth.json
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = "C:/Windows/Fonts/segoeui.ttf"

CLASSES = [
    {"course": "COM SCI 239", "section": "Lec 1", "days": ["Tu", "Th"], "start": "10:00", "end": "11:50",
     "building": "Boelter Hall", "room": "5249"},
    {"course": "MATH 170A", "section": "Lec 2", "days": ["M", "W", "F"], "start": "09:00", "end": "09:50",
     "building": "Mathematical Sciences", "room": "4000A"},
    {"course": "PHYSICS 1C", "section": "Lec 1", "days": ["Tu", "Th"], "start": "14:00", "end": "15:15",
     "building": "Knudsen Hall", "room": "1220B"},
    {"course": "COM SCI 260", "section": "Dis 1A", "days": ["W"], "start": "16:00", "end": "16:50",
     "building": "Engineering VI", "room": "289"},
]

DAYS = ["M", "Tu", "W", "Th", "F"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
COLORS = [("#e8f5e1", "#4caf50"), ("#efe6fa", "#7e3fd0"), ("#e6f2f2", "#2e8b8b"), ("#f7f5e6", "#b5a33c")]
X0, Y0, COL, HOUR = 70, 40, 210, 72  # grid origin, column width, pixels per hour
START_H, END_H = 8, 19


def minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def hour_label(h):
    return f"{(h - 1) % 12 + 1}{'AM' if h == 8 else 'PM' if h == 12 else ''}"


def draw(path):
    w, h = X0 + COL * 5 + 10, Y0 + HOUR * (END_H - START_H) + 10
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    font, bold = ImageFont.truetype(FONT, 15), ImageFont.truetype(FONT, 16)
    d.rectangle([X0, 10, w - 10, Y0], fill="#1f5ba8")
    for i, name in enumerate(DAY_NAMES):
        d.text((X0 + COL * i + COL / 2, 25), name, fill="white", font=bold, anchor="mm")
    for k in range(END_H - START_H + 1):
        y = Y0 + HOUR * k
        d.line([X0, y, w - 10, y], fill="#dddddd")
        if k < END_H - START_H:
            d.text((X0 - 8, y + 12), hour_label(START_H + k), fill="#444444", font=font, anchor="rm")
    for i in range(6):
        d.line([X0 + COL * i, Y0, X0 + COL * i, Y0 + HOUR * (END_H - START_H)], fill="#dddddd")
    for c, (fill, edge) in zip(CLASSES, COLORS):
        top = Y0 + (minutes(c["start"]) - START_H * 60) * HOUR / 60
        bottom = Y0 + (minutes(c["end"]) - START_H * 60) * HOUR / 60
        for day in c["days"]:
            x = X0 + COL * DAYS.index(day)
            d.rectangle([x + 3, top + 2, x + COL - 3, bottom - 2], fill=fill, outline=edge, width=2)
            lines = [c["course"], c["section"], f"{c['building']} {c['room']}"]
            for n, text in enumerate(lines):
                d.text((x + COL / 2, top + 12 + n * 17), text, fill=edge, font=font, anchor="mm")
    img.save(path)


def text():
    day = {"M": "M", "Tu": "T", "W": "W", "Th": "R", "F": "F"}
    rows = ["Fall 2026 Study List", ""]
    for c in CLASSES:
        rows.append(f"{c['course']:<12} {c['section']:<7} {''.join(day[d] for d in c['days']):<4} "
                    f"{c['start']}-{c['end']}   {c['building']} {c['room']}")
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    truth = json.dumps(CLASSES, indent=1)
    name = "schedule_clean"
    draw(HERE / f"{name}.png")
    (HERE / f"{name}_text.txt").write_text(text())
    (HERE / f"{name}.truth.json").write_text(truth)
    (HERE / f"{name}_text.truth.json").write_text(truth)
    print("wrote samples to", HERE)
