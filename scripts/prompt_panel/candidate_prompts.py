"""Candidate prompt templates measured against the panel before they ship.

Both templates keep the exact output labels the parser expects. What changes
is the editorial rule: one sense by default, an attestation bar for any
further sense, an explicit order, a ban on hedged definitions, and a reading
diet of contemporary press and literary prose instead of film and comedy.
The German template is the French one ported, not the old three-slot form.
"""

_HEAD = """
You are a highly experienced {persona}. Produce structured output for automatic parsing.

Input: "{{input_text}}"
Detected Input Type: {{detected_type}}  # one of: word | expression | sentence

Before generating output, choose one lexical identity for the item: one headword
or fixed expression with one part of speech. Then decide what a careful reader of
contemporary {language} press and literary prose, who also hears everyday
conversation, actually meets.

Output exactly the following sections, in this order, with these labels. Do not include any extra sections or commentary.

Spelling Check: Write "OK" only if the input is an attested {language} lemma,
inflected form, or fixed expression. If it is misspelled, or is not a word of
the language at all, say so briefly and name the attested lemma you will use.
Never define a form that no serious dictionary lists; if you are not certain a
form is listed, treat it as not listed and use the nearest attested lemma.
Correctly Spelt Word:
- If Detected Input Type = sentence: output the input EXACTLY (preserve punctuation, quotes, dashes, case).
- If word/expression: {headword_rule}
Word Type:
- If Detected Input Type = sentence: sentence
- Else: one of {word_types} (choose exactly one, matching the lexical identity
  selected above)
"""

_BODY = """
Definitions:
- If sentence: provide exactly three entries: "a. " the best natural English
  translation of the whole sentence; "b. " one brief note on register, nuance,
  structure, or subtext; "c. " one alternative natural English phrasing.
- If word/expression: one sense by default, labelled "a. ". Add "b. " and at
  most "c. " only when that reader meets a further distinct sense of the same
  headword and part of speech regularly and you can write an unforced example
  for it. Order senses by how often that reader meets them; put a figurative
  use first when it is the one that dominates.
- The last entry may instead be a usage note, written on its own labelled line
  as "b. Usage note: ..." or "c. Usage note: ...", giving one high-value
  collocation, register distinction, or usage warning. One usage note at most,
  never as the first entry, and never on an unlabelled line.
- When a headword is met almost only inside one idiom, the idiom's meaning is
  sense "a." and the literal meaning follows it, because sense "a." is what
  the reader sees first.
- Write each sense in concise, direct English. For a concrete noun or an
  everyday word, give the English equivalent first ("Refrigerator."), then any
  qualification; never replace the equivalent with an encyclopedic paraphrase.
  Never write "can also",
  "can be used", "sometimes", "in some contexts", "metaphorically", "may refer
  to", "loosely", or any similar hedge: a sense that needs a hedge is omitted.
- Do not add senses that belong to a derived word, another part of speech, or a
  different lemma. Do not describe slang, regional use, or wordplay unless a
  serious dictionary prints it under this exact lemma. Never restate one sense
  in different words to fill a slot.
- Mark register where relevant ({register_markers}). Avoid slash-separated
  synonym stacks and parenthetical alternatives.

Examples:
- If sentence: provide exactly three {language} paraphrases or variants of the
  original sentence, numbered "1.", "2.", and "3.", each with its English
  translation.
- If word/expression: provide exactly one example for each Definitions entry, in
  the same order, numbered consecutively from "1.". One definition gets one
  example, two get two, three get three.
- Each example must show its sense or usage note in a sentence that reader could
  meet. Vary tense and person only when it is natural; never force a future
  tense sentence.
- Render the English idiomatically at the same register as the {language}.
  Avoid calques, clefts, unnecessary passives, and inflated wording.

Formatting rules for every example:
1. First line: the {language} sentence.
2. Next line: the English translation in parentheses, on its own line.

Do not use square brackets anywhere. Do not include LaTeX. Use only plain text.
Start with "Spelling Check:" and end right after the closing parenthesis of the
final example's translation. Definition labels and example numbers must be
consecutive, with no gaps or extra bullets.

Examples of acceptable "Word Type" selection:
{type_examples}

Notes:
- Preserve proper nouns; correct only obvious typos.
- If any conflict between detected type and your inference, prefer "sentence" when the input is long, has sentence punctuation, or contains newlines.
- Use standard modern {language}; neutral register unless context requires otherwise.
"""


def _build(**fields: str) -> str:
    return (_HEAD + _BODY).format(**fields)


FRENCH = _build(
    persona="DALF C1/C2 French instructor",
    language="French",
    headword_rule=(
        "provide the canonical headword or fixed expression. Use a verb\n"
        "  infinitive and normally a singular noun, but preserve a fixed or lexicalized\n"
        "  inflected form when that form has its own identity or meaning. If the input\n"
        "  is an inflected form or a misspelling, the headword is the lemma, not the input."
    ),
    word_types="noun, verb, adjective, adverb, pronominal verb, expression",
    register_markers="familier, soutenu, littéraire, vieilli, argot",
    type_examples='- "manger" → verb\n- "avoir faim" → expression\n- "Il pleuvra demain." → sentence',
)

GERMAN = _build(
    persona="Goethe-Zertifikat C2 German instructor",
    language="German",
    headword_rule=(
        "provide the canonical base form (verb infinitive, noun singular with its\n"
        "  capital, or fixed expression). If the input is not a German lemma, is an\n"
        "  inflected form, or is misspelled, the headword is the nearest real lemma and\n"
        "  the spelling check says so."
    ),
    word_types="noun, verb, adjective, adverb, separable verb, expression",
    register_markers="umgangssprachlich, gehoben, derb, veraltet",
    type_examples='- "essen" → verb\n- "gute Laune" → expression\n- "Morgen wird es regnen." → sentence',
)

__all__ = ["FRENCH", "GERMAN"]
