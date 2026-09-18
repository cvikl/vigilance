"""The reporter's contract (spec §5): a guided-JSON prose bundle, a prompt whose hash is the
prompt_version, and the back-check that lets no figure into the report that is not in the payload."""
import hashlib
import json
import re
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict

from auditpace.models import ClaudeCLI, ModelClient, ModelJSONError
from auditpace.report.fmt import printed_tokens_by_kind
from auditpace.report.gateway import Payload, Vocab

FALLBACK = ("Narrative withheld: the report writer's text contained a figure or identifier not present in the "
            "audited aggregates.")
FALLBACK_LENGTH = "Narrative withheld: the report writer's text exceeded the section's word limit."
UNAVAILABLE = "Narrative withheld: report writer unavailable."
WORD_LIMITS = {"summary": 120, "where": 60, "why": 60, "who": 60, "actions_note": 80, "caveats_note": 80}
SMALL_INT_MAX = 12  # "two of six criteria" — ordinals and small counts need no payload match

SYSTEM_PROMPT = """You write the narrative paragraphs of an NHS clinical-audit report. You are given the audited
aggregates as a compact JSON view, already formatted exactly as the report will print them: every rate is a
string such as "19.3 % (17.4–21.4 %)" (the figure, then its 95 % confidence interval in parentheses) — copy it
verbatim, do not reformat, round or recompute it, and there is no separate lower/upper bound to combine yourself.
One entry per criterion (a handoff on a care pathway, with a target in hours): breach rates (naive and
corrected), a reason breakdown (each reason has a class: system means the patient was stalled, legitimate means
the patient was legitimately waiting), segments, a list of organisation outliers (each already a full sentence
fragment naming its Org-nn, its signal and its rate), alerts with an action and an owner taken from the audit
protocol, and data-quality counts.

Rules, all of them binding:
1. Use only figures that appear in the JSON, and write each exactly as it appears there (rates are given
   to one decimal place as percentages, already combined with their interval; counts are integers). Never
   round, never derive, never add a figure, never split a rate from its interval.
2. Never write about an individual patient, case, document or clinician. There are none in the JSON and
   there must be none in your text.
3. Do not propose actions or owners: they are given. When you discuss an action, name its owner.
4. When a criterion's interval is provisional, say so and give the reason exactly as written in
   provisional_reason.
5. Refer to criteria by id (H1, H2, ...), organisations as Org-nn, reasons by their code.
6. British English, plain prose, no bullet points, no headings, no markdown.
7. Keep each field within its word limit: summary 120, where/why/who 60 each, actions_note 80,
   caveats_note 80.

Write: a summary of where time is lost and why; for each criterion three short paragraphs — where
(rate, interval, reviewed count, what it means), why (reason breakdown, stalled versus legitimate wait),
who (segments and organisation outliers); an actions note (how the listed actions and owners follow
from the findings); and a caveats note (what the provisional flags, abstentions and unverified
citations mean for reading the figures)."""


class CriterionProse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    where: str
    why: str
    who: str


class Prose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    criteria: dict[str, CriterionProse]
    actions_note: str
    caveats_note: str


class ProseRejection(BaseModel):
    section: str
    tokens: list[str]
    reason: str


class ProseUnavailable(RuntimeError):
    """The reporter did not return a usable reply after the retry; the report falls back to empty_prose."""


def prose_schema(criterion_ids: list[str]) -> dict:
    s = {"type": "string"}
    per = {"type": "object", "additionalProperties": False, "required": ["where", "why", "who"],
           "properties": {"where": s, "why": s, "who": s}}
    return {"type": "object", "additionalProperties": False,
            "required": ["summary", "criteria", "actions_note", "caveats_note"],
            "properties": {"summary": s,
                           "criteria": {"type": "object", "additionalProperties": False, "required": list(criterion_ids),
                                        "properties": {cid: per for cid in criterion_ids}},
                           "actions_note": s, "caveats_note": s}}


def system_prompt() -> str:
    return SYSTEM_PROMPT


def prompt_version(model: str, max_tokens: int) -> str:
    blob = (SYSTEM_PROMPT + json.dumps(prose_schema(["X"]), sort_keys=True) + model + str(max_tokens)
            + str(SMALL_INT_MAX) + NUMBER_WORD_RE.pattern)
    return "rpt-" + hashlib.sha256(blob.encode()).hexdigest()[:12]


def empty_prose(criterion_ids: list[str], text: str = UNAVAILABLE) -> Prose:
    return Prose(summary=text, criteria={c: CriterionProse(where=text, why=text, who=text) for c in criterion_ids},
                 actions_note=text, caveats_note=text)


