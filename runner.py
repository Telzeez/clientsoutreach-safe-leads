"""Run orchestration: resolve the target, plan the searches, execute them.

``main.py`` stays a thin entry point; everything about *how* a run proceeds
lives here.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from config import settings
from config.enums import Depth
from config.runconfig import RunConfig
from data.dedup import Deduplicator
from data.exporter import Exporter, get_csv_row_count
from data.models import Business
from data.qualifier import is_qualified_lead
from geo.models import SearchUnit, Target
from geo.plan import build_search_plan
from geo.resolver import discover_subareas, resolve_target
from persistence.checkpoint import CheckpointStore
from persistence.progress import ProgressTracker
from reporting import Reporter, RunStats
from scraper.browser import BrowserManager
from scraper.delays import search_delay
from scraper.google_places import GoogleMapsAPIError, GoogleMapsClient
from scraper.maps_scraper import UnitResult, search_and_scrape

logger = logging.getLogger(__name__)


@dataclass
class Worker:
    """One API worker and its optional website-lookup browser context."""

    name: str
    browser: BrowserManager
    page: Any = None
    detail_visits: int = 0
    owns_browser: bool = True


class ScraperRun:
    """Executes one full scraping run."""

    def __init__(self, cfg: RunConfig, reporter: Reporter | None = None):
        self.cfg = cfg
        self.reporter = reporter or Reporter()
        self.stats = RunStats()

        cfg.output.ensure()
        self.progress = ProgressTracker(cfg.output)
        self.checkpoints = CheckpointStore(cfg.output)
        self.dedup = Deduplicator(cfg.output)
        self.exporter = Exporter(cfg.output)

        self.browser = BrowserManager(headless=cfg.headless, proxy=cfg.proxy_dict())
        self.maps_api: GoogleMapsClient | None = None
        self.target: Target | None = None
        self.units: list[SearchUnit] = []
        self._workers: list[Worker] = []

    # --- Business handling --------------------------------------------------

    def _handle_business(self, business: Business) -> None:
        """Deduplicate, export, and count a business returned by the API.

        Safe to call from several workers: asyncio is single-threaded and this
        function never awaits, so it runs to completion atomically.
        """
        self.stats.found += 1

        if self.dedup.is_duplicate(business):
            self.stats.duplicates += 1
            self.reporter.on_business(business, unique=False, qualified=False)
            return

        self.dedup.mark_seen(business)
        self.stats.unique += 1
        self.exporter.add_raw(business)

        qualified = is_qualified_lead(
            business,
            profile=self.cfg.profile,
            min_rating=self.cfg.min_rating,
            min_reviews=self.cfg.min_reviews,
            require_phone=self.cfg.require_phone,
        )
        if qualified:
            self.stats.qualified += 1
            self.exporter.add_qualified(business)

        self.reporter.on_business(business, unique=True, qualified=qualified)

    # --- Planning -----------------------------------------------------------

    async def _build_plan(self) -> list[SearchUnit]:
        self.reporter.on_phase(f"Resolving '{self.cfg.target_input}'...")
        if self.maps_api is None:
            raise RuntimeError("Google Maps API client has not been initialized.")
        self.target = await resolve_target(self.maps_api, self.cfg.target_input)

        if self.cfg.crawl_websites and self.target.has_coords:
            self.browser.set_region(self.target.lng)

        areas: list[str] = []
        if self.cfg.depth is Depth.AREAS:
            self.reporter.on_phase("Discovering sub-areas from Places API...")
            areas, _probe = await discover_subareas(
                self.maps_api,
                self.target,
                self.cfg,
                probe_category=self.cfg.categories[0],
                on_business=self._handle_business,
            )
            if areas:
                self.reporter.on_log(
                    f"Sub-areas: {', '.join(areas[:10])}"
                    + (f" (+{len(areas) - 10} more)" if len(areas) > 10 else "")
                )

        return build_search_plan(
            self.target,
            self.cfg.categories,
            self.cfg.depth,
            areas=areas,
            grid_rows=self.cfg.grid_rows,
            grid_cols=self.cfg.grid_cols,
            grid_span_km=self.cfg.grid_span_km,
            grid_zoom=self.cfg.grid_zoom,
        )

    # --- Unit execution -----------------------------------------------------

    async def _scrape_unit(self, worker: Worker, unit: SearchUnit, index: int) -> UnitResult:
        self.reporter.on_unit_start(unit, index, len(self.units))

        done_hrefs = self.checkpoints.load_done(unit.key) if self.cfg.resume else set()
        unit_found = 0
        unique_before = self.stats.unique
        qualified_before = self.stats.qualified
        # Seeded with what a previous run already did, then grown live so a
        # mid-unit checkpoint reflects real progress rather than an empty set.
        processed = set(done_hrefs)

        def on_business(business: Business):
            nonlocal unit_found
            unit_found += 1
            self._handle_business(business)

        def on_progress(done: int, total: int):
            self.reporter.on_unit_progress(done, total)
            # Checkpoint periodically so a crash costs one result, not the unit.
            if done % max(1, settings.CHECKPOINT_EVERY) == 0:
                self.checkpoints.save_done(unit.key, processed)
                self.exporter.flush()

        result = await search_and_scrape(
            worker.page,
            unit,
            self.cfg,
            maps_api=self.maps_api,
            on_business=on_business,
            on_progress=on_progress,
            on_processed=processed.add,
            skip_hrefs=done_hrefs,
        )

        worker.detail_visits += result.found
        self.reporter.on_unit_end(
            unit,
            found=unit_found,
            unique=self.stats.unique - unique_before,
            qualified=self.stats.qualified - qualified_before,
        )
        return result

    async def _process_unit(self, worker: Worker, unit: SearchUnit, index: int) -> None:
        """Run one unit and update its progress bookkeeping."""
        self.progress.mark_in_progress(unit.key)

        try:
            await self._scrape_unit(worker, unit, index)
        except asyncio.CancelledError:
            raise
        except GoogleMapsAPIError as exc:
            self.stats.units_failed += 1
            self.progress.mark_failed(unit.key)
            self.reporter.on_log(f"FAILED {unit.label}: {exc}", level="error")
            raise
        except Exception as exc:
            logger.exception(f"Unit failed: {unit.label}")
            self.stats.units_failed += 1
            self.progress.mark_failed(unit.key)
            self.reporter.on_log(f"FAILED {unit.label}: {exc}", level="error")
            if self.cfg.crawl_websites:
                try:
                    worker.page = await worker.browser.new_context()
                    worker.detail_visits = 0
                except Exception:
                    pass
            return

        self.stats.units_done += 1
        self.progress.mark_completed(unit.key)
        self.checkpoints.clear(unit.key)

        self.exporter.flush()

        if (
            self.cfg.crawl_websites
            and worker.detail_visits >= settings.CONTEXT_REFRESH_EVERY
        ):
            self.reporter.on_log(f"[{worker.name}] Refreshing browser context...")
            worker.page = await worker.browser.new_context()
            worker.detail_visits = 0

    def _should_skip(self, unit: SearchUnit) -> bool:
        if self.cfg.resume and self.progress.is_completed(unit.key):
            self.stats.units_skipped += 1
            self.reporter.on_log(f"Skipping (already done): {unit.label}")
            self.reporter.refresh()
            return True
        return False

    # --- Execution strategies -----------------------------------------------

    async def _run_sequential(self, worker: Worker) -> None:
        for index, unit in enumerate(self.units, start=1):
            if self._should_skip(unit):
                continue
            await self._process_unit(worker, unit, index)
            if index < len(self.units):
                await search_delay()

    async def _run_pool(self, primary: Worker) -> None:
        """Run search units across several workers in parallel."""
        queue: asyncio.Queue = asyncio.Queue()
        for index, unit in enumerate(self.units, start=1):
            if not self._should_skip(unit):
                queue.put_nowait((index, unit))

        self._workers = [primary]
        for n in range(1, self.cfg.concurrency):
            if not self.cfg.crawl_websites:
                self._workers.append(Worker(
                    name=f"w{n + 1}",
                    browser=self.browser,
                    page=None,
                    owns_browser=False,
                ))
                continue
            browser = BrowserManager(
                headless=self.cfg.headless, proxy=self.cfg.proxy_dict()
            )
            if self.target and self.target.has_coords:
                browser.set_region(self.target.lng)
            page = await browser.start()
            self._workers.append(Worker(name=f"w{n + 1}", browser=browser, page=page))

        self.reporter.on_log(f"Running {len(self._workers)} search workers in parallel.")

        async def consume(worker: Worker):
            while True:
                try:
                    index, unit = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await self._process_unit(worker, unit, index)
                finally:
                    queue.task_done()
                await search_delay()

        tasks = [asyncio.create_task(consume(w)) for w in self._workers]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            # One worker aborting (or Ctrl-C) must not leave the others running.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    # --- State --------------------------------------------------------------

    def _save_state(self) -> None:
        """Flush every piece of durable state. Each step guarded separately so
        one failure cannot skip the rest."""
        for label, action in (
            ("flush CSVs", self.exporter.flush),
            ("save dedup", self.dedup.save),
            ("save progress", self.progress.save),
        ):
            try:
                action()
            except Exception as exc:
                logger.error(f"Could not {label}: {exc}")

    async def _shutdown_workers(self) -> None:
        for worker in self._workers:
            if worker.owns_browser and worker.browser is not self.browser:
                try:
                    await worker.browser.close()
                except Exception as exc:
                    logger.debug(f"Closing {worker.name} failed: {exc}")
        self._workers = []

    # --- Main loop ----------------------------------------------------------

    async def execute(self) -> RunStats:
        self.reporter.start(self.stats)
        aborted: str | None = None

        try:
            self.maps_api = GoogleMapsClient()
            self.units = await self._build_plan()
            self.stats.total_units = len(self.units)
            self.reporter.on_plan(self.units)

            if not self.units:
                self.reporter.on_log("Nothing to scrape — empty plan.", level="warning")
                return self.stats

            page = await self.browser.start() if self.cfg.crawl_websites else None
            primary = Worker(name="w1", browser=self.browser, page=page)
            if self.cfg.concurrency > 1:
                await self._run_pool(primary)
            else:
                self._workers = [primary]
                await self._run_sequential(primary)

        except GoogleMapsAPIError as exc:
            aborted = f"Google Maps API error: {exc}"
            logger.error(aborted)
        except (KeyboardInterrupt, asyncio.CancelledError):
            aborted = "Interrupted by user."
            logger.warning(aborted)
        finally:
            # Everything here must run even on Ctrl-C.
            self._save_state()
            try:
                self.exporter.export_xlsx()
            except Exception as exc:
                logger.debug(f"XLSX export skipped: {exc}")
            await self._shutdown_workers()
            try:
                await self.browser.close()
            except Exception as exc:
                logger.debug(f"Browser close failed: {exc}")
            self.reporter.stop()

        self.stats.aborted_reason = aborted
        return self.stats

    # --- Summary ------------------------------------------------------------

    def summary(self) -> dict:
        return {
            "target": self.target.query if self.target else self.cfg.target_input,
            "depth": self.cfg.depth.value,
            "profile": self.cfg.profile.value,
            "units_total": self.stats.total_units,
            "units_done": self.stats.units_done,
            "units_failed": self.stats.units_failed,
            "units_skipped": self.stats.units_skipped,
            "found": self.stats.found,
            "unique": self.stats.unique,
            "duplicates": self.stats.duplicates,
            "qualified": self.stats.qualified,
            "raw_rows": get_csv_row_count(self.cfg.output.leads_raw_csv),
            "qualified_rows": get_csv_row_count(self.cfg.output.leads_qualified_csv),
            "dedup_pool": self.dedup.total_seen,
            "elapsed": self.stats.elapsed,
        }
