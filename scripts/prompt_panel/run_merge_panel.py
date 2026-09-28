"""Measure merge look-ups: what a look-up adds to an entry the collection holds.

Each case in ``merge_panel.json`` holds an entry. The look-up goes through the
shipped vocabulary template, the same provider call and parser the app uses,
and the app's own merge diff (``VocabRepository.new_definitions_for_merge``),
so the score is what the phone would offer to add.

    python scripts/prompt_panel/run_merge_panel.py --prompts fresh --out results/merge-fresh.json
    python scripts/prompt_panel/run_merge_panel.py --prompts candidate --out results/merge-candidate.json
    python scripts/prompt_panel/run_panel.py --compare results/merge-fresh.json results/merge-candidate.json

``fresh`` sends the template alone, which is how merges worked before
2026-09-28: the model never saw the held entry. ``shipped`` appends
``vocab_builder.ai_prompts.MERGE_ADDENDUM``; ``candidate`` appends
``candidate_prompts.MERGE``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))

from run_panel import content_words, generate, load_templates  # noqa: E402
from vocab_builder import ai_prompts  # noqa: E402
from vocab_builder.ai_response_parser import parse_ai_response_text  # noqa: E402
from vocab_builder.core.text_utils import detect_input_type  # noqa: E402
from vocab_builder.core.vocab_repository import VocabRepository  # noqa: E402
from vocab_builder.llm_client import DEFAULT_THINKING_LEVEL  # noqa: E402


def build_prompt(mode: str, template: str, case: dict[str, Any]) -> str:
    prompt = template.format(input_text=case["word"], detected_type=detect_input_type(case["word"]))
    if mode == "fresh":
        return prompt
    addendum = ai_prompts.MERGE_ADDENDUM
    if mode == "candidate":
        import candidate_prompts  # type: ignore

        addendum = candidate_prompts.MERGE
    held = "\n".join([f"Part of speech: {case['type']}"] + [f"- {sense}" for sense in case["held"]])
    return prompt + addendum.replace("{held_entry}", held)


def restates(added: str, held: list[str]) -> bool:
    words = content_words(added)
    return any(
        words and other and len(words & other) / min(len(words), len(other)) >= 0.5
        for other in (content_words(sense) for sense in held)
    )


def score(case: dict[str, Any], parsed: Any, hedges: list[str]) -> dict[str, Any]:
    added = VocabRepository.new_definitions_for_merge(case["held"], [str(d) for d in parsed.definitions])
    lowered = [a.lower() for a in added]
    restated = [a for a in added if restates(a, case["held"])]
    hedged = [a for a in lowered if any(h in a for h in hedges)]
    parsed_ok = not parsed.contract_issues
    if case["expect"] == "none":
        found = not added
    elif case["expect"] == "either":
        found = all(any(k in a for k in case["allowed_any"]) for a in lowered)
    else:
        found = any(k in a for a in lowered for k in case["add_any"])
    return {
        "parsed_ok": parsed_ok,
        "expected_ok": found,
        "restated": len(restated),
        "hedged": len(hedged),
        "added": len(added),
        "passed": parsed_ok and found and not restated and not hedged,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by = {kind: [r for r in results if r["expect"] == kind] for kind in ("none", "either", "add")}
    return {
        "passed": sum(r["score"]["passed"] for r in results),
        "cases": len(results),
        "complete_left_alone": sum(r["score"]["passed"] for r in by["none"]),
        "complete_cases": len(by["none"]),
        "optional_sense_ok": sum(r["score"]["passed"] for r in by["either"]),
        "optional_cases": len(by["either"]),
        "missing_sense_found": sum(r["score"]["passed"] for r in by["add"]),
        "missing_cases": len(by["add"]),
        "senses_offered": sum(r["score"]["added"] for r in results),
        "restatements_offered": sum(r["score"]["restated"] for r in results),
        "parse_failures": sum(not r["score"]["parsed_ok"] for r in results),
        "mean_seconds": round(sum(r["elapsed_seconds"] for r in results) / max(1, len(results)), 1),
    }


def run(mode: str, out: Path, thinking: str) -> None:
    from vocab_builder.llm_client import GeminiClient

    panel = json.loads((HERE / "merge_panel.json").read_text(encoding="utf-8"))
    hedges = json.loads((HERE / "panel.json").read_text(encoding="utf-8"))["hedges"]
    templates = load_templates("baseline")
    client = GeminiClient()
    results = []
    for case in panel["cases"]:
        prompt = build_prompt(mode, templates[case["language"]], case)
        started = dt.datetime.now(dt.timezone.utc)
        response = generate(client, prompt, thinking)
        elapsed = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
        parsed = parse_ai_response_text(response)
        result = {
            "language": case["language"],
            "word": case["word"],
            "expect": case["expect"],
            "definitions": parsed.definitions,
            "added": VocabRepository.new_definitions_for_merge(case["held"], parsed.definitions),
            "contract_issues": parsed.contract_issues,
            "elapsed_seconds": round(elapsed, 1),
            "score": score(case, parsed, hedges),
            "raw": response,
        }
        results.append(result)
        mark = "pass" if result["score"]["passed"] else "FAIL"
        print(f"{mark:4} {case['language']} {case['word']:14} {case['expect']:4} "
              f"added={result['score']['added']} restated={result['score']['restated']} {elapsed:.1f}s", flush=True)
    payload = {
        "prompts": f"merge-{mode}",
        "thinking": thinking,
        "model": client.model_name(),
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "summary": summarize(results),
        "results": results,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(f"saved {out}")


def rescore(path: Path) -> None:
    """Re-score a saved run after a panel or scorer change, without the provider."""
    cases = {c["word"]: c for c in json.loads((HERE / "merge_panel.json").read_text(encoding="utf-8"))["cases"]}
    hedges = json.loads((HERE / "panel.json").read_text(encoding="utf-8"))["hedges"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    for result in payload["results"]:
        case = cases[result["word"]]
        result["expect"] = case["expect"]
        result["score"] = score(case, parse_ai_response_text(result["raw"]), hedges)
    payload["summary"] = summarize(payload["results"])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompts", choices=["fresh", "shipped", "candidate"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--rescore", type=Path, help="re-score a saved run after a panel or scorer change")
    parser.add_argument("--thinking", default=DEFAULT_THINKING_LEVEL, choices=["low", "medium", "high"])
    args = parser.parse_args()
    if args.rescore:
        rescore(args.rescore)
        return
    if not args.prompts or not args.out:
        parser.error("--prompts and --out are required to run the panel")
    run(args.prompts, args.out, args.thinking)


if __name__ == "__main__":
    main()
