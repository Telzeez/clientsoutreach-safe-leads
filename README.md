# ClientsOutreach Python

Safe Lead Scraper from Google Maps

Version 1.0

This repository is the workspace for the ClientsOutreach lead-generation stack, with the main project living in [Lead-Scraper-Google-Maps](./Lead-Scraper-Google-Maps).

## Workspace layout

- [Lead-Scraper-Google-Maps](./Lead-Scraper-Google-Maps) — Google Maps lead scraper and CLI wizard
- [src/clientsoutreach_python](./src/clientsoutreach_python) — package scaffold for the monorepo root

## Setup with uv

This repo is set up to use uv for dependency management and project execution.

From the repository root:

```bash
uv sync --all-packages
```

If you want to run the scraper project directly:

```bash
cd Lead-Scraper-Google-Maps
uv sync
```

## Run the scraper

```bash
cd Lead-Scraper-Google-Maps
uv run python main.py
```

To skip the wizard and start a quick run:

```bash
cd Lead-Scraper-Google-Maps
uv run python main.py \
  --city "Lahore" \
  --depth areas \
  --categories plumbers electricians \
  --profile no_website \
  -y
```

## Environment variables

Set your Google Maps API key before running the scraper:

```bash
export SCRAPER_GOOGLE_MAPS_API_KEY="your-key"
```

For PowerShell:

```powershell
$env:SCRAPER_GOOGLE_MAPS_API_KEY = "your-key"
```

## Notes

- Use uv instead of virtualenv + pip for setup and execution.
- Use `uv run ...` so the project environment stays consistent across machines.
- Optional website lookup profiles may require the Playwright browser runtime.

For project-specific usage, architecture, CLI flags, and output details, see [Lead-Scraper-Google-Maps/README.md](./Lead-Scraper-Google-Maps/README.md).
