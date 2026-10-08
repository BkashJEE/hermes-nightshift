"""Tool schemas — what the LLM sees."""

NIGHTSHIFT_START = {
    "name": "nightshift_start",
    "description": (
        "Start recording every running Bot Screen (each Bot's own desktop) as a low-frame-rate video, so the "
        "Bots can work unattended and the user gets one tiled time-lapse plus a report afterwards. Call it once "
        "the Bots have their goals. Only screens that are already running are recorded; it tells you which "
        "Bots have no screen. Refuses if a shift is already recording."
    ),
    "parameters": {"type": "object", "properties": {
        "profiles": {"type": "array", "items": {"type": "string"}, "description": (
            "profile names to record (e.g. ['ceo','sanju']); omit for every running Bot Screen")},
        "fps": {"type": "number", "description": "frames per second to capture; default 2 (time-lapse)"},
        "label": {"type": "string", "description": "short name for this shift, e.g. 'launch prep'"},
    }},
}

NIGHTSHIFT_STOP = {
    "name": "nightshift_stop",
    "description": (
        "Stop the recording, build the tiled time-lapse video (all screens side by side, each labelled with the "
        "Bot's name and cursor style) and the report: per Bot, sessions, screen actions, final status from its "
        "last reply, and how many times a human had to take over. Returns the video and report paths plus the "
        "report markdown — send the markdown to the user as-is."
    ),
    "parameters": {"type": "object", "properties": {
        "speed": {"type": "number", "description": "time-lapse speed-up factor for the video; default 20"},
    }},
}

NIGHTSHIFT_STATUS = {
    "name": "nightshift_status",
    "description": "Whether a shift is recording, for how long, which Bot Screens exist and are running, and recent runs. Read-only.",
    "parameters": {"type": "object", "properties": {}},
}

NIGHTSHIFT_WALL = {
    "name": "nightshift_wall",
    "description": (
        "Open the Bot Wall: one local web page showing every running Bot Screen live, side by side, with each "
        "Bot's name, cursor style and latest words. Returns the URL (loopback only). Use when the user wants to "
        "watch the Bots work. 'stop' closes it. Read-only on the Bots: it never sends them anything."
    ),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["open", "status", "stop"], "description": "default open"},
        "port": {"type": "integer", "description": "local port; default 8793"},
    }},
}

NIGHTSHIFT_REPORT = {
    "name": "nightshift_report",
    "description": "The report and video path of a finished shift (the latest by default). Read-only.",
    "parameters": {"type": "object", "properties": {
        "run": {"type": "string", "description": "run id like 20261008-220000; omit for the latest"},
    }},
}
