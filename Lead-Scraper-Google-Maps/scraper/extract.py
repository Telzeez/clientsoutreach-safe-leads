"""Extract contact links and text from a business website."""

import logging

from playwright.async_api import Page

logger = logging.getLogger(__name__)

WEBSITE_JS = r"""
() => {
  const out = { emails: [], links: [] };
  try {
    document.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href') || '';
      if (href.toLowerCase().startsWith('mailto:')) out.emails.push(href);
      else if (href.startsWith('http') || href.startsWith('//')) out.links.push(href);
    });
  } catch (e) {}
  try {
    out.text = (document.body ? document.body.innerText : '') || '';
  } catch (e) { out.text = ''; }
  return out;
}
"""


async def extract_website_contacts(page: Page) -> dict:
    """Pull mailto links, outbound links and page text from a business website."""
    try:
        return await page.evaluate(WEBSITE_JS)
    except Exception as exc:
        logger.debug("Website extraction failed: %s", exc)
        return {"emails": [], "links": [], "text": ""}
