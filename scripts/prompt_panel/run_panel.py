"""Run the vocabulary prompt yardstick and score the result.

The panel in ``panel.json`` names twenty words with the sense count and first
sense a careful reader would expect. This script sends each word through the
same prompt template, provider call, and parser the application uses, saves
every raw response, and scores the run so a prompt edit is measured rather
than tasted.

    python scripts/prompt_panel/run_panel.py --prompts baseline --out results/baseline.json
    python scripts/prompt_panel/run_panel.py --prompts candidate --out results/candidate.json
    python scripts/prompt_panel/run_panel.py --compare results/baseline.json results/candidate.json

``--prompts baseline`` uses the templates shipped in ``vocab_builder``;
``--prompts candidate`` imports ``candidate_prompts.py`` from this directory.
A Gemini credential must be available exactly as it is for the CLI.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from vocab_builder.ai_response_parser import parse_ai_response_text  # noqa: E402
from vocab_builder.ai_response_parser import _extract_section  # noqa: E402
from vocab_builder.core.text_utils import detect_input_type  # noqa: E402

STOP = set(
    "the a an of to or in on for and with by is be as at from that this something "
    "someone one used often usually into out up its it his her their who which when "
    "person thing".split()
)


def load_templates(name: str) -> dict[str, str]:
    if name == "baseline":
        from vocab_builder.ai_prompts import AI_PROMPT_TEMPLATE, GERMAN_PROMPT_TEMPLATE

        return {"fr": AI_PROMPT_TEMPLATE, "de": GERMAN_PROMPT_TEMPLATE}
    if name == "candidate":
        sys.path.insert(0, str(HERE))
        import candidate_prompts  # type: ignore

        return {"fr": candidate_prompts.FRENCH, "de": candidate_prompts.GERMAN}
    raise SystemExit(f"unknown prompt set: {name}")


def generate(client: Any, prompt: str) -> str:
    return "".join(client.stream(prompt, thinking_level="low"))


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ÿ]+", text.lower()) if w not in STOP and len(w) > 2}


def is_usage_note(definition: str) -> bool:
    return definition.strip().lower().startswith("usage note")


def score(spec: dict[str, Any], parsed: Any, corrected: str, hedges: list[str]) -> dict[str, Any]:
    definitions = [str(d) for d in parsed.definitions]
    lowered = [d.lower() for d in definitions]
    # A usage note is not a sense: the prompt allows one beside the senses, so
    # the count that is judged is the count of senses.
    senses = [d for d in lowered if not is_usage_note(d)]
    notes = len(lowered) - len(senses)
    first = lowered[0] if lowered else ""
    everything = " ".join(lowered)
    # Invention is judged on senses only: a usage note that names the derived
    # lemma a reader might confuse ("zurückrudern") is doing its job.
    sense_text = " ".join(senses)
    low, high = spec["senses"]
    checks = {
        "count_ok": low <= len(senses) <= high,
        "notes_ok": notes <= 1 and not (lowered and is_usage_note(lowered[0])),
        "first_ok": any(k in first for k in spec.get("first_any", [])),
        "first_clean": not any(k in first for k in spec.get("first_reject", [])),
        "required_ok": (
            not spec.get("required_any")
            or any(k in everything for k in spec["required_any"])
        ),
        "nothing_invented": not any(k in sense_text for k in spec.get("must_not", [])),
        "corrected_ok": (
            not spec.get("corrected_not")
            or corrected.strip().lower() not in spec["corrected_not"]
        ),
        "parsed_ok": bool(definitions) and not parsed.parsing_warnings,
    }
    hedged = [d for d in lowered if any(h in d for h in hedges)]
    # Restatement is judged between senses, since a usage note legitimately
    # repeats the headword's field, and only when both sides carry enough
    # content words for a ratio to mean anything: "Customs officer." against a
    # note mentioning "cordon douanier" shares one word of two and is not a
    # restatement.
    sets = [content_words(d) for d in senses]
    overlaps = sum(
        1
        for i, a in enumerate(sets)
        for b in sets[i + 1:]
        if len(a) >= 3 and len(b) >= 3 and len(a & b) / min(len(a), len(b)) >= 0.5
    )
    return {
        **checks,
        "passed": all(checks.values()) and not hedged and overlaps == 0,
        "hedged_definitions": len(hedged),
        "overlapping_pairs": overlaps,
        "sense_count": len(senses),
        "usage_notes": notes,
    }


def rescore(path: Path) -> None:
    """Re-parse and re-score saved raw responses without calling the provider."""
    panel = json.loads((HERE / "panel.json").read_text(encoding="utf-8"))
    specs = {spec["word"]: spec for spec in panel["words"]}
    payload = json.loads(path.read_text(encoding="utf-8"))
    for result in payload["results"]:
        parsed = parse_ai_response_text(result["raw"])
        result["definitions"] = parsed.definitions
        result["examples"] = parsed.examples
        result["parsing_warnings"] = parsed.parsing_warnings
        result["contract_issues"] = parsed.contract_issues
        result["score"] = score(specs[result["word"]], parsed, result["corrected"], panel["hedges"])
    payload["summary"] = summarize(payload["results"])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(f"rescored {path}")


def run(prompts: str, out: Path) -> None:
    from vocab_builder.llm_client import GeminiClient

    panel = json.loads((HERE / "panel.json").read_text(encoding="utf-8"))
    templates = load_templates(prompts)
    client = GeminiClient()
    results = []
    for spec in panel["words"]:
        word = spec["word"]
        prompt = templates[spec["language"]].format(
            input_text=word, detected_type=detect_input_type(word)
        )
        started = dt.datetime.now(dt.timezone.utc)
        response = generate(client, prompt)
        elapsed = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
        parsed = parse_ai_response_text(response)
        corrected = _extract_section(response, "Correctly Spelt Word:").strip().splitlines()
        corrected_word = corrected[0].strip() if corrected else ""
        result = {
            "language": spec["language"],
            "word": word,
            "corrected": corrected_word,
            "word_type": parsed.word_type,
            "definitions": parsed.definitions,
            "examples": parsed.examples,
            "parsing_warnings": parsed.parsing_warnings,
            "contract_issues": parsed.contract_issues,
            "elapsed_seconds": round(elapsed, 1),
            "score": score(spec, parsed, corrected_word, panel["hedges"]),
            "raw": response,
        }
        results.append(result)
        mark = "pass" if result["score"]["passed"] else "FAIL"
        print(f"{mark:4} {spec['language']} {word:14} senses={len(parsed.definitions)} {elapsed:.1f}s", flush=True)
    payload = {
        "prompts": prompts,
        "model": client.model_name(),
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "summary": summarize(results),
        "results": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(f"saved {out}")


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [
        "passed", "count_ok", "notes_ok", "first_ok", "first_clean",
        "required_ok", "nothing_invented", "corrected_ok", "parsed_ok",
    ]
    summary: dict[str, Any] = {k: sum(1 for r in results if r["score"][k]) for k in keys}
    summary["words"] = len(results)
    summary["hedged_definitions"] = sum(r["score"]["hedged_definitions"] for r in results)
    summary["overlapping_pairs"] = sum(r["score"]["overlapping_pairs"] for r in results)
    summary["total_senses"] = sum(r["score"]["sense_count"] for r in results)
    summary["usage_notes"] = sum(r["score"]["usage_notes"] for r in results)
    summary["mean_seconds"] = round(sum(r["elapsed_seconds"] for r in results) / max(1, len(results)), 1)
    return summary


def compare(left: Path, right: Path) -> None:
    a = json.loads(left.read_text(encoding="utf-8"))
    b = json.loads(right.read_text(encoding="utf-8"))
    print(f"{'metric':22} {a['prompts']:>10} {b['prompts']:>10}")
    for key, va in a["summary"].items():
        print(f"{key:22} {str(va):>10} {str(b['summary'].get(key)):>10}")
    print()
    print(f"{'word':16} {a['prompts']:>10} {b['prompts']:>10}")
    by_word = {r["word"]: r for r in b["results"]}
    for r in a["results"]:
        other = by_word.get(r["word"])
        left_mark = "pass" if r["score"]["passed"] else "FAIL"
        right_mark = ("pass" if other["score"]["passed"] else "FAIL") if other else "-"
        print(f"{r['word']:16} {left_mark:>10} {right_mark:>10}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompts", choices=["baseline", "candidate"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("LEFT", "RIGHT"))
    parser.add_argument("--rescore", type=Path, help="re-score a saved run after a panel or scorer change")
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare)
        return
    if args.rescore:
        rescore(args.rescore)
        return
    if not args.prompts or not args.out:
        parser.error("--prompts and --out are required to run the panel")
    run(args.prompts, args.out)


if __name__ == "__main__":
    main()
