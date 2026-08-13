"""
Paper text lookup with fallbacks.

For a given (geo_id, pmcid) we try, in order:
  1. processed_papers.json  (the bulk-extracted text from 06_chunk_papers.py)
  2. downloaded_papers/<geo_id>.txt   (e.g. from the Elsevier TDM API)
  3. downloaded_papers/<geo_id>.html  (e.g. saved via Playwright)
  4. Elsevier TDM API live fetch by DOI (if elsevier_api_key is set)

Public API:
    paper_text_lookup(base_dir).get(geo_id, pmcid=None, doi=None)
    fetch_elsevier_text(doi) -> str | None
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


min_usable_chars = 5_000


def looks_like_full_paper_text(text: str) -> bool:
    """Reject metadata/abstract-only responses masquerading as full text."""
    if len(text) < min_usable_chars:
        return False
    low = text.lower()
    section_hits = sum(
        marker in low
        for marker in ("introduction", "methods", "results", "discussion", "references")
    )
    return len(text) >= 20_000 or section_hits >= 2


def fetch_elsevier_text(doi: str, api_key: Optional[str] = None) -> Optional[str]:
    """Pull full-text from Elsevier's TDM API by DOI.

    Returns the plain-text body or None on failure. Requires
    elsevier_api_key env var (or pass api_key explicitly).
    """
    if not doi:
        return None
    key = api_key or os.environ.get("elsevier_api_key", "")
    if not key:
        return None
    url = f"https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}"
    req = urllib.request.Request(url, headers={
        "X-ELS-APIKey": key,
        "Accept": "text/plain",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            content = r.read().decode("utf-8", errors="replace")
        if looks_like_full_paper_text(content):
            return content
        return None
    except Exception as e:
        print(f"  elsevier API failed for {doi}: {e}")
        return None


class paper_text_lookup:
    """Caches paper text from processed_papers.json + local files, with API fallback."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.papers_dir = self.base_dir / "downloaded_papers"
        self.processed_path = self.base_dir / "processed_papers.json"
        self.by_pmcid: dict[str, str] = {}
        self.loaded = False

    def load_processed(self) -> None:
        if self.loaded:
            return
        if self.processed_path.exists():
            with open(self.processed_path, encoding="utf-8") as f:
                data = json.load(f)
            for p in data:
                pmcid = p.get("pmcid", "")
                if pmcid:
                    self.by_pmcid[pmcid] = " ".join(p.get("chunks", []))
        self.loaded = True

    def try_local_text_file(self, geo_id: str) -> Optional[str]:
        """Look for downloaded_papers/<geo_id>.txt or .html (e.g. Elsevier API saves
        or Playwright HTML scrapes). For .html, run the same text extractor we
        use for the bulk pipeline."""
        # plain text first
        txt = self.papers_dir / f"{geo_id}.txt"
        if txt.exists():
            text = " ".join(txt.read_text(encoding="utf-8", errors="replace").split())
            if len(text) >= min_usable_chars:
                return text

        # html via beautifulsoup
        html = self.papers_dir / f"{geo_id}.html"
        if html.exists():
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html.read_text(encoding="utf-8", errors="replace"), "html.parser")
                article = soup.find("article") or soup.find("main") or soup
                for tag in article.find_all(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                text = " ".join(article.get_text(" ", strip=True).split())
                if len(text) >= min_usable_chars:
                    return text
            except Exception as e:
                print(f"  html parse failed for {html.name}: {e}")
        return None

    def get(
        self,
        geo_id: str,
        pmcid: Optional[str] = None,
        doi: Optional[str] = None,
        try_elsevier: bool = True,
    ) -> str:
        """Best-effort paper text lookup. Returns '' if nothing usable found.

        Args:
            geo_id: the GSE identifier (used for local file fallback)
            pmcid:  PubMed Central ID for processed_papers.json lookup
            doi:    DOI for Elsevier API fallback
            try_elsevier: live API fetch when local lookups fail
        """
        # 1. processed_papers.json (bulk-extracted)
        if pmcid:
            self.load_processed()
            text = self.by_pmcid.get(pmcid, "")
            if len(text) >= min_usable_chars:
                return text

        # 2/3. local text/html file (saved by Elsevier API or Playwright)
        local = self.try_local_text_file(geo_id)
        if local:
            return local

        # 4. live Elsevier API fetch
        if try_elsevier and doi:
            fetched = fetch_elsevier_text(doi)
            if fetched:
                # cache to disk so we don't re-fetch
                out = self.papers_dir / f"{geo_id}.txt"
                try:
                    out.write_text(fetched, encoding="utf-8")
                    print(f"  cached elsevier fetch: {out}")
                except Exception:
                    pass
                return " ".join(fetched.split())

        return ""
