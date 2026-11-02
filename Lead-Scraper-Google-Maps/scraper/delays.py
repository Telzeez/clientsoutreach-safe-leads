"""Pacing between Google Maps Platform search units."""

import asyncio
import random

from config.settings import SEARCH_DELAY_MAX, SEARCH_DELAY_MIN


async def search_delay() -> None:
    """Wait a randomized interval between search units."""
    await asyncio.sleep(random.uniform(SEARCH_DELAY_MIN, SEARCH_DELAY_MAX))
