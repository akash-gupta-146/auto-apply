"""What a resume says about you in so many words: where you are, what you do and for whom, how you studied, how you
can be found online. Plain pattern matching, so it answers only when the page is clear. Whatever it cannot find is
left out (the form shows an empty box, and the AI Fill button can have a go). Each answer is a suggestion the person
checks before saving.

Resumes are laid out in many ways; these are the common ones: "Company, City - Title  Jan 2020 - Present",
"Title at Company | dates", "Title @ Company" in the header, and a company line followed by a title line.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

CITIES = (
    "Navi Mumbai", "Greater Noida", "New Delhi", "Thiruvananthapuram", "Visakhapatnam", "Bengaluru", "Bangalore",
    "Hyderabad", "Pune", "Mumbai", "Thane", "Delhi", "Gurugram", "Gurgaon", "Noida", "Ghaziabad", "Faridabad",
    "Chennai", "Kolkata", "Ahmedabad", "Jaipur", "Chandigarh", "Mohali", "Kochi", "Cochin", "Trivandrum",
    "Coimbatore", "Indore", "Bhopal", "Nagpur", "Lucknow", "Surat", "Vadodara", "Vijayawada", "Mysuru", "Mysore",
    "Mangaluru", "Bhubaneswar", "Patna", "Ranchi", "Nashik", "Kanpur", "Dehradun", "Raipur",
)
CITY = re.compile(r"\b(?:" + "|".join(sorted(CITIES, key=len, reverse=True)) + r")\b", re.I)
# "NIT Raipur", "University of Pune", "Pune University": a city's name inside a college's name is not where the
# person lives. Separate passes, in this order: one pattern would match "at University" and leave "of Pune" behind.
INSTITUTES = (
    re.compile(r"\b(?:University|Institute|College)\s+of\s+\w+"),
    re.compile(r"\b(?:NIT|NITK|IIT|IIIT|IIM|BITS|VIT|SRM)\s+\w+"),
    re.compile(r"\b\w+\s+(?:University|Institute|College)\b"),
)

TITLE = re.compile(r"\b(?:engineer|developer|manager|lead|architect|analyst|designer|consultant|scientist|administrator"
                   r"|specialist|officer|director|tester|programmer|intern|associate|executive|head|sdet|devops"
                   r"|strategist|coordinator|founder|owner)\b", re.I)
EXPERIENCE_HEADING = re.compile(r"^\W*(?:work|professional|employment|relevant|career)?\s*(?:experience|history)\W*$", re.I)
EDUCATION_HEADING = re.compile(r"^\W*(?:education|academics?|academic\s+(?:background|qualifications?)|qualifications?)\W*$", re.I)
BULLET = re.compile(r"^\s*[-•*▪◦·–]\s")
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*"
DATE = rf"(?:{MONTH})?(?:19|20)\d\d"
DATE_RANGE = re.compile(rf"\(?\b{DATE}\s*(?:-|–|—|to)\s*(?:present|current|now|till date|{DATE})\b\)?", re.I)
EXPERIENCE_YEARS = re.compile(r"\d+\+?\s*(?:years?|yrs?)\b", re.I)
SPLITTERS = re.compile(r"\s+at\s+|\s*@\s*|\s*\|\s*|\s+[-–—]\s+", re.I)

DEGREE = re.compile(  # case matters: "BE" is a degree, "be" is a word
    r"\b(?:Bachelor|Master|Doctor|Diploma|B\.?\s?Tech|M\.?\s?Tech|B\.?\s?E\.?|M\.?\s?E\.?|B\.?\s?Sc|M\.?\s?Sc"
    r"|B\.?\s?C\.?\s?A|M\.?\s?C\.?\s?A|MBA|PGDM|B\.?\s?Com|M\.?\s?Com|Ph\.?\s?D|B\.?\s?A\.|M\.?\s?A\.)(?![A-Za-z])")
COLLEGE = re.compile(r"\b(?:university|institute|college|school|academy|IIT|NIT|IIIT|BITS)\b", re.I)

LINKEDIN = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[\w\-%]+", re.I)
GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([\w\-]+)", re.I)
URL = re.compile(r"(?:https?://|www\.)[^\s|,;<>()]+", re.I)

AMOUNT = (r"(\d[\d,.]*\s*(?:(?:lpa|lacs?|lakhs?|l|k|cr|crores?)\b)?"
          r"(?:\s*(?:per annum|per year|p\.?a\.?|/\s*annum))?)")
CURRENT_CTC = re.compile(r"(?:(?:current|present)\s*(?:ctc|salary|compensation|package)|\bcctc)\s*[:\-–—]?\s*(?:is\s*)?(?:₹|rs\.?|inr)?\s*" + AMOUNT, re.I)
EXPECTED_CTC = re.compile(r"(?:(?:expected|desired)\s*(?:ctc|salary|compensation|package)|\bectc)\s*[:\-–—]?\s*(?:is\s*)?(?:₹|rs\.?|inr)?\s*" + AMOUNT, re.I)
NOTICE = re.compile(r"notice\s*period\s*(?:is|:|-|–|—)?\s*([^\n|;]{1,40})", re.I)
IMMEDIATE = re.compile(r"\bimmediate(?:ly)?\s+(?:joiner|joining|available)\b", re.I)
LABELLED = {
    "city": re.compile(r"(?:current\s+)?(?:location|city)\s*[:\-–]\s*([^\n|;,]{2,40})", re.I),
    "current_title": re.compile(r"current\s+(?:designation|role|title|position|job\s+title)\s*[:\-–]\s*([^\n|;]{2,70})", re.I),
    "current_company": re.compile(r"current\s+(?:company|employer|organi[sz]ation)\s*[:\-–]\s*([^\n|;]{2,70})", re.I),
}


def _flat(text: str) -> str:
    return " ".join(text.split())


def _clip(text: str) -> str:
    """The first column of a line (a gap of three spaces starts the next one), without trailing punctuation."""
    return re.split(r"\s{3,}", text.strip())[0].strip(" .,:;-–—|")


def _labelled(text: str, pattern: "re.Pattern[str]") -> str:
    match = pattern.search(text)
    return _clip(match.group(1)) if match else ""


def _section(lines: List[str], heading: "re.Pattern[str]", count: int) -> List[str]:
    """The first few lines under a heading such as 'Work Experience' (empty when there is no such heading)."""
    for number, line in enumerate(lines):
        if len(line.strip()) <= 40 and heading.match(_flat(line)):
            return lines[number + 1:number + 1 + count]
    return []


def _split_place(company: str) -> Tuple[str, str]:
    """'Acme Widgets, Bengaluru' -> ('Acme Widgets', 'Bengaluru'): a city after the company is where the job is."""
    head, _, tail = company.rpartition(",")
    if head and CITY.fullmatch(tail.strip()):
        return head.strip(), tail.strip().title()
    return company, ""


def _job_entry(line: str) -> Optional[Tuple[str, str, str]]:
    """(title, company, place) from one line of the experience list; company/place may be empty. None: not a job line."""
    clean = _flat(DATE_RANGE.sub(" ", line)).strip(" |,-–—•·")
    if not 2 < len(clean) <= 110 or not TITLE.search(clean):
        return None
    parts = [part.strip(" ,") for part in SPLITTERS.split(clean) if part.strip(" ,")]
    if len(parts) == 1 and clean.count(",") == 1:  # "Senior Engineer, Acme Corp"
        parts = [part.strip() for part in clean.split(",")]
    titled = [n for n, part in enumerate(parts) if TITLE.search(part) and not EXPERIENCE_YEARS.search(part)]
    if not titled or len(parts[titled[0]]) > 70:
        return None
    title = parts[titled[0]]
    others = [part for n, part in enumerate(parts) if n != titled[0] and not EXPERIENCE_YEARS.search(part)]
    others.sort(key=lambda part: bool(TITLE.search(part)))  # a company is rarely named like a job
    company, place = _split_place(others[0]) if others else ("", "")
    return title, company, place


def _neighbour_company(section: List[str], at: int) -> Tuple[str, str]:
    """The company is on the line above the title (or below it)."""
    for number in (at - 1, at + 1):
        if 0 <= number < len(section) and not BULLET.match(section[number]):
            guess = _flat(DATE_RANGE.sub(" ", section[number])).strip(" |,-–—•·")
            if 2 < len(guess) <= 60 and not TITLE.search(guess):
                return _split_place(guess)
    return "", ""


def _current_job(lines: List[str]) -> Tuple[str, str, str]:
    """(title, company, place) of the newest job: the first entry under Experience, else the header's 'Title @ Company'."""
    section = _section(lines, EXPERIENCE_HEADING, 8)
    for number, line in enumerate(section):
        entry = None if BULLET.match(line) else _job_entry(line)
        if entry:
            title, company, place = entry
            if not company:
                company, place = _neighbour_company(section, number)
            return title, company, place
    for line in lines[:6]:
        entry = _job_entry(line) if re.search(r"\s(?:@|at)\s", line, re.I) else None
        if entry and entry[1]:
            return entry
    return "", "", ""


