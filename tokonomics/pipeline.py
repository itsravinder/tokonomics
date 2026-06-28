"""
pipeline.py - request-body optimization for the Tokonomics proxy.

Operates on an Anthropic Messages API request body (the JSON Claude Code POSTs
to /v1/messages) and returns an optimized copy plus a per-stage report of how
many estimated tokens each stage saved.

Three stages, each independently toggleable:
  1. rtk        - compress noisy command/bash tool_result output.
  2. markitdown - convert document blocks (PDF/Office) to clean markdown.
  3. prompt     - minify whitespace-heavy / structured text in older blocks.

Safety is the whole game here - this runs in the live request path:
  - optimize() NEVER raises. Any failure returns the ORIGINAL body unchanged.
  - Compression is DETERMINISTIC and applied UNIFORMLY to every message. This is
    what keeps Anthropic prompt caching intact: the cache key is an exact byte
    prefix, so a given tool_result must compress to identical bytes whether it
    is the newest turn or deep in history. Treating the last message differently
    from history (or using time/randomness) would shift those bytes turn-to-turn
    and force cache misses - which can cost MORE than the tokens we save.
  - We only ever touch `tool_result` and `document` blocks (machine-generated:
    tool output, logs, files, RAG chunks). The system prompt and the user's own
    text are never modified.
  - Every stage and every block is wrapped in its own try/except, so one bad
    block degrades to passthrough for that block only.

markitdown / tiktoken are optional and imported lazily; absence degrades the
relevant stage to a no-op rather than failing.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from base64 import b64decode

# ---- token estimation ------------------------------------------------------
_ENCODER = None
_ENCODER_TRIED = False


def _encoder():
    """Lazily load a tiktoken encoder; None if tiktoken is not installed."""
    global _ENCODER, _ENCODER_TRIED
    if _ENCODER_TRIED:
        return _ENCODER
    _ENCODER_TRIED = True
    try:
        import tiktoken  # type: ignore

        _ENCODER = tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - tiktoken optional
        _ENCODER = None
    return _ENCODER


def estimate_text_tokens(text: str) -> int:
    """Estimate tokens for a string. tiktoken if available, else chars/4."""
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(text) // 4)


def _iter_text(obj) -> str:
    """Flatten all human-readable text in a body/message/block for estimation."""
    parts: list[str] = []

    def walk(o):
        if isinstance(o, str):
            parts.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return "\n".join(parts)


def estimate_tokens(obj) -> int:
    """Estimate the token footprint of an arbitrary JSON-ish object."""
    return estimate_text_tokens(_iter_text(obj))


# ---- text compression helpers ---------------------------------------------
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TRAILING_WS_RE = re.compile(r"[ \t]+(\n)")
_BLANKS_RE = re.compile(r"\n{3,}")
_TRUNCATE_LINES = 400  # outputs longer than this get an elision marker


def _looks_like_command_output(text: str) -> bool:
    """Heuristic: is this tool_result a command/bash dump rather than prose?"""
    if not text:
        return False
    has_ansi = "\x1b[" in text
    many_lines = text.count("\n") >= 8
    return has_ansi or many_lines


def _compress_output(text: str, truncate: bool = False) -> str:
    """Strip ANSI, trailing whitespace, collapse blank runs, dedupe identical
    lines, and (only when `truncate` is on) elide the middle of huge outputs.

    Intra-line spacing is never altered, so indentation-significant content
    (code, YAML, diffs) inside command output is preserved."""
    out = _ANSI_RE.sub("", text)
    out = _TRAILING_WS_RE.sub(r"\1", out)
    out = _BLANKS_RE.sub("\n\n", out)

    # collapse immediately-repeated identical lines (e.g. progress spam)
    lines = out.split("\n")
    deduped: list[str] = []
    repeat = 0
    for ln in lines:
        if deduped and ln == deduped[-1] and ln.strip():
            repeat += 1
            continue
        if repeat:
            deduped.append(f"... [{repeat} identical line(s) elided] ...")
            repeat = 0
        deduped.append(ln)
    if repeat:
        deduped.append(f"... [{repeat} identical line(s) elided] ...")

    # truncate very long outputs, keeping head and tail (opt-in: lossy)
    if truncate and len(deduped) > _TRUNCATE_LINES:
        head = deduped[: _TRUNCATE_LINES // 2]
        tail = deduped[-_TRUNCATE_LINES // 2 :]
        elided = len(deduped) - len(head) - len(tail)
        deduped = head + [f"... [{elided} line(s) elided] ..."] + tail

    return "\n".join(deduped).strip("\n")


_RTK_BIN = None


def _set_rtk_binary(path: str | None) -> None:
    """Let the proxy hand us the resolved rtk path (optional shell-out)."""
    global _RTK_BIN
    _RTK_BIN = path or None


def _rtk_compress(text: str) -> str | None:
    """Try the bundled rtk binary on stdin; return None if unavailable/failed."""
    if not _RTK_BIN or not os.path.exists(_RTK_BIN):
        return None
    try:
        proc = subprocess.run(
            [_RTK_BIN, "compress", "--stdin"],
            input=text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    except Exception:  # noqa: BLE001 - rtk shell-out is best-effort
        return None
    return None


# ---- block-level transforms ------------------------------------------------
def _result_text_blocks(block: dict):
    """Yield (container, key) for each editable text payload in a tool_result.

    A tool_result's `content` may be a plain string or a list of
    {type:text, text:...} blocks. Yields references we can read/write in place.
    """
    content = block.get("content")
    if isinstance(content, str):
        yield block, "content"
    elif isinstance(content, list):
        for sub in content:
            if isinstance(sub, dict) and sub.get("type") == "text" and isinstance(sub.get("text"), str):
                yield sub, "text"


def stage_rtk(messages: list, cfg: dict) -> None:
    """Compress noisy command/bash output inside tool_result blocks, in place."""
    truncate = bool(cfg.get("truncate", False))
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            try:
                for container, key in _result_text_blocks(block):
                    text = container[key]
                    if not _looks_like_command_output(text):
                        continue
                    compressed = _rtk_compress(text) or _compress_output(text, truncate)
                    if len(compressed) < len(text):
                        container[key] = compressed
            except Exception:  # noqa: BLE001 - per-block safety
                continue


_MD_CACHE: dict[str, str] = {}
_MD_CACHE_MAX = 64


def _markitdown_convert(raw: bytes, suffix: str) -> str | None:
    """Convert document bytes to markdown via markitdown; None if unavailable.

    Memoized by content hash: the same document recurs in history every turn,
    and re-running markitdown on the hot path each time would add real latency.
    """
    key = hashlib.sha1(raw).hexdigest()
    if key in _MD_CACHE:
        return _MD_CACHE[key]
    try:
        from markitdown import MarkItDown  # type: ignore
    except Exception:  # noqa: BLE001 - markitdown optional
        return None
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        result = MarkItDown().convert(tmp_path)
        md = getattr(result, "text_content", None)
        if md:
            if len(_MD_CACHE) >= _MD_CACHE_MAX:
                _MD_CACHE.clear()
            _MD_CACHE[key] = md
        return md
    except Exception:  # noqa: BLE001
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


_MEDIA_SUFFIX = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def stage_markitdown(messages: list, cfg: dict) -> None:
    """Replace base64 `document` blocks with clean markdown text, in place."""
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for i, block in enumerate(content):
            if not isinstance(block, dict) or block.get("type") != "document":
                continue
            try:
                src = block.get("source") or {}
                if src.get("type") != "base64" or not src.get("data"):
                    continue
                suffix = _MEDIA_SUFFIX.get(src.get("media_type", ""), ".bin")
                raw = b64decode(src["data"])
                md = _markitdown_convert(raw, suffix)
                if md and md.strip():
                    content[i] = {"type": "text", "text": md.strip()}
            except Exception:  # noqa: BLE001 - per-block safety
                continue


def _minify(text: str) -> str:
    """Minify a tool_result ONLY when it is wholly JSON (whitespace there is
    insignificant). Any other text is returned unchanged - collapsing spaces in
    code, YAML, or diffs would corrupt indentation-significant content."""
    stripped = text.strip()
    if stripped and stripped[0] in "{[":
        try:
            return json.dumps(json.loads(stripped), separators=(",", ":"))
        except (ValueError, TypeError):
            pass
    return text


def stage_prompt(messages: list, cfg: dict) -> None:
    """Minify embedded JSON in tool_result blocks (no-op on non-JSON text).

    Deliberately skips standalone `text` blocks: those are the user's own words
    (instructions, pasted code), which we must not alter.
    """
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            try:
                for container, key in _result_text_blocks(block):
                    container[key] = _minify(container[key])
            except Exception:  # noqa: BLE001 - per-block safety
                continue


# ---- orchestration ---------------------------------------------------------
DEFAULT_CONFIG = {
    "passthrough": False,
    "rtk": True,
    "markitdown": True,
    "prompt": True,
    "truncate": False,  # lossy middle-elision of huge outputs; opt-in
}

_STAGES = (
    ("rtk", stage_rtk),
    ("markitdown", stage_markitdown),
    ("prompt", stage_prompt),
)


def optimize(body: dict, config: dict | None = None) -> tuple[dict, dict]:
    """Return (optimized_body, report). Never raises.

    report = {
      status, orig_tokens, opt_tokens, saved_tokens,
      stages: {rtk: saved, markitdown: saved, prompt: saved},
    }
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    orig_tokens = estimate_tokens(body)
    report = {
        "status": "ok",
        "orig_tokens": orig_tokens,
        "opt_tokens": orig_tokens,
        "saved_tokens": 0,
        "stages": {"rtk": 0, "markitdown": 0, "prompt": 0},
    }

    if cfg.get("passthrough"):
        report["status"] = "passthrough"
        return body, report

    try:
        out = copy.deepcopy(body)
        messages = out.get("messages")
        if not isinstance(messages, list) or not messages:
            report["status"] = "no-messages"
            return body, report

        # Compress every message uniformly. Stages only touch tool_result /
        # document blocks, so the user's text and the system prompt are safe;
        # determinism + uniformity keep the prompt-cache prefix byte-stable.
        running = orig_tokens
        for name, fn in _STAGES:
            if not cfg.get(name, True):
                continue
            try:
                fn(messages, cfg)
            except Exception:  # noqa: BLE001 - stage safety
                continue
            after = estimate_tokens(out)
            report["stages"][name] = max(0, running - after)
            running = after

        opt_tokens = estimate_tokens(out)
        report["opt_tokens"] = opt_tokens
        report["saved_tokens"] = max(0, orig_tokens - opt_tokens)
        # if optimization somehow grew the body, fall back to the original
        if opt_tokens > orig_tokens:
            report["status"] = "no-gain"
            report["opt_tokens"] = orig_tokens
            report["saved_tokens"] = 0
            report["stages"] = {"rtk": 0, "markitdown": 0, "prompt": 0}
            return body, report
        return out, report
    except Exception as exc:  # noqa: BLE001 - absolute backstop
        report["status"] = f"passthrough-error: {type(exc).__name__}"
        report["opt_tokens"] = orig_tokens
        report["saved_tokens"] = 0
        return body, report
