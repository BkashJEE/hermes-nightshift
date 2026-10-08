# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-08

### Added
- `nightshift_start` / `nightshift_stop` / `nightshift_status` / `nightshift_report` tools, the `nightshift` skill and the `hermes nightshift` CLI command.
- Records every running Bot Screen with `ffmpeg x11grab`, builds a tiled, labelled time-lapse (up to 6 screens) and a report with per-Bot sessions, screen actions, status from the Bot's last reply, and human takeovers, all read from `state.db`.