def _without_colleges(line: str) -> str:
    for pattern in INSTITUTES:
        line = pattern.sub(" ", line)
    return line


def _header_city(lines: List[str]) -> str:
    for line in lines[:8]:
        match = CITY.search(_without_colleges(line))
        if match:
            return match.group(0).title()
    return ""


def _education(lines: List[str]) -> str:
    section = _section(lines, EDUCATION_HEADING, 8)
    for number, line in enumerate(section):
        if not DEGREE.search(line):
            continue
        text = _flat(re.sub(r"\s{3,}", ", ", line.strip()))
        following = _flat(section[number + 1]) if number + 1 < len(section) else ""
        if following and COLLEGE.search(following) and not COLLEGE.search(text) and not DEGREE.search(following) \
                and len(text) + len(following) < 150:
            text += ", " + following  # the college on the line below the degree
        return text[:160]
    return ""


def _amount(pattern: "re.Pattern[str]", text: str) -> str:
    match = pattern.search(text)
    return _flat(match.group(1)).strip(" .,") if match else ""


def _notice_period(text: str) -> str:
    value = _labelled(text, NOTICE)
    if value:
        return value[0].upper() + value[1:]
    match = IMMEDIATE.search(text)
    return match.group(0).capitalize() if match else ""


def _with_scheme(address: str) -> str:
    return address if address.lower().startswith("http") else "https://" + address


