"""Tool definitions. So far: the schedule-extraction prompt and output schema (shared with bench/)."""

# Output of extract_schedule_image / extract_schedule_text (plan.md §3).
SCHEDULE_SCHEMA = {
    "type": "object",
    "required": ["classes"],
    "properties": {"classes": {"type": "array", "items": {
        "type": "object",
        "required": ["course", "section", "days", "start", "end", "building", "room", "confidence"],
        "properties": {
            "course": {"type": "string"},
            "section": {"type": ["string", "null"]},
            "days": {"type": "array", "items": {"type": "string", "enum": ["M", "Tu", "W", "Th", "F"]}},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "building": {"type": ["string", "null"]},
            "room": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    }}},
}

EXTRACT_PROMPT = """Extract every class from this weekly schedule.
Return {"classes": [...]} with one object per course section, merging the same section across days:
{"classes": [{"course": "CS 239", "section": "Lec 1", "days": ["Tu", "Th"], "start": "10:00", "end": "11:50",
  "building": "Boelter Hall", "room": "5249", "confidence": "high"}, ...]}
Days use M, Tu, W, Th, F. Times are 24-hour HH:MM. For an image, estimate start/end from the block's position on the time grid.
confidence is "high", "medium", or "low". If a field is unreadable, use null; do not guess."""
