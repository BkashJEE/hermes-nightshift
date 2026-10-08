# Night Shift

Let your [Hermes](https://github.com/NousResearch/hermes-agent) Bots work on their own desktops overnight.
Wake up to **one time-lapse of every screen** and an **honest report**: what got done, what got blocked,
and how many times a human had to take over.

Each Bot's [Bot Screen](https://hermes-agent.nousresearch.com/docs/user-guide/features/bot-screen) is a
plain X display, so Night Shift records it with `ffmpeg x11grab`. No compositor hooks, no portals, no
tokens. Every tile is labelled with the Bot's name and its
[cursor motion style](https://github.com/NousResearch/hermes-agent/pull/TODO), so you can tell who is clicking.

## What you get

- `nightshift.mp4`: all Bot Screens side by side (up to 6), sped up, each tile labelled.
- `report.md`:

  | Bot | cursor | sessions | screen actions | status | needed a human |
  |---|---|---|---|---|---|
  | Sanvith — Chief of Staff | magnetic | 1 | 12 | done | 0 |
  | Sanju — CTO | comet_swoop | 1 | 19 | needs you | 1 |
  | Nova — CMO | spring_settle | 1 | 9 | done | 0 |

  Status comes from the Bot's last reply (✅ done · ✋ needs you · ⚠️ blocked · ⏳ scheduled). "Needed a
  human" counts tool calls that were refused because someone had taken over that screen. Numbers come from
  each profile's own `state.db`, read-only. Nothing is summarised by a model.

## Install

```bash
hermes plugins install BkashJEE/hermes-nightshift
hermes plugins enable nightshift
```

Needs `ffmpeg` on the host and Bot Screens (Linux; `hermes computer-use screen install`).

## Use

1. Start each Bot's screen (Desktop → Bots → the Bot → Screen → **Start screen**, or
   `hermes -p <profile> computer-use screen start`).
2. Give the Bots their goals, then say **"start the night shift"**, or:
   ```bash
   hermes nightshift start --profiles ceo sanju nova
   ```
3. In the morning, **"stop the night shift"**, or:
   ```bash
   hermes nightshift stop
   ```
   That prints the report and the video path. To have it delivered at 7am:
   ```bash
   hermes cron create "0 7 * * *" "Call nightshift_stop, then send the report markdown and the video path." --skill nightshift:nightshift --deliver telegram --name nightshift-morning
   ```

## Tools

| Tool | What it does |
|---|---|
| `nightshift_start` | Record every running Bot Screen (or the profiles you name) at 2 fps |
| `nightshift_stop` | Stop, build the tiled time-lapse and the report |
| `nightshift_status` | Recording state, which screens exist and run, recent runs |
| `nightshift_report` | Report and video path of a finished shift |

Runs live under the plugin's data folder (`plugin-data/…/nightshift/runs/<id>/`): one raw video per Bot,
`nightshift.mp4`, `report.md`, `run.json`.

## Develop

```bash
python -m unittest discover -s tests -v
hermes plugins validate .
```

## License

MIT
