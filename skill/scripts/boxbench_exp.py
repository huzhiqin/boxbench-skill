#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
boxbench_exp — BoxBench Commons client.

Zero third-party dependencies (matches the rest of the skill: bash + python3 only).

Responsibilities:
  1. Pull the public Commons digest for a platform key and cache it locally.
  2. Build experience atoms from a finished boxbench result JSON.
  3. Sanitize every string before it can leave the machine (offline-first).
  4. Push atoms to the Commons, with retry, from a local outbox.

Contribution is ON by default with an explicit opt-out:
    BOXBENCH_CONTRIBUTE=0     # disable uploads entirely
    BOXBENCH_COMMONS_URL=...  # override the endpoint
    BOXBENCH_PUBLISHER_TOKEN=...  # explicit token (else generated once, stored locally)

Commands (also usable as a library):
    pull   --platform <key> [--out <file>] [--min-trust N] [--force]
    push   --result <boxbench_result.json> [--model <name>] [--platform <key>]
    status
    flush                      # retry queued atoms from the outbox
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://aibox-capabilities.pages.dev/api/exp"
SCHEMA = "boxbench.experience/v1"
# Same rule as server gate G1; keeps client and server agreeing on valid keys.
_PLATFORM_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
HTTP_TIMEOUT = 20

# --------------------------------------------------------------------------- #
# Local state
# --------------------------------------------------------------------------- #

def state_dir() -> Path:
    override = os.environ.get("BOXBENCH_STATE_DIR")
    base = Path(override) if override else Path.home() / ".boxbench"
    base.mkdir(parents=True, exist_ok=True)
    return base


def credential_path() -> Path:
    return state_dir() / "credentials"