def _links(text: str) -> Tuple[str, str, str]:
    """(linkedin, github, portfolio): the first of each. Only a full web address counts as a portfolio."""
    linkedin = LINKEDIN.search(text)
    github = GITHUB.search(text)
    portfolio = ""
    for match in URL.finditer(text):
        address = match.group(0).rstrip(".,)")
        if not re.search(r"linkedin\.com|github\.com", address, re.I):
            portfolio = address
            break
    return (_with_scheme(linkedin.group(0)) if linkedin else "",
            f"https://github.com/{github.group(1)}" if github else "",
            _with_scheme(portfolio) if portfolio else "")


def extract_details(text: str) -> Dict[str, str]:
    """The details the resume states, keyed like the boxes of the details form. Only what was found is returned."""
    lines = [line for line in text.splitlines() if line.strip()]
    title, company, place = _current_job(lines)
    linkedin, github, portfolio = _links(text)
    found = {
        "city": _labelled(text, LABELLED["city"]) or place or _header_city(lines),
        "current_title": _labelled(text, LABELLED["current_title"]) or title,
        "current_company": _labelled(text, LABELLED["current_company"]) or company,
        "education": _education(lines),
        "notice_period": _notice_period(text),
        "current_ctc": _amount(CURRENT_CTC, text),
        "expected_ctc": _amount(EXPECTED_CTC, text),
        "linkedin": linkedin, "github": github, "portfolio": portfolio,
    }
    return {key: value for key, value in found.items() if value}
