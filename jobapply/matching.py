"""Decide whether a job is worth applying to. Pure code: zero LLM requests."""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, NamedTuple, Optional, Set

from .config import Criteria, Profile
from .experience import years_asked
from .models import Job
from .skills_vocab import _canonical, detect_skills

NEUTRAL_SCORE = 50  # job text names too few known skills to judge: trust the title match
MIN_SKILLS_TO_JUDGE = 2
STRONG_SKILLS = 60  # percent of the skills a job names that are yours: a nice-to-have, never a must
RANKS = {"Skip": 0, "Low": 1, "Medium": 2, "High": 3}
MATCH = "match"  # the reason of a job whose title is one of the roles asked for
SUGGESTED = "suggested"  # the reason of a job taken only because the site suggested it: nothing was matched

# "Similar role": a generic title ("Software Developer - SDE II") for a job whose TEXT is about the roles asked for.
GENERIC_NOUN = "engineer"  # what developer / sde / programmer become (SYNONYMS below)
SIMILAR_MIN_MENTIONS = 3  # focus words the job text must use, in total (one stray "frontend team" is not a frontend job)
LEVEL_WORDS = {"senior", "sr", "sr.", "lead", "staff", "principal", "junior", "jr", "jr.", "associate", "software"}

# Keywords: the person's own words for a good job. One whose title, experience or description uses enough of them is
# a fit even when its title is not in the list of roles.
KEYWORD_MIN_HITS = 2  # different keywords a job must use (all of them, when fewer than this were given)


class Decision(NamedTuple):
    ok: bool
    reason: str
    score: float
    rescuable: bool = False  # rejected only for its title: an AI reading the description may still overturn it


# Job titles spell the same role many ways: "Front End Developer" must match "frontend engineer".
PHRASES = [
    (r"\bfront[\s-]?end\b", "frontend"),
    (r"\bback[\s-]?end\b", "backend"),
    (r"\bfull[\s-]?stack\b", "fullstack"),
    (r"\breact(?:[\s.]?js)?\b", "react"),
    (r"\buser[\s-]?interface\b", "ui"),
]
SYNONYMS = {"developer": "engineer", "dev": "engineer", "programmer": "engineer", "sde": "engineer"}


def _words(text: str) -> List[str]:
    lowered = text.lower()
    for pattern, replacement in PHRASES:
        lowered = re.sub(pattern, replacement, lowered)
    # "+" belongs to a word only as "c++" (in "React+Javascript" it separates two words), and a "." only inside
    # one ("node.js", ".net"): at the end it is a full stop ("...built with React.")
    raw = re.findall(r"[a-z0-9#.]+(?:\+\+)?", lowered)
    return [SYNONYMS.get(word, word) for word in (w.rstrip(".") for w in raw) if word]


def _tokens(text: str) -> Set[str]:
    return set(_words(text))


def title_matches(title: str, roles) -> bool:
    """True when every word of any role appears in the title (order-free)."""
    title_tokens = _tokens(title)
    return any(_tokens(role) <= title_tokens for role in roles if role.strip())


def focus_words(roles: Iterable[str]) -> Set[str]:
    """What makes the roles what they are: "frontend engineer", "react developer" -> {frontend, react}."""
    words: Set[str] = set()
    for role in roles:
        words |= _tokens(role)
    return words - {GENERIC_NOUN} - LEVEL_WORDS


def similar_role_evidence(job: Job, roles: Iterable[str]) -> Optional[str]:
    """Why a title that is NOT one of the roles may still be the same kind of job, else None.

    Needs a generic engineering title and a job text that keeps talking about the roles' focus words.
    "Backend Engineer", "Engineering Manager" and "Fullstack Architect" fail the first test;
    a Java or data job that never says frontend or react fails the second.
    """
    focus = focus_words(roles)
    if not focus or GENERIC_NOUN not in _tokens(job.title):
        return None
    seen = Counter(word for word in _words(f"{job.title}\n{job.description}") if word in focus)
    if sum(seen.values()) < SIMILAR_MIN_MENTIONS:
        return None
    return ", ".join(f"{word} x{count}" for word, count in seen.most_common())


def _mentions(words: List[str], phrase: List[str]) -> bool:
    """True when the phrase's words stand next to each other, in order, among the text's words."""
    size = len(phrase)
    return size > 0 and any(words[start:start + size] == phrase for start in range(len(words) - size + 1))


