"""Storing files attached to a booking.

A document is either a link to wherever the file already lives, or a file
stored under `data/docs/`. This module owns the stored-file half: deciding
where a file may go, what it may be called, and what it is allowed to contain.

The rules here are not paranoia for its own sake. These files are written by an
upload and then served back over HTTP from the same origin as the app, and the
published ones are served from a GitHub Pages site that anybody can read. Both
of those turn an ordinary filename into an attack surface.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

from .config import DOCS_DIR, PRIVATE_DOCS_DIR

log = logging.getLogger("trip.documents")

#: Hard cap per file. Generous enough for a scanned multi-page itinerary -- the
#: ones on this trip run to 15 MB -- without letting an upload fill the disk.
MAX_BYTES = 25 * 1024 * 1024

#: Extensions allowed, by what the file is for.
#:
#: `.html`, `.htm`, `.svg` and `.xhtml` are deliberately absent. All four can
#: carry script, and a file served from the app's own origin runs with the
#: app's privileges, so uploading one would be stored cross-site scripting
#: against both localhost and the published site. An image or a PDF opened in
#: a browser cannot do that.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif",
    ".txt", ".md", ".csv",
    ".ics",
})

#: Content types matched against the extension, so a `.pdf` that is really an
#: HTML page is refused. Checked only when the browser sends one.
EXPECTED_TYPES: dict[str, tuple[str, ...]] = {
    ".pdf": ("application/pdf",),
    ".png": ("image/png",),
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".webp": ("image/webp",),
    ".gif": ("image/gif",),
    ".heic": ("image/heic", "image/heif"),
    ".heif": ("image/heic", "image/heif"),
    ".txt": ("text/plain",),
    ".md": ("text/markdown", "text/plain"),
    ".csv": ("text/csv", "text/plain", "application/vnd.ms-excel"),
    ".ics": ("text/calendar",),
}

#: Leading bytes every accepted binary format starts with. A file whose
#: extension and content type both say PDF but whose bytes say otherwise is
#: refused, because those two are supplied by the client and the bytes are not.
MAGIC: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_DOTS = re.compile(r"\.{2,}")


class DocumentError(ValueError):
    """An upload that cannot be stored, with a message safe to show a user."""


def safe_filename(raw: str) -> str:
    """Reduce a client-supplied filename to something safe to write.

    Only the final path component is considered, so `../../app/main.py` becomes
    `main.py` rather than escaping the documents folder. Accents are folded,
    anything outside `[A-Za-z0-9._-]` becomes a hyphen, and runs of dots are
    collapsed so a name cannot smuggle a traversal through normalisation.
    """
    tail = Path(raw.replace("\\", "/")).name
    folded = unicodedata.normalize("NFKD", tail)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    cleaned = _UNSAFE.sub("-", folded).strip("-._")
    cleaned = _DOTS.sub(".", cleaned)
    if not cleaned or cleaned.startswith("."):
        raise DocumentError("That filename has nothing usable in it.")
    return cleaned[:120]


def check_extension(filename: str) -> str:
    """Return the lowercased extension, or refuse it."""
    suffix = Path(filename).suffix.lower()
    if not suffix:
        raise DocumentError("That file has no extension, so its type is unknown.")
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise DocumentError(
            f"{suffix} files are not accepted. Allowed: {allowed}. "
            "HTML and SVG are excluded because they can carry script."
        )
    return suffix


def check_declared_type(suffix: str, content_type: str | None) -> None:
    """Refuse a content type that contradicts the extension."""
    if not content_type:
        return
    base = content_type.split(";")[0].strip().lower()
    if base in ("application/octet-stream", ""):
        return
    expected = EXPECTED_TYPES.get(suffix)
    if expected and base not in expected:
        raise DocumentError(
            f"That file says it is {base} but is named {suffix}. "
            "Rename it to match what it actually is."
        )


def check_magic(suffix: str, head: bytes) -> None:
    """Refuse content whose leading bytes contradict the extension."""
    signatures = MAGIC.get(suffix)
    if not signatures:
        return
    if not any(head.startswith(sig) for sig in signatures):
        raise DocumentError(
            f"The contents of that file do not look like {suffix}. "
            "It may have been renamed from something else."
        )


def folder_for(booking_id: int, publish: bool) -> Path:
    """Where a booking's files live, by whether they are published.

    The flag maps onto a real directory rather than being only a database
    column, so what it claims matches what git does: `data/docs/` is committed,
    `data/docs/private/` is gitignored.
    """
    root = DOCS_DIR if publish else PRIVATE_DOCS_DIR
    return root / str(int(booking_id))


def unique_path(folder: Path, filename: str) -> Path:
    """A free path in `folder`, suffixing `-2`, `-3` ... on collision.

    Overwriting silently would lose a document that something already links
    to, so two uploads of `ticket.pdf` become `ticket.pdf` and `ticket-2.pdf`.
    """
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = folder / filename
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def store(
    booking_id: int,
    filename: str,
    payload: bytes,
    publish: bool,
    content_type: str | None = None,
) -> tuple[Path, int]:
    """Validate and write one uploaded document. Returns its path and size.

    Order matters: everything cheap and refusable is checked before anything
    is written, so a rejected upload leaves nothing behind.
    """
    if not payload:
        raise DocumentError("That file is empty.")
    if len(payload) > MAX_BYTES:
        raise DocumentError(
            f"That file is {len(payload) / 1_048_576:.1f} MB. "
            f"The limit is {MAX_BYTES // 1_048_576} MB."
        )

    clean = safe_filename(filename)
    suffix = check_extension(clean)
    check_declared_type(suffix, content_type)
    check_magic(suffix, payload[:16])

    folder = folder_for(booking_id, publish)
    folder.mkdir(parents=True, exist_ok=True)
    target = unique_path(folder, clean)

    # Write to a sibling first, then move, so an interrupted upload cannot
    # leave a half-written file that looks complete.
    staging = target.with_name(f".{target.name}.part")
    staging.write_bytes(payload)
    staging.replace(target)

    log.info(
        "Stored %s for booking %d (%.1f KB, %s)",
        target.name, booking_id, len(payload) / 1024,
        "published" if publish else "local only",
    )
    return target, len(payload)


def resolve(booking_id: int, filename: str, publish: bool) -> Path | None:
    """The stored path for a document, or None if it is not where it claims.

    Resolved and then checked to be inside the expected folder, so a filename
    that survived into the database before these rules existed still cannot
    read something outside it.
    """
    folder = folder_for(booking_id, publish).resolve()
    try:
        candidate = (folder / Path(filename).name).resolve()
        candidate.relative_to(folder)
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


def delete(booking_id: int, filename: str, publish: bool) -> bool:
    """Remove a stored file. Missing is success: the end state is what matters."""
    target = resolve(booking_id, filename, publish)
    if target is None:
        return False
    try:
        target.unlink()
    except OSError as exc:  # noqa: BLE001 - a failed unlink is not fatal
        log.warning("Could not delete %s: %s", target, exc)
        return False
    # Tidy up an emptied booking folder.
    folder = target.parent
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return True


def move(booking_id: int, filename: str, from_publish: bool, to_publish: bool) -> str | None:
    """Move a file between the published and private folders.

    Returns the new filename, which can differ if the destination already had
    one by that name.
    """
    source = resolve(booking_id, filename, from_publish)
    if source is None:
        return None
    folder = folder_for(booking_id, to_publish)
    folder.mkdir(parents=True, exist_ok=True)
    target = unique_path(folder, source.name)
    source.replace(target)
    if source.parent.is_dir() and not any(source.parent.iterdir()):
        source.parent.rmdir()
    log.info(
        "Moved %s for booking %d to %s",
        target.name, booking_id, "published" if to_publish else "local only",
    )
    return target.name


# ------------------------------------------------------------------ manifest


#: Committed record of which documents belong to which booking.
#:
#: The files themselves live under `data/docs/`, but what each one is called
#: and which booking it belongs to lived only in `data/trip.db` -- which is
#: gitignored, and which the static build throws away in favour of a freshly
#: seeded copy. Published files were therefore being copied into the site with
#: nothing linking to them.
#:
#: Bookings are already defined in committed code (`app/seed.py`), so their
#: documents are recorded the same way: in a file that travels with the repo
#: and is replayed into the database after seeding.
MANIFEST = DOCS_DIR / "manifest.json"

#: Bookings are keyed by title rather than by row id. Ids come from seed order
#: and would silently repoint every document if a stop were added to the
#: itinerary; a title is what a human would use to find the booking again.
_KEY_TRIM = re.compile(r"\s+")


def manifest_key(title: str) -> str:
    return _KEY_TRIM.sub(" ", (title or "").strip()).lower()


def read_manifest() -> dict[str, list[dict]]:
    """Load the committed manifest. A missing or broken file is not fatal."""
    if not MANIFEST.is_file():
        return {}
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Ignoring unreadable %s: %s", MANIFEST.name, exc)
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(k): [d for d in v if isinstance(d, dict)]
        for k, v in payload.get("bookings", payload).items()
        if isinstance(v, list)
    }


def write_manifest(entries: dict[str, list[dict]]) -> None:
    """Replace the manifest.

    Private files are deliberately absent: the manifest is committed, so
    listing a gitignored file would publish its name, its label and which
    booking it belongs to even though the file itself stayed behind.
    """
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "_comment": (
            "Published booking documents, written by the app. Committed so "
            "the static build knows what to link to. Files held back from "
            "publishing are not listed here."
        ),
        "bookings": {k: v for k, v in sorted(entries.items()) if v},
    }
    MANIFEST.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
