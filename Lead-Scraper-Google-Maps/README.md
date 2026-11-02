# Safe Lead Scraper from Google Maps

Version 1.0

A resumable Google Maps lead scraper built for local business prospecting. It uses the Google Places API and Geocoding API to discover businesses, filter them into lead profiles, and export clean CSV/XLSX outputs with a guided CLI workflow.

This project uses uv for dependency management and execution.

## What this project does

- Search by city, metro, or custom target area
- Choose search depth: `city`, `areas`, or `grid`
- Filter businesses by category and lead profile
- Deduplicate results and resume interrupted runs safely
- Export leads to CSV and Excel files
- Optionally crawl websites for email/social discovery
- Use a live dashboard or plain log output depending on your terminal

## Setup with uv

From the repository root:

```bash
uv sync --all-packages
```

Then work in this project directory:

```bash
cd Lead-Scraper-Google-Maps
uv sync
```

Launch the app:

```bash
cd Lead-Scraper-Google-Maps
uv run python main.py
```

If you want to run the CLI without the wizard:

```bash
cd Lead-Scraper-Google-Maps
uv run python main.py \
  --city "Lahore" \
  --depth areas \
  --categories plumbers electricians dentists \
  --profile no_website \
  -y
```

## Setup

### 1. Enable Google Maps APIs

Create or select a Google Cloud project and enable:

- Places API (New)
- Geocoding API

Also make sure billing is enabled for the project. Then set your API key:

```bash
export SCRAPER_GOOGLE_MAPS_API_KEY="your-key"
```

PowerShell:

```powershell
$env:SCRAPER_GOOGLE_MAPS_API_KEY = "your-key"
```

Do not commit your API key to source control.

### 2. Install dependencies

```bash
cd Lead-Scraper-Google-Maps
uv sync
```

If you plan to use website lookup profiles such as `no_email` or `all`, install the Chromium browser used by Playwright:

```bash
uv run playwright install chromium
```

## Quick start examples

### Find businesses without websites

```bash
cd Lead-Scraper-Google-Maps
uv run python main.py \
  --city "Lahore" \
  --depth areas \
  --categories plumbers electricians dentists \
  --profile no_website
```

### Safe first run

```bash
cd Lead-Scraper-Google-Maps
uv run python main.py \
  --city "Lahore" \
  --depth city \
  --categories plumbers \
  --profile no_website \
  --max-results 20
```

### Run without the TUI

```bash
cd Lead-Scraper-Google-Maps
uv run python main.py \
  --city "Lahore" \
  --depth areas \
  --categories plumbers \
  --profile no_website \
  --headless --no-tui -y
```

## Lead profiles

The main built-in profiles are:

- `no_website` — businesses missing a website
- `no_email` — businesses missing a discoverable email
- `all` — export all discovered businesses

A `no_website` lead usually qualifies when:

- the business has no website listed on Google Maps
- a phone number is present by default
- the rating is at least `3.0`
- the review count is at least `5`

You can override defaults with flags such as `--no-require-phone`, `--min-rating`, and `--min-reviews`.

## Search depth

The scraper supports three strategies:

- `city` — one search per category, good for quick tests
- `areas` — discover neighborhoods and search each area, best for most real runs
- `grid` — grid across a city or region, useful for dense metros

## Output

The scraper writes output into the `output/` directory by default unless you set `--output`.

Common files:

- `leads_raw.csv` — all unique businesses found
- `leads_qualified.csv` — businesses matching the selected profile
- `leads.xlsx` — combined raw + qualified data
- `progress.json` — resume state
- `seen_keys.json` — deduplication state
- `checkpoints/` — crash-safe recovery data
- `scraper.log` — detailed logs

## Resume and recovery

Runs are designed to be resumable:

- completed searches are skipped on restart
- active searches checkpoint progress to avoid reprocessing everything
- repeated runs can continue without restarting the entire scrape

Use `--no-resume` only when you intentionally want a fresh run.

## CLI and configuration

This project exposes a wizard-driven CLI and a large set of flags for search planning, qualification, and runtime behavior. Common examples:

```bash
uv run python main.py --list-categories
uv run python main.py --metro "New York" --depth areas --categories dentists --profile no_website
uv run python main.py --city "Austin TX" --depth grid --grid 3x3 --grid-span 20 --categories roofing --profile no_website
```

Environment variables follow the `SCRAPER_` naming pattern. For example:

```bash
export SCRAPER_MIN_RATING=4.0
export SCRAPER_OUTPUT_DIR=./my-leads
export SCRAPER_HEADLESS=true
```

## Docker

```bash
docker compose up --build
```

Or run a single command through the container:

```bash
docker compose run --rm scraper \
  python main.py --city "Austin TX" --depth areas \
  --categories plumbers --profile no_website --headless -y
```

## Testing

The project includes offline tests for parsing, geolocation, deduplication, runner recovery, and output generation.

```bash
cd Lead-Scraper-Google-Maps
uv run pytest
```

## Responsible use

Review Google Maps Platform terms, Places API policies, pricing, and applicable privacy or outreach rules before collecting or contacting businesses. Respect opt-outs and keep request rates reasonable.

## Support

If you find this project useful, you can [buy me a coffee on Ko-fi](https://ko-fi.com/telzeez). Thank you for your support!

## License

Released under the MIT License.
