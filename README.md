# Safe Lead Scraper from Google Maps

Version 1.0

An async, resumable Google Maps lead scraper that uses Google Places and
Geocoding APIs to find businesses, qualify leads, and export CSV and Excel
files. It includes a guided CLI, terminal dashboard, crash-safe resume, and
optional website contact lookup.

## Setup

Install dependencies from the repository root with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
```

Set your Google Maps Platform API key:

```bash
export SCRAPER_GOOGLE_MAPS_API_KEY="your-key"
```

PowerShell:

```powershell
$env:SCRAPER_GOOGLE_MAPS_API_KEY = "your-key"
```

Enable Places API (New) and Geocoding API in your Google Cloud project, and
review the applicable billing, quota, and API policies. Do not commit the API
key.

For optional website contact lookup, install Chromium:

```bash
uv run playwright install chromium
```

## Run

Start the guided setup:

```bash
uv run python main.py
```

Or run a search directly:

```bash
uv run python main.py \
  --city "Lahore" \
  --depth areas \
  --categories plumbers electricians dentists \
  --profile no_website \
  -y
```

The default `no_website` profile finds businesses whose Maps listing has no
website. Search depth can be `city`, `areas`, or `grid`; lead profiles include
`no_website`, `no_email`, and `all`. Results and resume state are written to
`output/` by default. Use `--help` for CLI options.

## Tests

Run the offline test suite:

```bash
uv run pytest
```

## Support

If you find this project useful, you can
[buy me a coffee on Ko-fi](https://ko-fi.com/telzeez). Thank you for your support!

## Responsible use

Review Google Maps Platform terms, API policies and pricing, and applicable
privacy and outreach rules before use. Respect opt-outs and keep request rates
reasonable.

## License

Released under the [MIT License](LICENSE).
