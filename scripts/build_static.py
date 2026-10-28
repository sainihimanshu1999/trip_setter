"""Render the dashboard into a folder of static files for GitHub Pages.

GitHub Pages runs no Python, so the server's half of the work has to happen
ahead of time. This drives the real app through FastAPI's TestClient (no
network, no port) and saves what it renders:

    dist/index.html      <- /
    dist/journey.html    <- /journey
    dist/bookings.html   <- /bookings
    dist/api/*.json      <- the endpoints the pages fetch after first paint
    dist/static/**       <- css and js, copied verbatim

Three rewrites make the output portable:

* `/static/...` and `/journey` become *relative* links, so the site works at
  `user.github.io/trip_setter/` as well as at a domain root or over file://.
* the one runtime `fetch('/api/expenses?limit=14')` is pointed at the saved
  JSON instead.
* a `data-static` marker on <html> tells the frontend it has no server, which
  hides the booking editor and swaps Refresh for the upload panel.

Usage:
    python scripts/build_static.py [--out dist] [--repo owner/name]

`--repo` (or GITHUB_REPOSITORY, which Actions sets for free) prefills the
upload panel so you do not have to type the repo in the browser.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

#: Page routes to render, and the filename each becomes.
PAGES = {
    "/": "index.html",
    "/journey": "journey.html",
    "/bookings": "bookings.html",
}

#: Endpoints to snapshot. The dashboard fetches expenses after first paint;
#: the rest are saved so the site is inspectable and future client-side work
#: has data to read.
ENDPOINTS = {
    "/api/overview": "overview.json",
    "/api/people": "people.json",
    "/api/categories": "categories.json",
    "/api/modes": "modes.json",
    "/api/timeline": "timeline.json",
    "/api/settlements": "settlements.json",
    "/api/journey": "journey.json",
    "/api/places": "places.json",
    "/api/legs": "legs.json",
    "/api/bookings": "bookings.json",
    "/api/meta": "meta.json",
    "/api/expenses?limit=14": "expenses.json",
    "/api/expenses?limit=500": "expenses-all.json",
}

#: Route -> output file, used to rewrite nav links.
LINK_REWRITES = {
    'href="/"': 'href="index.html"',
    'href="/journey"': 'href="journey.html"',
    'href="/bookings"': 'href="bookings.html"',
}


def _rewrite(html: str, repo: str) -> str:
    """Make one page's HTML work as a file served from any subpath."""
    # Assets: /static/x -> static/x. Covers href, src and url().
    html = html.replace('"/static/', '"static/').replace("'/static/", "'static/")

    # Nav links to sibling files.
    for before, after in LINK_REWRITES.items():
        html = html.replace(before, after)

    # The dashboard's post-paint fetch.
    html = html.replace("'/api/expenses?limit=14'", "'api/expenses.json'")

    # Tell the frontend there is no server behind it, and which repo the
    # upload panel should commit to.
    html = html.replace(
        "<html lang=\"en\">",
        f'<html lang="en" data-static="1" data-repo="{repo}">',
        1,
    )

    # /docs needs a running FastAPI, so drop the footer link to it.
    html = re.sub(
        r'\s*<a href="/docs"[^>]*>.*?</a>', "", html, flags=re.S
    )
    return html


def build(out_dir: Path, repo: str) -> dict:
    """Render everything into `out_dir`. Returns a small report."""
    # A throwaway database, so a stale local trip.db cannot leak into the
    # build and the itinerary is always freshly seeded from seed.py.
    tmp = Path(tempfile.mkdtemp(prefix="trip-build-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'build.db'}"
    os.environ.setdefault("SPLITWISE_CSV_PATH", "data/expenses.csv")
    os.environ["AUTO_SEED"] = "true"

    # Imported after the environment is set, because settings are read once.
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    settings = get_settings()
    report = {
        "source": settings.data_source,
        "csv": str(settings.resolved_csv_path or ""),
        "pages": [],
        "endpoints": [],
    }

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "api").mkdir(parents=True)

    with TestClient(app) as client:
        for route, filename in PAGES.items():
            response = client.get(route)
            response.raise_for_status()
            (out_dir / filename).write_text(
                _rewrite(response.text, repo), encoding="utf-8"
            )
            report["pages"].append(filename)

        for route, filename in ENDPOINTS.items():
            response = client.get(route)
            response.raise_for_status()
            (out_dir / "api" / filename).write_text(
                json.dumps(response.json(), separators=(",", ":")),
                encoding="utf-8",
            )
            report["endpoints"].append(filename)

    shutil.copytree(BASE_DIR / "app" / "static", out_dir / "static")

    # Stops Pages running the output through Jekyll, which would drop files
    # whose names begin with an underscore.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    shutil.rmtree(tmp, ignore_errors=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist", help="output folder")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help='"owner/name", prefills the upload panel',
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = BASE_DIR / out_dir

    report = build(out_dir, args.repo)

    print(f"data source : {report['source']}")
    if report["csv"]:
        print(f"csv         : {report['csv']}")
    print(f"repo        : {args.repo or '(not set, panel will ask)'}")
    print(f"pages       : {', '.join(report['pages'])}")
    print(f"endpoints   : {len(report['endpoints'])} json files")
    print(f"output      : {out_dir}")

    if report["source"] == "demo":
        print(
            "\nNote: built from the bundled sample data. Put your export at "
            "data/expenses.csv to build from real figures.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
