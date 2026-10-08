---
name: nightshift
description: "Run a night shift: give each Bot a goal, record every Bot Screen while they work, and in the morning deliver one time-lapse video and a report of what got done, what got blocked, and how often a human had to step in. Use for 'night shift', 'run overnight', 'record the bots working', or 'what did the bots do'."
version: 0.1.0
author: Bikash Joshi
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [bot-screen, computer-use, recording, time-lapse, autonomy, report]
---

# Night Shift

The Bots work on their own desktops (Bot Screens). You record all of them and report honestly.

## Starting a shift
1. `nightshift_status` → see which Bots have a screen running. A Bot without one cannot be recorded; tell the
   user to start it (Desktop → Bots → the Bot → Screen → **Start screen**, or
   `hermes -p <profile> computer-use screen start`). Never start screens yourself.
2. Make sure every Bot has a goal before the recording starts. The user gives it, or you hand it over with
   `message_agent` / `ask_agent` if those tools exist. Goals must be concrete and end with a visible result
   ("open X, do Y, reply with ✅ when done or ⚠️ with the reason").
3. `nightshift_start` with the profiles and a short label. Default 2 fps is right for hours of work.
4. Tell the user it is recording and that `nightshift_stop` ends it. Then stop talking — do not poll.

## Ending a shift
- `nightshift_stop` builds the video and the report. Paste the returned `markdown` exactly as it is, then the
  video path. Never improve the numbers or the Bots' last words.
- If the video is `null`, say the recording was too short or a screen produced no frames, and point to the
  run folder.

## Status marks
A Bot's last reply decides its status: ✅ done · ✋ needs you · ⚠️ blocked · ⏳ scheduled · anything else
"unknown". "needed a human" counts tool calls refused because someone had taken over the screen.

## Scheduling the morning
To end a shift and deliver the report at 7am:
`hermes cron create "0 7 * * *" "Call nightshift_stop, then send the report markdown and the video path." --skill nightshift:nightshift --deliver telegram --name nightshift-morning`