# Suffix is captured on its own (no leading hyphen/space) so a hyphenated form ("24-hour") and a
# spelled-out one ("24 hours") both classify the same way; the connector between the digits and the
# suffix is consumed outside the group.
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?(?:-?\s*(%|percent\b|per\s+cent\b|hours?\b|hrs?\b|h\b))?")
RATE_SUFFIXES = {"%", "percent", "per cent"}
CRIT_RE = re.compile(r"\bH\d+\b", re.IGNORECASE)
ORG_RE = re.compile(r"\bOrg-\d+\b", re.IGNORECASE)
CODE_RE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b[0-9a-f]{32}\b", re.IGNORECASE)
# "1 in 3 cases", "nine in ten", "one out of four" — a proportion spelled with "in"/"out of" is
# rejected outright even though both sides may be small integers exempt from the numeric scan on
# their own; matched on the ORIGINAL text (not the compound-blanked copy) and never folded into
# prompt_version (a checker tightening, not a prompt change).
PROPORTION_RE = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"\s+(?:in|out of)\s+"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)
# Bounded compound identifiers that must be matched (and checked against kinds["id"]) as a single
# token before NUM_RE ever sees them: ISO weeks, ISO dates, numeric bands ("40-59", "0-17") and open
# bands ("80+"). The lookbehind refuses to start a match right after a digit or a dot, so a fabricated
# number that merely CONTAINS an allowed token ("140-591", "20200") does not itself match as a compound
# (it is left to NUM_RE, which flags it). The lookahead refuses to end a match right before a digit,
# or before a "." that is itself followed by a digit — the latter, not a bare trailing ".", so a
# hyphenated CI such as "10.0-50.0" is not mis-split (the decimal after the hyphen blocks "0-50") while
# a compound at the end of a sentence ("...to 2020-12-31.") still matches whole.
COMPOUND_RE = re.compile(r"(?<![\d.])(\d{4}-W\d{2}|\d{4}-\d{2}-\d{2}|\d+-\d+|\d+\+)(?!\d)(?!\.\d)")
# Spelled-out figures that would otherwise dodge NUM_RE entirely: thirteen and up, with an optional
# hyphenated unit ("twenty-nine"), the big multipliers, and the fraction/multiplier words that also
# encode a proportion in prose. Zero..twelve are left alone — they mirror the SMALL_INT_MAX exemption.
NUMBER_WORD_RE = re.compile(
    r"\b(?:thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
    r"|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:-(?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|hundreds?|thousands?|millions?"
    r"|half|thirds?|quarters?|fifths?|double|triple|twice)\b",
    re.IGNORECASE,
)
# Extra spelled-out words that must NOT move prompt_version's fixture key (NUMBER_WORD_RE.pattern IS
# folded into the blob) — kept in a separate regex applied the same way as NUMBER_WORD_RE.
NUMBER_WORD_EXTRA_RE = re.compile(
    r"\b(?:dozens?|tenths?|sixths?|sevenths?|eighths?|ninths?|twentieths?)\b",
    re.IGNORECASE,
)


def _suffix_kind(suffix: str | None) -> str | None:
    if suffix is None:
        return None
    return "rate" if re.sub(r"\s+", " ", suffix.lower()) in RATE_SUFFIXES else "hours"


def _offending_tokens(text: str, kinds: dict[str, set[str]], vocab: Vocab) -> list[str]:
    bad: list[str] = []
    # A whole compound token not in kinds["id"] is itself the offence (its digits are never checked
    # piecemeal); a compound that IS an allowed id token is blanked out of the copy NUM_RE scans, so
    # e.g. "40-59" or "2020-W12" is consumed whole rather than split into two bare numbers.
    bad += [m.group(0) for m in COMPOUND_RE.finditer(text) if m.group(0) not in kinds["id"]]
    blanked = COMPOUND_RE.sub(" ", text)
    if ID_RE.search(text):
        bad.append("identifier")
    bad += [m.group(0) for m in NUMBER_WORD_RE.finditer(text)]
    bad += [m.group(0) for m in NUMBER_WORD_EXTRA_RE.finditer(text)]
    bad += [m.group(0) for m in PROPORTION_RE.finditer(text)]
    everything = kinds["rate"] | kinds["hours"] | kinds["count"] | kinds["id"]
    for m in NUM_RE.finditer(blanked):
        raw = m.group(0)
        number = re.match(r"\d[\d,]*(?:\.\d+)?", raw).group(0).replace(",", "")
        kind = _suffix_kind(m.group(1))
        if kind == "rate":
            ok = number in kinds["rate"]
        elif kind == "hours":
            ok = number in kinds["hours"] or number in kinds["count"]
        else:
            ok = number in everything or (number.isdigit() and int(number) <= SMALL_INT_MAX)
        if not ok:
            bad.append(number)
    all_codes = set().union(*vocab.reasons.values()) if vocab.reasons else set()
    bad += [t for t in CRIT_RE.findall(text) if t not in kinds["id"]]
    bad += [t for t in ORG_RE.findall(text) if t not in kinds["id"]]
    bad += [t for t in CODE_RE.findall(text) if t in all_codes and t not in kinds["id"]]
    return bad