def publisher_token() -> str:
    """Read or create the local contributor token. Never leaves this file except
    in the Authorization header; it carries no personal information."""
    explicit = os.environ.get("BOXBENCH_PUBLISHER_TOKEN")
    if explicit:
        return explicit.strip()
    path = credential_path()
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = os.urandom(24).hex()
    path.write_text(token, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def commons_url() -> str:
    return os.environ.get("BOXBENCH_COMMONS_URL", DEFAULT_URL).rstrip("/")


def contribution_enabled() -> bool:
    return os.environ.get("BOXBENCH_CONTRIBUTE", "1").strip().lower() not in ("0", "false", "no", "off")


# --------------------------------------------------------------------------- #
# Canonical hashing (must match the server: sorted-key JSON, sha256)
# --------------------------------------------------------------------------- #

def canonical_json(value) -> str:
    return json.dumps(_sort_deep(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sort_deep(value):
    if isinstance(value, dict):
        return {k: _sort_deep(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sort_deep(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        # JCS/RFC 8785: a float with an integral value serializes without a
        # decimal point. JavaScript's JSON.stringify(0.0) is "0", so Python
        # must normalise the same way or client and server hash differently.
        return int(value)
    return value


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Publish these so callers do not need their own canonicalizer.
canon = canonical_json
sha256 = sha256_hex


# --------------------------------------------------------------------------- #
# Sanitization (client-side, defense in depth; server re-runs its own)
# --------------------------------------------------------------------------- #

_SAN_RULES = [
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    ("ipv6", re.compile(r"\b(?:[a-f0-9]{1,4}:){2,7}[a-f0-9]{1,4}\b", re.I), "<ipv6>"),
    ("mac", re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I), "<mac>"),
    ("cred_url", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@[^\s]*", re.I), "<credential-url>"),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*\b", re.I), "Bearer <redacted>"),
    ("sk_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "<api-key>"),
    ("gh_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "<api-key>"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "<jwt>"),
    ("passwd", re.compile(r"\b(?:password|passwd|pwd|secret|token)\s*[:=]\s*\S+", re.I), "<credential>"),
    ("home", re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\Users\\)([A-Za-z0-9._-]+)"), "<home>/<user>"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>"),
    ("host", re.compile(r"\b[a-z0-9][a-z0-9-]{2,}\.(?:local|lan|internal|corp|intra)\b", re.I), "<host>"),
]

_BLOB_RE = re.compile(r"\b[A-Za-z0-9+/_-]{40,256}\b")


def _entropy(text: str) -> float:
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    import math
    total = len(text)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def sanitize_string(text: str, hits=None) -> str:
    if hits is None:
        hits = set()
    out = text
    for key, pattern, repl in _SAN_RULES:
        def _sub(m, _key=key, _repl=repl):
            if _key == "ipv4" and re.match(r"^(?:127\.|0\.0\.0\.0)", m.group(0)):
                return m.group(0)
            hits.add(_key)
            return _repl
        out = pattern.sub(_sub, out)

    def _blob(m):
        tok = m.group(0)
        if re.search(r"\d", tok) and re.search(r"[A-Za-z]", tok) and _entropy(tok) >= 3.5:
            hits.add("entropy")
            return "<blob>"
        return tok
    out = _BLOB_RE.sub(_blob, out)
    return out


def sanitize_deep(value, hits=None):
    if hits is None:
        hits = set()
    if isinstance(value, str):
        return sanitize_string(value, hits)
    if isinstance(value, list):
        return [sanitize_deep(v, hits) for v in value]
    if isinstance(value, dict):
        return {k: sanitize_deep(v, hits) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------- #
# Evidence extraction (whitelist, mirrors the server's ALLOWED sets)
# --------------------------------------------------------------------------- #

_ALLOWED_PHASE_A = {"os", "kernel", "cpu_arch", "cpu_cores", "cpu_max_mhz", "mem_total",
                    "accelerator", "accel_tool", "blocks"}
_ALLOWED_ENGINE = {"engine_name", "engine_build", "ctx_size", "model_file_size", "model_quant"}
_ALLOWED_PHASE_C = {"c1_load_s", "c2_short_decode", "c3_ttft", "c4_long_ctx",
                    "c6c7_conc2", "c6c7_conc4", "c8_toolcall", "c9_multiturn", "c10_vram"}


def _pick(obj, allowed):
    if not isinstance(obj, dict):
        return {}
    return {k: v for k, v in obj.items() if k in allowed}


def build_evidence(result: dict, model_name: str | None = None) -> dict:
    evidence = {
        "boxbench_version": result.get("boxbench_version"),
        "spec_version": result.get("spec_version"),
        "timestamp": result.get("timestamp"),
        "phase_a": _pick(result.get("phase_a"), _ALLOWED_PHASE_A),
        "classification": _pick(result.get("classification"), {"tier", "infer_mem_gb"}),
    }
    models = result.get("models") if isinstance(result.get("models"), list) else None
    if models:
        target = None
        for m in models:
            if isinstance(m, dict) and m.get("name") == model_name:
                target = m
                break
        target = target or models[0]
    else:
        target = result
    if isinstance(target, dict):
        evidence["phase_c"] = _pick(target.get("phase_c"), _ALLOWED_PHASE_C)
        evidence["engine"] = _pick(target.get("engine"), _ALLOWED_ENGINE)
        evidence["model_name"] = target.get("name") or model_name
        if "c1_load_s" in target:
            evidence["c1_load_s"] = target["c1_load_s"]
    return evidence


def recompute_decode(evidence: dict):
    """Same formula as render_report.py: completion_tokens / wall_s."""
    c2 = (evidence.get("phase_c") or {}).get("c2_short_decode") or {}
    tokens = c2.get("completion_tokens")
    wall = c2.get("wall_s")
    if not isinstance(tokens, (int, float)) or not isinstance(wall, (int, float)) or wall <= 0:
        return None
    return round(tokens / wall, 2)


def make_atom(result: dict, platform_key: str, model_name: str | None = None, note: str | None = None) -> dict:
    evidence = sanitize_deep(build_evidence(result, model_name))
    decode = recompute_decode(evidence)
    model = evidence.get("model_name") or model_name or "unknown"
    quant = (evidence.get("engine") or {}).get("model_quant")
    engine = (evidence.get("engine") or {}).get("engine_name") or platform_key
    tier = (evidence.get("classification") or {}).get("tier")

    claim = {
        "type": "baseline" if decode is not None else "capability",
        "model": model,
        "quant": quant,
        "metric": "decode_tok_s" if decode is not None else None,
        "value": decode,
        "unit": "tok/s" if decode is not None else None,
        "text": None if decode is not None else f"ran on {platform_key}",
    }
    if decode is None:
        claim.pop("metric")
        claim.pop("value")
        claim.pop("unit")

    atom = {
        "schema": SCHEMA,
        "atom_id": "",
        "created_at": (result.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%S%z")),
        "platform_key": platform_key,
        "platform": {"engine": engine.split(" ")[0], "chip": _chip_of(evidence), "os": (evidence.get("phase_a") or {}).get("os")},
        "device_class": tier,
        "claim": claim,
        "note": note,
        "evidence": evidence,
        "evidence_hash": sha256(canonical_json(evidence)),
        "source": {"publisher_id": "local", "skill_version": _skill_version(), "spec_version": result.get("spec_version")},
    }
    atom["atom_id"] = _atom_id(atom)
    return atom


def _chip_of(evidence: dict) -> str:
    accel = (evidence.get("phase_a") or {}).get("accelerator") or ""
    m = re.search(r"mem=(\S+\s+\S+)", str(accel))
    return m.group(1) if m else str(accel)[:40] or "unknown"


def _skill_version() -> str:
    """Read the version from SKILL.md so provenance never goes stale."""
    try:
        skill = Path(__file__).resolve().parent.parent / "SKILL.md"
        for line in skill.read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def derive_platform_key(result: dict) -> str | None:
    """Infer the platform key (<engine>-<chip>) from a result JSON.

    The key must match what PLATFORM_NOTES.md indexes on, otherwise the pool
    forks into duplicate platforms. Rules, in order:
      1. First token of engine.engine_name (e.g. "houmo-HLIELLama-xh2 (...)").
      2. <engine>-<chip> if only a bare engine name is present.
    Returns None when nothing reliable can be derived, so the caller can ask
    the user instead of inventing a key.
    """
    def _engine_name(obj):
        if not isinstance(obj, dict):
            return None
        name = obj.get("engine_name")
        return name if isinstance(name, str) and name.strip() else None

    name = _engine_name(result.get("engine"))
    if not name:
        models = result.get("models")
        if isinstance(models, list):
            for m in models:
                if isinstance(m, dict):
                    name = _engine_name(m.get("engine"))
                    if name:
                        break
    if not name:
        return None

    key = name.strip().split()[0].strip(" ,")
    if not _PLATFORM_KEY_RE.match(key):
        return None
    return key


_ATOM_ID_FIELDS = ("platform_key", "created_at", "claim", "evidence_hash")


def _atom_id(atom: dict) -> str:
    """Content identity, independent of provenance.

    `source` is excluded on purpose: it is metadata (publisher, skill_version),
    not content. Including skill_version would mint a new atom_id whenever the
    client is upgraded, letting a re-publish slip past the server's G6 dedupe.
    """
    base = {k: atom.get(k) for k in _ATOM_ID_FIELDS}
    return sha256(canonical_json(base))


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def _request(method: str, url: str, body=None, headers=None) -> tuple[int, bytes, dict]:
    """Return (status, body, response_headers).

    Headers are returned so callers can persist ETag/Last-Modified and turn the
    next request into a cheap 304 instead of re-downloading the digest.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "boxbench-exp/1.0")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b"", {}


# --------------------------------------------------------------------------- #
# Outbox
# --------------------------------------------------------------------------- #

def outbox_dir() -> Path:
    d = state_dir() / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def enqueue(atom: dict) -> Path:
    path = outbox_dir() / f"{atom['atom_id'][:16]}.json"
    path.write_text(json.dumps(atom, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def queued() -> list[Path]:
    return sorted(outbox_dir().glob("*.json"))


def push_atoms(atoms: list[dict]) -> dict:
    if not atoms:
        return {"ok": True, "accepted": 0, "results": []}
    status, raw, _hdrs = _request(
        "POST",
        f"{commons_url()}/push",
        {"atoms": atoms},
        {"Authorization": f"Bearer {publisher_token()}"},
    )
    try:
        return json.loads(raw.decode("utf-8")) if raw else {"ok": False, "error": f"http {status}"}
    except json.JSONDecodeError:
        return {"ok": False, "error": f"http {status}: non-JSON response"}


def flush(max_retry: int = 3, batch_size: int = 20) -> dict:
    """Send queued atoms, batching them the way the server expects.

    The server accepts up to 20 atoms per request, so sending one atom per
    request turns an N-item outbox into N round trips (seconds each on a slow
    link). A batch is removed when the server has produced a verdict for every
    atom in it; a network failure keeps the whole batch for the next run.
    """
    if not contribution_enabled():
        return {"ok": True, "skipped": "contribution disabled"}
    sent, kept = 0, 0
    paths: list[Path] = []
    atoms: list[dict] = []
    for path in queued():
        try:
            atoms.append(json.loads(path.read_text(encoding="utf-8")))
            paths.append(path)
        except (json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)

    for start in range(0, len(atoms), batch_size):
        chunk = atoms[start:start + batch_size]
        chunk_paths = paths[start:start + batch_size]
        outcome = {"ok": False}
        for attempt in range(max_retry):
            outcome = push_atoms(chunk)
            if outcome.get("ok"):
                break
            time.sleep(2 ** attempt)
        results = outcome.get("results") or []
        if outcome.get("ok") and len(results) == len(chunk):
            # The server returned a verdict for every atom in the batch; whichever
            # status it chose, it now holds them, so the outbox copies are done.
            for p in chunk_paths:
                p.unlink(missing_ok=True)
            sent += len(chunk)
        elif outcome.get("ok") and results:
            # Partial verdicts: drop only the ones the server acknowledged.
            acknowledged = min(len(results), len(chunk))
            for p in chunk_paths[:acknowledged]:
                p.unlink(missing_ok=True)
            sent += acknowledged
            kept += len(chunk) - acknowledged
        else:
            # Network failure: keep the whole batch for the next run.
            kept += len(chunk)
    return {"ok": True, "sent": sent, "kept": kept}


# --------------------------------------------------------------------------- #
# Commons -> PLATFORM_NOTES merge
# --------------------------------------------------------------------------- #

COMMONS_BEGIN = "<!-- BOXBENCH-COMMONS:BEGIN"
COMMONS_END = "<!-- BOXBENCH-COMMONS:END -->"


def default_notes_path() -> Path:
    """PLATFORM_NOTES.md sits next to the skill root, one level above scripts/."""
    override = os.environ.get("BOXBENCH_NOTES")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "PLATFORM_NOTES.md"


def _demote_headings(text: str, levels: int = 2) -> str:
    """Push every Markdown heading down by `levels`.

    The digest arrives as a standalone document starting with `# BoxBench
    Commons`. It is merged under an existing `## <platform>` section, so an
    un-demoted heading would outrank the section that contains it.
    """
    prefix = "#" * levels
    out = []
    for line in text.split("\n"):
        if line.startswith("#"):
            out.append(prefix + line)
        else:
            out.append(line)
    return "\n".join(out)


def commons_block(platform: str, digest_text: str) -> str:
    body = digest_text.strip("\n")
    if body:
        body = _demote_headings(body, 2)
    else:
        body = "_公共经验池暂无该平台的可信条目。_"
    return (
        f"{COMMONS_BEGIN} platform={platform} -->\n"
        f"> 🤖 公共经验池自动同步（机器生成，勿手改；与本机冲突时以本地实测为准）\n\n"
        f"{body}\n"
        f"{COMMONS_END}"
    )


def merge_commons_block(notes_text: str, platform: str, block: str) -> tuple[str, bool]:
    """Idempotently place the machine block for `platform` into the notes.

    Hand-written content is never modified: an existing block for this platform
    is replaced in place, otherwise the block is inserted under the platform
    heading, otherwise a fresh section is appended at the end.
    """
    begin = f"{COMMONS_BEGIN} platform={platform} -->"
    if begin in notes_text:
        start = notes_text.index(begin)
        end = notes_text.index(COMMONS_END, start) + len(COMMONS_END)
        if notes_text[start:end] == block:
            return notes_text, False
        return notes_text[:start] + block + notes_text[end:], True

    heading = f"## `{platform}`"
    lines = notes_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(heading):
            # Insert at the END of this section, not right under the heading:
            # the operator may have hand-written notes belonging to the section,
            # and pushing them below the machine block splits their content.
            level = len(heading) - len(heading.lstrip("#"))
            insert_at = len(lines)
            for j in range(i + 1, len(lines)):
                stripped = lines[j].lstrip()
                if not stripped.startswith("#"):
                    continue
                next_level = len(stripped) - len(stripped.lstrip("#"))
                if next_level <= level:
                    insert_at = j
                    break
            # Trim trailing blank lines so the block does not float away.
            while insert_at > i + 1 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            new_lines = lines[:insert_at] + ["", block, ""] + lines[insert_at:]
            return "\n".join(new_lines), True

    suffix = "" if notes_text.endswith("\n") else "\n"
    return f"{notes_text}{suffix}\n{heading} — 公共经验池同步\n\n{block}\n", True


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_pull(args) -> int:
    platform = args.platform
    headers = {}
    cache = state_dir() / f"commons-{re.sub(r'[^A-Za-z0-9._-]', '_', platform)}.md"
    if cache.exists() and not args.force:
        etag_file = state_dir() / f"commons-{re.sub(r'[^A-Za-z0-9._-]', '_', platform)}.etag"
        if etag_file.exists():
            headers["If-None-Match"] = etag_file.read_text(encoding="utf-8").strip()
    url = f"{commons_url()}/pull?mode=digest&platform_key={urllib.parse.quote(platform)}&min_trust={args.min_trust}"
    status, raw, hdrs = _request("GET", url, headers=headers)
    if status == 304:
        print(f"cached (no change): {cache}")
        print(cache.read_text(encoding="utf-8"))
        return 0
    if status == 0:
        if cache.exists():
            print(f"offline — using cached digest: {cache}", file=sys.stderr)
            print(cache.read_text(encoding="utf-8"))
            return 0
        print("offline and no cache available", file=sys.stderr)
        return 1
    if status != 200:
        print(f"pull failed: http {status}", file=sys.stderr)
        return 1
    text = raw.decode("utf-8")
    cache.write_text(text, encoding="utf-8")
    etag = hdrs.get("ETag") or hdrs.get("etag")
    if etag:
        (state_dir() / f"commons-{re.sub(r'[^A-Za-z0-9._-]', '_', platform)}.etag").write_text(etag, encoding="utf-8")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


def fetch_catalog() -> list[dict] | None:
    """Discover platforms the pool holds. None when offline/unavailable."""
    status, raw, _hdrs = _request("GET", f"{commons_url()}/pull")
    if status != 200:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    platforms = data.get("platforms")
    return platforms if isinstance(platforms, list) else None


def sync_one(platform: str, notes_path: Path, force: bool, dry_run: bool, min_trust: int) -> tuple[str, int]:
    """Sync a single platform; return (action, exit_code)."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", platform)
    cache = state_dir() / f"commons-{safe}.md"
    etag_file = state_dir() / f"commons-{safe}.etag"
    headers = {}
    if cache.exists() and not force and etag_file.exists():
        headers["If-None-Match"] = etag_file.read_text(encoding="utf-8").strip()

    url = f"{commons_url()}/pull?mode=digest&platform_key={urllib.parse.quote(platform)}&min_trust={min_trust}"
    status, raw, hdrs = _request("GET", url, headers=headers)

    if status == 304 and cache.exists():
        digest_text = cache.read_text(encoding="utf-8")
    elif status == 200:
        digest_text = raw.decode("utf-8")
        cache.write_text(digest_text, encoding="utf-8")
        etag = hdrs.get("ETag") or hdrs.get("etag")
        if etag:
            etag_file.write_text(etag, encoding="utf-8")
    elif status == 0 and cache.exists():
        digest_text = cache.read_text(encoding="utf-8")
    elif status == 0:
        return ("offline, no cache", 1)
    else:
        return (f"http {status}", 1)

    original = notes_path.read_text(encoding="utf-8")
    merged, changed = merge_commons_block(original, platform, commons_block(platform, digest_text))
    if not changed:
        return ("up to date", 0)
    if dry_run:
        return ("would update", 0)
    notes_path.write_text(merged, encoding="utf-8")
    return ("updated", 0)


def cmd_sync(args) -> int:
    """Fetch the Commons digest and merge it into PLATFORM_NOTES.md.

    The machine block is fenced by markers, so re-running is idempotent and
    hand-written notes are never touched. Offline falls back to the cached
    digest; if nothing is cached, exits without editing.

    With --all, discover every platform the pool holds and sync each one.
    """
    notes_path = Path(args.notes) if args.notes else default_notes_path()
    if not notes_path.exists():
        print(f"notes file not found: {notes_path}", file=sys.stderr)
        return 1

    platforms: list[str] = []
    if args.all:
        catalog = fetch_catalog()
        if catalog is None:
            print("cannot reach the Commons catalog; try again or name a platform", file=sys.stderr)
            return 1
        platforms = [p.get("platform_key") for p in catalog if p.get("platform_key")]
        if not platforms:
            print("the pool holds no platforms yet; nothing to sync")
            return 0
        print(f"syncing {len(platforms)} platform(s) from the catalog", file=sys.stderr)
    else:
        if not args.platform:
            print("--platform is required unless --all is given", file=sys.stderr)
            return 2
        platforms = [args.platform]

    failures = 0
    for platform in platforms:
        action, code = sync_one(platform, notes_path, args.force, args.dry_run, args.min_trust)
        prefix = "[dry-run] " if args.dry_run else ""
        print(f"{prefix}{platform}: {action}")
        if code:
            failures += 1

    if args.dry_run:
        print(f"\n[dry-run] nothing written to {notes_path}", file=sys.stderr)
    elif failures == 0:
        print(f"\nnotes: {notes_path}")
    return 1 if failures else 0


def cmd_push(args) -> int:
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    platform = args.platform or args.platform_key
    if not platform:
        platform = derive_platform_key(result)
        if platform:
            print(f"platform key inferred: {platform}", file=sys.stderr)
    if not platform:
        print(
            "cannot infer the platform key from this result (engine.engine_name missing).\n"
            "Pass --platform explicitly, e.g.: --platform houmo-HLIELLama-xh2",
            file=sys.stderr,
        )
        return 2
    atom = make_atom(result, platform, args.model, args.note)
    path = enqueue(atom)
    print(f"queued: {path}")
    if not contribution_enabled():
        print("contribution disabled (BOXBENCH_CONTRIBUTE=0) — atom kept locally, not uploaded")
        return 0
    outcome = flush()
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 0


def cmd_flush(args) -> int:
    print(json.dumps(flush(), ensure_ascii=False, indent=2))
    return 0


def cmd_status(args) -> int:
    info = {
        "commons_url": commons_url(),
        "contribution_enabled": contribution_enabled(),
        "state_dir": str(state_dir()),
        "queued_atoms": len(queued()),
        "credentials_present": credential_path().exists(),
        "cached_digests": [p.name for p in state_dir().glob("commons-*.md")],
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(args) -> int:
    """Offline checks for the client-side invariants that are easy to break.

    These cover the PLATFORM_NOTES merge, which no server test can reach: the
    operator's hand-written notes must survive, ordering inside a section must
    be preserved, headings must not outrank their container, and re-running
    must be a no-op.
    """
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n      {detail}" if detail else ""))
        if not ok:
            failures += 1

    digest = "# BoxBench Commons — plat-x\n\n## Baselines\n- M: **42 tok/s** [verified x2]\n"
    block = commons_block("plat-x", digest)

    # Headings inside the block must sit below the enclosing `##` section.
    head_levels = [len(l) - len(l.lstrip("#")) for l in block.split("\n") if l.startswith("#")]
    check("merged headings do not outrank their section", all(lv >= 3 for lv in head_levels), f"levels={head_levels}")

    # Hand-written notes stay in their section, in order, before the machine block.
    notes = "# NOTES\n\n## `plat-x` — mine\n\nnote A\nnote B\n\n## `other`\n\nother note\n"
    merged, changed = merge_commons_block(notes, "plat-x", block)
    a, b, m = merged.index("note A"), merged.index("note B"), merged.index(COMMONS_BEGIN)
    check("hand-written notes are preserved in order", changed and a < b)
    check("machine block follows the operator's notes", a < m and b < m)
    check("other sections are untouched", "other note" in merged)

    # Idempotence: merging the same block again changes nothing.
    again, changed2 = merge_commons_block(merged, "plat-x", block)
    check("re-merge is a no-op", not changed2 and again == merged)

    # Updating the content replaces in place instead of appending a second block.
    block2 = commons_block("plat-x", digest.replace("42 tok/s", "43 tok/s"))
    updated, changed3 = merge_commons_block(merged, "plat-x", block2)
    check(
        "changed digest is replaced in place",
        changed3 and updated.count(COMMONS_BEGIN) == 1 and "43 tok/s" in updated,
        f"{updated.count(COMMONS_BEGIN)} block(s)",
    )

    # A platform with no section gets a fresh one appended.
    fresh, changed4 = merge_commons_block(notes, "new-plat", commons_block("new-plat", digest))
    check(
        "unknown platform appends a new section",
        changed4 and "`new-plat`" in fresh and "note A" in fresh,
    )

    # Canonical JSON must agree with the server on integral floats.
    check(
        "canonical_json normalises integral floats",
        canonical_json({"a": 0.0, "b": 1.5}) == '{"a":0,"b":1.5}',
        canonical_json({"a": 0.0, "b": 1.5}),
    )

    print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILED'}")
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="boxbench_exp", description="BoxBench Commons client")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pull = sub.add_parser("pull", help="fetch the Commons digest for a platform")
    p_pull.add_argument("--platform", required=True)
    p_pull.add_argument("--out")
    p_pull.add_argument("--min-trust", type=int, default=2)
    p_pull.add_argument("--force", action="store_true")
    p_pull.set_defaults(func=cmd_pull)

    p_push = sub.add_parser("push", help="build an atom from a result JSON and upload")
    p_push.add_argument("--result", required=True)
    p_push.add_argument("--platform")
    p_push.add_argument("--platform-key")
    p_push.add_argument("--model")
    p_push.add_argument("--note")
    p_push.set_defaults(func=cmd_push)

    p_flush = sub.add_parser("flush", help="retry queued atoms")
    p_flush.set_defaults(func=cmd_flush)

    p_sync = sub.add_parser("sync", help="merge the Commons digest into PLATFORM_NOTES.md")
    p_sync.add_argument("--platform", help="platform key (omit with --all)")
    p_sync.add_argument("--all", action="store_true", help="sync every platform in the catalog")
    p_sync.add_argument("--notes", help="path to PLATFORM_NOTES.md (default: alongside the skill)")
    p_sync.add_argument("--min-trust", type=int, default=2)
    p_sync.add_argument("--force", action="store_true")
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.set_defaults(func=cmd_sync)

    p_status = sub.add_parser("status", help="show local client state")
    p_status.set_defaults(func=cmd_status)

    p_self = sub.add_parser("selftest", help="run offline self-checks (no network)")
    p_self.set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