def keyword_evidence(job: Job, keywords: Iterable[str]) -> Optional[str]:
    """Where the job uses your keywords, or None when it uses too few of them to call it a fit.

    Reads the title, the experience the job asks for, and the description (where a posting names its role).
    Spelling variants count as the same word ("Front End" is "frontend"), exactly as in title matching.
    """
    wanted: Dict[str, str] = {}
    for keyword in keywords:
        if keyword.strip():
            wanted.setdefault(keyword.strip().lower(), keyword.strip())  # a repeat counts once, as first spelt
    if not wanted:
        return None
    parts = {name: _words(text) for name, text in
             (("title", job.title), ("experience", job.experience), ("description", job.description))}
    found = []
    for keyword in wanted.values():
        phrase = _words(keyword)
        places = [name for name, words in parts.items() if _mentions(words, phrase)]
        if places:
            found.append(f"{keyword} ({'/'.join(places)})")
    return ", ".join(found) if len(found) >= min(KEYWORD_MIN_HITS, len(wanted)) else None


def skills_in_common(job: Job, profile: Profile) -> Optional[str]:
    """The broadest way in: a generic engineering title whose text names skills you have. The caller still applies min_score.

    The title test is what keeps managers, architects and designers out, however well their text reads.
    """
    if GENERIC_NOUN not in _tokens(job.title):
        return None
    mine = {_canonical(skill) for skill in profile.skills}
    shared = sorted(detect_skills(f"{job.title}\n{job.description}") & mine)
    return ", ".join(shared[:6]) or None


def other_ways_in(job: Job, criteria: Criteria) -> List[str]:
    """Why a job whose title is not one of your roles may still be right for you: a similar role, or your keywords."""
    reasons = []
    similar = similar_role_evidence(job, criteria.target_roles) if criteria.similar_roles else None
    if similar:
        reasons.append(f"similar role, the job text mentions {similar}")
    keywords = keyword_evidence(job, criteria.keywords)
    if keywords:
        reasons.append(f"keyword fit: {keywords}")
    return reasons


def parse_salary_lpa(text: str) -> Optional[float]:
    """Best-effort top-of-range salary in INR lakhs per annum, else None."""
    lowered = (text or "").lower().replace(",", "")
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", lowered)]
    if not numbers or "not disclosed" in lowered or "month" in lowered:
        return None
    if "lac" in lowered or "lpa" in lowered:
        return max(numbers)
    if ("₹" in lowered or "inr" in lowered) and max(numbers) >= 100_000:
        return max(numbers) / 100_000
    return None


def skill_score(job: Job, profile: Profile) -> float:
    wanted = detect_skills(f"{job.title}\n{job.description}")
    if len(wanted) < MIN_SKILLS_TO_JUDGE:
        return NEUTRAL_SCORE
    mine = {_canonical(skill) for skill in profile.skills}
    return round(100 * len(wanted & mine) / len(wanted))


def blocked_reason(job: Job, criteria: Criteria) -> Optional[str]:
    """Why a company is off the list for good, or None. This is a "never", not a match: every kind of run honours it."""
    company = job.company.lower()
    if any(blocked.lower() in company for blocked in criteria.blocked_companies if blocked.strip()):
        return f"blocked company: {job.company}"
    return None


class Fit(NamedTuple):
    rating: str  # Skip / Low / Medium / High
    reasons: List[str]  # the dealbreaker, or the nice-to-haves the job has


def dealbreaker(job: Job, profile: Profile, criteria: Criteria) -> Optional[str]:
    """The first rung of the ladder: a "never". A word you listed, or an experience level too far from yours (read cautiously:
    see experience.py). Like a blocked company it is honoured by every kind of run, and no AI may overturn it."""
    words = _words(f"{job.title}\n{job.description}")
    for word in criteria.dealbreakers:
        if word.strip() and _mentions(words, _words(word)):
            return f"dealbreaker: {word.strip()}"
    asked, mine = years_asked(job.experience, job.description), profile.total_experience_years
    if asked and mine > 0:
        low, high = asked
        if criteria.max_years_below is not None and high is not None and mine - high > criteria.max_years_below:
            return f"too junior: it asks {low:g}-{high:g} years and you have {mine:g}"
        if criteria.max_years_above is not None and low - mine > criteria.max_years_above:
            return f"too senior: it asks {low:g}+ years and you have {mine:g}"
    return None