def _sections(prose: Prose):
    yield "summary", prose.summary, WORD_LIMITS["summary"]
    for cid, cp in prose.criteria.items():
        for part in ("where", "why", "who"):
            yield f"criteria.{cid}.{part}", getattr(cp, part), WORD_LIMITS[part]
    yield "actions_note", prose.actions_note, WORD_LIMITS["actions_note"]
    yield "caveats_note", prose.caveats_note, WORD_LIMITS["caveats_note"]


def _set_section(prose: Prose, section: str, text: str) -> None:
    if section.startswith("criteria."):
        _, cid, part = section.split(".")
        setattr(prose.criteria[cid], part, text)
    else:
        setattr(prose, section, text)


def check_prose(prose: Prose, payload: Payload, vocab: Vocab) -> tuple[Prose, list[ProseRejection]]:
    """Every number, criterion id, Org-nn and reason code in a paragraph must be a printed token of the
    payload — a %-suffixed figure must be a printed rate and an h-suffixed one an hours/count figure,
    not just any printed number; any identifier-shaped string, spelled-out number word, or an
    over-length paragraph fails. A failed paragraph becomes FALLBACK; nothing is rewritten."""
    kinds = printed_tokens_by_kind(payload)
    out = prose.model_copy(deep=True)
    rejections: list[ProseRejection] = []
    for section, text, limit in list(_sections(out)):
        if len(text.split()) > limit * 1.2:
            rejections.append(ProseRejection(section=section, tokens=[], reason="over length"))
            _set_section(out, section, FALLBACK_LENGTH)
            continue
        bad = _offending_tokens(text, kinds, vocab)
        if bad:
            rejections.append(ProseRejection(section=section, tokens=sorted(set(bad)), reason="token not in payload"))
            _set_section(out, section, FALLBACK)
    return out, rejections


RETRIES = 1


class Reporter(Protocol):
    def reply(self, system: str, user: str, schema: dict) -> dict: ...


class VLLMReporter:
    """OpenAI-compatible guided JSON via ModelClient (record/replay applies)."""

    def __init__(self, client: ModelClient, max_tokens: int = 2048):
        self.client, self.max_tokens = client, max_tokens

    def reply(self, system: str, user: str, schema: dict) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            content, finish = self.client.chat_full(
                messages, json_schema=schema, temperature=0.0, max_tokens=self.max_tokens
            )
        except httpx.HTTPError as e:
            raise ModelJSONError(f"reporter HTTP error: {e}") from e
        if finish == "length":
            raise ModelJSONError("reporter reply truncated (finish_reason=length)")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ModelJSONError(f"reporter returned non-JSON: {content[:200]!r}") from e


class ClaudeReporter:
    def __init__(self, cli: ClaudeCLI):
        self.cli = cli

    def reply(self, system: str, user: str, schema: dict) -> dict:
        return self.cli.chat_json(system, user, schema)


def user_message(payload: Payload) -> str:
    """Compact, not indented: on the real cohort the indented form pushed the prompt one token over
    the reporter's 12,288-token context (10,241 input tokens against a 10,240 budget at max_tokens =
    2048) — indentation whitespace is pure overhead for a machine reader. `ensure_ascii=False` keeps
    the real "%"/"–" characters as one glyph each rather than a 6-character backslash-u escape."""
    return json.dumps(payload.for_model(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def ask_model(reporter: Reporter, payload: Payload, criterion_ids: list[str]) -> Prose:
    """One call, one retry; the reply must parse as Prose for exactly the given criteria."""
    schema = prose_schema(criterion_ids)
    user = user_message(payload)
    last: Exception | None = None
    for _ in range(RETRIES + 1):
        try:
            raw = reporter.reply(system_prompt(), user, schema)
            prose = Prose.model_validate(raw)
            if set(prose.criteria) != set(criterion_ids):
                raise ModelJSONError(f"reporter criteria {sorted(prose.criteria)} != {sorted(criterion_ids)}")
            return prose
        except (ModelJSONError, ValueError) as e:  # pydantic ValidationError is a ValueError
            last = e
    raise ProseUnavailable(str(last))
