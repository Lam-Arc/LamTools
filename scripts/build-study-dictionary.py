"""Build the bundled Study English→Chinese dictionary from the configured model.

Two resumable stages:

``list``    Ask the configured model for CET-6 vocabulary in batches, validate
            every candidate (script regex, ASCII letters only, frequency floor
            when ``wordfreq`` is installed) and write ``words.txt``.  Existing
            words are kept, so re-running only tops the list up.
``entries`` Generate fixed-schema entries for ``words.txt`` and write
            ``en-zh.jsonl`` (plus a manifest).  Words already present in the
            output are skipped, so the build can be stopped and resumed.

The shipped dictionary carries no third-party dictionary text: the entries are
produced by the user's own configured model and validated here.  Query time
never calls a model for a word that this table already answers.

Usage (from ``core/``)::

    py -3.14 scripts/build-study-dictionary.py --stage list
    py -3.14 scripts/build-study-dictionary.py --stage entries --concurrency 8
    py -3.14 scripts/build-study-dictionary.py --stage validate
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _find_core_dir() -> Path:
    """Locate ``core/`` from either the scripts/ checkout or a plugin-side copy."""
    for base in (SCRIPT_DIR, *SCRIPT_DIR.parents):
        if (base / "core" / "src" / "lamtools_core" / "plugins" / "bundled" / "study").is_dir():
            return base / "core"
    raise SystemExit("cannot locate core/ from the builder location")


CORE_DIR = _find_core_dir()
SRC_DIR = CORE_DIR / "src"
DICTIONARY_DIR = SRC_DIR / "lamtools_core" / "plugins" / "bundled" / "study" / "dictionary"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lamtools_core.plugins.bundled.study.lexicon import normalize_entry  # noqa: E402

WORD_RE = re.compile(r"^[a-z][a-z-]*$")
# The frequency top-up can supply proper nouns; the model labels them.
PROPER_POS = re.compile(r"proper|\bnp\b", re.I)
# The builder validates every entry against the rules the runtime uses.
valid_entry = normalize_entry

LIST_PROMPT = (
    "You are compiling the CET-6 (Chinese College English Test Band 6) vocabulary list. "
    "Return only single English words that belong to that syllabus: base forms, lowercase, "
    "no proper nouns, no phrases, no inflections, no duplicates. "
    "Answer as JSON: {\"words\": [\"...\"]}."
)

ENTRY_PROMPT = (
    "You are a bilingual lexicographer producing British learner's-dictionary entries for a "
    "Chinese learner. For each requested word return IPA (British and American), the part of "
    "speech, up to three senses ordered by how common they are, a short English definition and "
    "a simplified-Chinese gloss per sense, one example sentence with its Chinese translation per "
    "sense, and the inflected forms the word actually has. Never invent a sense or a form that "
    "the word does not have; keep the Chinese gloss concise and idiomatic. "
    "Write phonetics between slashes, e.g. /ˈməʊʃn/, and use only these form keys: "
    "pl, pt, pp, ing, 3sg (plus comparative and superlative for adjectives that have them)."
)

ENTRY_SCHEMA = json.loads(
    """
{"type":"object","properties":{"entries":{"type":"array","items":{"type":"object","properties":{
"word":{"type":"string"},"phonetic_uk":{"type":"string"},"phonetic_us":{"type":"string"},
"senses":{"type":"array","items":{"type":"object","properties":{
  "pos":{"type":"string"},"zh":{"type":"string"},"en":{"type":"string"},
  "example":{"type":"object","properties":{"en":{"type":"string"},"zh":{"type":"string"}}}},
  "required":["pos","zh","en"]}},
"forms":{"type":"object","properties":{
  "pl":{"type":"string"},"pt":{"type":"string"},"pp":{"type":"string"},"ing":{"type":"string"},
  "3sg":{"type":"string"},"comparative":{"type":"string"},"superlative":{"type":"string"}}}},
"required":["word","phonetic_uk","phonetic_us","senses","forms"]}}},
"required":["entries"]}
"""
)

_LIST_SCHEMA = json.loads('{"type":"object","properties":{"words":{"type":"array","items":{"type":"string"}}},"required":["words"]}')


def frequency_filter():
    """Return ``zipf(word) -> float`` when wordfreq is installed, else None."""
    try:
        from wordfreq import zipf_frequency  # type: ignore
    except Exception:
        return None
    return lambda word: float(zipf_frequency(word, "en"))


def top_words(count: int) -> list[str]:
    """Return the most frequent English words when wordfreq is installed."""
    try:
        from wordfreq import top_n_list  # type: ignore
    except Exception:
        return []
    return [word for word in top_n_list("en", count * 3) if WORD_RE.match(word)]


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_entries(path: Path) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        word = str(entry.get("word") or "")
        if word:
            entries[word] = entry
    return entries


def write_entries(path: Path, entries: dict[str, dict]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for word in sorted(entries):
            handle.write(json.dumps(entries[word], ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


class Builder:
    def __init__(self, model_ref: str, concurrency: int, reasoning: dict) -> None:
        from lamtools_core.app.http_agent_app import CoreConfigRoutingLLMClient

        self.model_ref = model_ref
        self.concurrency = concurrency
        self.reasoning = reasoning
        self.tokens = Counter()
        self.calls = 0
        self.client = CoreConfigRoutingLLMClient(
            default_model_ref=model_ref,
            thinking_enabled=bool(reasoning.get("thinking_enabled")),
            thinking_budget=10000,
            reasoning_level=str(reasoning.get("reasoning_level") or ""),
            max_tokens=None,
            temperature=0.3,
        )

    async def ask(self, messages: list, schema: dict, name: str, max_retries: int = 3):
        from lamtools_core.llm import ChatMessage, LLMRequest

        last_error = ""
        for attempt in range(max_retries):
            request = LLMRequest(
                messages=[ChatMessage(role=role, content=content) for role, content in messages],
                model=self.model_ref,
                response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": False}},
                max_tokens=None,
                timeout=180,
                metadata=dict(self.reasoning),
            )
            try:
                response = await self.client.complete(request)
            except Exception as exc:  # noqa: BLE001 — a single bad batch must not kill the build
                last_error = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(2 + attempt * 3)
                continue
            self.calls += 1
            if response.usage is not None:
                self.tokens["prompt"] += int(response.usage.prompt_tokens or 0)
                self.tokens["completion"] += int(response.usage.completion_tokens or 0)
            try:
                return json.loads(response.content)
            except json.JSONDecodeError as exc:
                last_error = f"unparsable JSON: {exc}"
                await asyncio.sleep(1)
        print(f"  ! batch failed: {last_error}", flush=True)
        return None


async def build_list(builder: Builder, words: list[str], target: int, batch: int, round_no: int) -> list[str]:
    seen = {word for word in words}
    async def one(offset: int) -> list[str]:
        prompt = (
            f"{LIST_PROMPT}\nReturn {batch} further CET-6 words"
            + (f" that are not in this already-collected list: {', '.join(sorted(seen)[-400:])}" if seen else "")
            + (f". Batch {offset + 1}." if round_no > 0 else ".")
        )
        payload = await builder.ask([("system", LIST_PROMPT), ("user", prompt)], _LIST_SCHEMA, "words")
        if not isinstance(payload, dict):
            return []
        return [str(word).strip().lower() for word in payload.get("words") or []]

    results = await asyncio.gather(*(one(index) for index in range(builder.concurrency)))
    added = []
    for batch_words in results:
        for word in batch_words:
            if WORD_RE.match(word) and word not in seen:
                seen.add(word)
                added.append(word)
    return added


def merge_curated(entries: dict[str, dict], path: Path) -> int:
    """Fold the hand-written lexicon into the shipped table.

    The generated file is the single artifact both hosts read, so the curated
    entries the Study surfaces rely on have to travel inside it.  They keep a
    ``source`` marker so the card can still tell verified entries apart.
    """
    from lamtools_core.plugins.bundled.study.lexicon import ENTRIES, curated

    merged = 0
    for word, values in ENTRIES.items():
        entry = curated(word, values)
        entries[word] = {
            'word': word,
            'phonetic_uk': entry['phonetic_uk'],
            'phonetic_us': '',
            'senses': entry['senses'],
            'source': 'curated',
        }
        merged += 1
    if merged:
        write_entries(path, entries)
    print(f"curated entries folded into the table: {merged}", flush=True)
    return merged


def prune(words: list[str], entries: dict[str, dict], entries_path: Path, words_path: Path) -> list[str]:
    """Drop entries a learner dictionary should not carry, and stop retrying them.

    The frequency top-up that fills the word list can hand over proper nouns.
    The model labels them (``proper noun``), so the entry is removed and the
    word leaves ``words.txt`` — otherwise every rebuild would pay for it again.
    Curated entries are never pruned: they are hand-written on purpose.
    """
    removed = []
    for word, entry in list(entries.items()):
        if str(entry.get("source") or "") == "curated":
            continue
        pos = " ".join(str(sense.get("pos") or "") for sense in entry.get("senses") or [])
        if PROPER_POS.search(pos):
            del entries[word]
            removed.append(word)
    rejected_path = entries_path.with_suffix(".rejected.json")
    previous: list[str] = []
    if rejected_path.exists():
        try:
            loaded = json.loads(rejected_path.read_text(encoding="utf-8"))
            previous = [str(item) for item in loaded.get("words") or []]
        except ValueError:
            previous = []
    if removed:
        write_entries(entries_path, entries)
        dropped = set(removed)
        words[:] = [word for word in words if word not in dropped]
        words_path.write_text("\n".join(words) + "\n", encoding="utf-8", newline="\n")
        rejected_path.write_text(
            json.dumps(
                {
                    "words": sorted(set(previous) | set(removed)),
                    "reason": "proper nouns excluded from generation",
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return removed


async def build_entries(builder: Builder, entries: dict[str, dict], words: list[str], batch: int, out_path: Path) -> None:
    pending = [word for word in words if word not in entries]
    if not pending:
        print("entries: nothing to do", flush=True)
        return
    batches = [pending[index:index + batch] for index in range(0, len(pending), batch)]
    print(f"entries: {len(pending)} words in {len(batches)} batches (concurrency {builder.concurrency})", flush=True)
    done = 0
    lock = asyncio.Lock()
    started = time.perf_counter()

    async def one(part: list[str]) -> None:
        nonlocal done
        payload = await builder.ask(
            [("system", ENTRY_PROMPT), ("user", "Entries for: " + ", ".join(part))],
            ENTRY_SCHEMA,
            "entries",
        )
        produced = {}
        if isinstance(payload, dict):
            for raw in payload.get("entries") or []:
                for word in part:
                    entry = valid_entry(raw, word)
                    if entry is not None:
                        produced[word] = entry
                        break
        async with lock:
            entries.update(produced)
            done += len(part)
            write_entries(out_path, entries)
            elapsed = time.perf_counter() - started
            print(
                f"  {done}/{len(pending)} words | kept {len(entries)} | {builder.calls} calls | "
                f"{builder.tokens['completion']} out-tokens | {elapsed/60:.1f} min",
                flush=True,
            )

    queue = list(batches)
    workers = [asyncio.create_task(_worker(queue, one)) for _ in range(builder.concurrency)]
    await asyncio.gather(*workers)


async def _worker(queue: list, handler) -> None:
    while queue:
        part = queue.pop(0)
        await handler(part)


async def main_async(args: argparse.Namespace) -> int:
    words_path = args.words or (DICTIONARY_DIR / "words.txt")
    entries_path = args.output or (DICTIONARY_DIR / "en-zh.jsonl")
    words = read_lines(words_path)
    entries = load_entries(entries_path)
    zipf = frequency_filter()
    builder = Builder(args.model, args.concurrency, {"thinking_enabled": False, "reasoning_level": "light"})

    print(f"model={args.model} concurrency={args.concurrency} words={len(words)} entries={len(entries)} wordfreq={'yes' if zipf else 'no'}", flush=True)

    if args.stage in ("list", "all"):
        rounds = 0
        while len(words) < args.target and rounds < args.max_rounds:
            added = await build_list(builder, words, args.target, args.list_batch, rounds)
            if zipf is not None:
                added = [word for word in added if zipf(word) >= args.min_zipf]
            fresh = [word for word in added if word not in set(words)]
            words = sorted(set(words) | set(fresh))
            rounds += 1
            print(f"list round {rounds}: +{len(fresh)} -> {len(words)} words", flush=True)
            words_path.parent.mkdir(parents=True, exist_ok=True)
            words_path.write_text("\n".join(words) + "\n", encoding="utf-8", newline="\n")
            if not fresh:
                break
        if len(words) < args.target:
            top = top_words(args.target)
            if top:
                merged = sorted(set(words) | set(top))
                if len(merged) > args.target:
                    keep = set(top[: args.target])
                    merged = sorted((set(words) & keep) | keep)
                words = merged[: max(args.target, len(words))]
                words_path.write_text("\n".join(words) + "\n", encoding="utf-8", newline="\n")
                print(f"list topped up with frequency data -> {len(words)} words", flush=True)
        print(f"list: {len(words)} words at {words_path}", flush=True)

    if args.stage in ("entries", "all"):
        if args.limit:
            words = words[: args.limit]
        await build_entries(builder, entries, words, args.batch, entries_path)
        merge_curated(entries, entries_path)
        # Keep the cumulative build cost: a later resumable run must not erase
        # what the artifact actually took to produce.
        manifest_path = DICTIONARY_DIR / "en-zh.manifest.json"
        previous: dict = {}
        if manifest_path.exists():
            try:
                previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            except ValueError:
                previous = {}
        tokens = {
            key: int(builder.tokens.get(key, 0)) + int((previous.get("tokens") or {}).get(key, 0))
            for key in set(builder.tokens) | set(previous.get("tokens") or {})
        }
        manifest = {
            "entries": len(entries),
            "words": len(words),
            "missing": [word for word in words if word not in entries][:50],
            "without_phonetic": [
                word for word, entry in entries.items()
                if not entry.get("phonetic_uk") and not entry.get("phonetic_us")
            ][:200],
            "model": args.model,
            "reasoning": {"thinking_enabled": False, "reasoning_level": "light"},
            "prompt_version": 1,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "calls": builder.calls + int(previous.get("calls") or 0),
            "tokens": tokens,
            "runs": int(previous.get("runs") or 0) + 1,
            "sha256": hashlib.sha256(entries_path.read_bytes()).hexdigest() if entries_path.exists() else "",
            "license": "Model-generated by the user's configured provider; no third-party dictionary text.",
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(json.dumps({key: manifest[key] for key in ("entries", "words", "calls", "tokens", "sha256")}, ensure_ascii=False), flush=True)

    if args.stage == "validate":
        bad = []
        for word, entry in entries.items():
            if valid_entry(entry, word) is None:
                bad.append(word)
        print(json.dumps({"checked": len(entries), "invalid": bad[:20], "invalid_count": len(bad)}, ensure_ascii=False))

    if args.stage == "prune":
        removed = prune(words, entries, entries_path, words_path)
        print(json.dumps({"pruned": len(removed), "words": len(words), "entries": len(entries), "sample": removed[:20]}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("list", "entries", "all", "validate", "prune"), default="all")
    parser.add_argument("--model", default="command-code-deepseek-deepseek-v4.1-flash")
    parser.add_argument("--target", type=int, default=6000)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch", type=int, default=20)
    parser.add_argument("--list-batch", type=int, default=300)
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--min-zipf", type=float, default=1.5)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--words", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
