# CLAUDE.md

The project instructions for every coding agent live in AGENTS.md:

@AGENTS.md

## Claude-specific notes

- **Before you start:** read `docs/ARCHITECTURE.md` for the area you are changing.
- **Slow commands:** run the full Python suite (`python3 -m pytest -q`, ~8–10 min) and CI waits in the background. Run the targeted tests for the area first.
- **UI changes:** check them in the pre-installed Chromium with Playwright against a demo server (`DEMO_MODE=true uvicorn api.main:app --port 8766`) at 1280 px and 390 px, in light and dark mode. Look at the screenshots before calling the work done.
- **Charts:** follow the shared chart style in `frontend/src/app/shared/chart.ts`.
- **Commits and PRs** end with the attribution lines given in the session's instructions.