def rate(job: Job, profile: Profile, criteria: Criteria, score: float) -> Fit:
    """The proficiently ladder: a dealbreaker is Skip; otherwise the job already met your must-haves (its title, your skills) and
    is rated by its nice-to-haves: two or more High, one Medium, none Low. Plain checks you can read: no AI."""
    broke = dealbreaker(job, profile, criteria)
    if broke:
        return Fit("Skip", [broke])
    nice = []
    if score >= STRONG_SKILLS:
        nice.append(f"{score:.0f}% of its skills are yours")
    if keyword_evidence(job, criteria.keywords):
        nice.append("it uses your keywords")
    salary = parse_salary_lpa(job.salary)
    if criteria.min_salary_lpa and salary is not None and salary >= criteria.min_salary_lpa:
        nice.append(f"it pays {salary:g} LPA, over your {criteria.min_salary_lpa:g}")
    place = job.location.lower()
    if criteria.locations and ("remote" in place or any(city.strip().lower() in place for city in criteria.locations if city.strip())):
        nice.append("it is where you want to work")
    asked, mine = years_asked(job.experience, job.description), profile.total_experience_years
    if asked and mine > 0 and asked[0] <= mine and (asked[1] is None or mine <= asked[1]):
        nice.append("it asks for your level of experience")
    return Fit("High" if len(nice) >= 2 else "Medium" if nice else "Low", nice)


def fit_note(job: Job, profile: Profile, criteria: Criteria, decision: Decision) -> str:
    """The rating in plain words for the report, so an application can be audited. Empty when nothing was matched (suggested jobs)."""
    if decision.reason == SUGGESTED:
        return ""
    fit = rate(job, profile, criteria, decision.score)
    return f"fit {fit.rating}" + (f": {'; '.join(fit.reasons)}" if fit.reasons else "")


def accept_suggested(job: Job, profile: Profile, criteria: Criteria) -> Decision:
    """For "apply to every job the site suggests": no role, skill or salary test, only the "nevers": blocked companies and dealbreakers."""
    score = skill_score(job, profile)
    blocked = blocked_reason(job, criteria) or dealbreaker(job, profile, criteria)
    return Decision(False, blocked, score) if blocked else Decision(True, SUGGESTED, score)


def evaluate(job: Job, profile: Profile, criteria: Criteria) -> Decision:
    score = skill_score(job, profile)
    blocked = blocked_reason(job, criteria)
    if blocked:
        return Decision(False, blocked, score)
    if criteria.skip_roles and title_matches(job.title, criteria.skip_roles):
        return Decision(False, f"skip-role title: {job.title}", score)
    broke = dealbreaker(job, profile, criteria)
    if broke:
        return Decision(False, broke, score)  # a "never": not rescuable, so no AI reading the description may overturn it
    verdict, minimum = MATCH, criteria.min_score
    title_fits = not criteria.target_roles or title_matches(job.title, criteria.target_roles)
    if not title_fits:
        reasons = other_ways_in(job, criteria)
        common = None if reasons or not criteria.similar_roles else skills_in_common(job, profile)
        if common:
            reasons.append(f"skills in common: {common}")
        if not reasons:
            return Decision(False, f"title not in target roles: {job.title}", score, rescuable=True)
        verdict = "; ".join(reasons)
    if criteria.min_salary_lpa:
        salary = parse_salary_lpa(job.salary)
        if salary is not None and salary < criteria.min_salary_lpa:
            return Decision(False, f"salary {salary} LPA below minimum", score)
    if score < minimum:
        # A title that was not one of yours got in only on a guess (similar role, keywords) and the guess was not backed by
        # the skills: an AI reading the description may still overturn it. A title that WAS yours is not second-guessed.
        return Decision(False, f"skill match {score}% is below your minimum of {minimum}%", score, rescuable=not title_fits)
    fit = rate(job, profile, criteria, score)
    if RANKS[fit.rating] < RANKS.get(str(criteria.min_fit).title(), RANKS["Low"]):
        return Decision(False, f"fit {fit.rating} is below your minimum of {criteria.min_fit}", score)
    return Decision(True, verdict, score)


def why_it_fits(job: Job, profile: Profile, criteria: Criteria, decision: Decision) -> str:
    """The plain words for "why was this job applied to?": what let its title in, and how its skills compare to yours."""
    suggested = decision.reason == SUGGESTED
    if suggested:
        title = "the site suggested it and you chose to apply to every suggested job, so it was not matched against your roles or skills"
    elif decision.reason != MATCH:
        title = decision.reason  # a similar role, your keywords, skills in common or the AI's verdict: already in words
    else:
        role = next((r for r in criteria.target_roles if r.strip() and _tokens(r) <= _tokens(job.title)), None)
        title = f"the title fits your role '{role}'" if role else "you listed no target roles, so any title is allowed"
    wanted = detect_skills(f"{job.title}\n{job.description}")
    if len(wanted) < MIN_SKILLS_TO_JUDGE:
        return title if suggested else f"{title}; the job names too few skills to compare, so the title decided"
    shared = sorted(wanted & {_canonical(skill) for skill in profile.skills})
    lead, minimum = ("for information, ", "") if suggested else ("", f"; your minimum is {criteria.min_score}%")
    return f"{title}; {lead}{decision.score:.0f}% of the {len(wanted)} skills it names are yours ({', '.join(shared[:6]) or 'none'}{minimum})"
