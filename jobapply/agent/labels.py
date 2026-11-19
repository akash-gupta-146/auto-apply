"""What the words on buttons and fields mean, for the planner, the guard and the page classifier alike.

Plain English words, never a site's own names: nothing here knows any one job site.
"""
from __future__ import annotations

import re

from ..ai_answers import CONSENT  # a declaration or agreement: never settled by an AI

# A whole label, so "Apply filters" and "Apply coupon" are not the way in to an application, nor "Apply using LinkedIn" (that needs a login of yours).
# Job sites word it many ways: "Apply To Position" (Breezy, whose button the agent once could not find), "Apply for this opportunity", "Apply directly
# on employer's site" (HiringCafe)...
APPLY_LABEL = re.compile(
    r"^\W*(?:(?:easy|quick|1-click) )?apply(?: directly)?"
    r"(?: now| here| today| online| externally"
    r"| (?:to|for) (?:this |the |a |an )?(?:job|role|position|opportunity|opening|vacancy|posting)(?: now| today| online)?"
    r"| on (?:the )?(?:company|employer)(?:'s|\u2019s)? (?:site|website|page))?\W*$"
    r"|^\W*start (?:your |an |the )?application\b|^\W*i'?m interested\W*$", re.I)
# Pressing it may send the application.
SUBMIT_LABEL = re.compile(r"\b(?:submit|send|finish|complete|confirm)\b.{0,20}\bapplication\b|^\W*(?:submit|send|finish|confirm and submit|submit and apply)\W*$", re.I)
# On an application page, any of these words may mean "send it". Over-cautious on purpose: a needless approval costs you a click,
# while a missed one sends an application you did not approve.
MAY_SEND = re.compile(r"\b(?:submit|send|apply|finish|confirm|complete|done|agree)\b", re.I)
# Pressing it moves a form on, and sends nothing.
CONTINUE_LABEL = re.compile(
    r"^\W*(?:save (?:and|&) )?(?:continue|next|proceed|review|next step|go to next|review (?:and|&) submit|save (?:and|&) next)\W*$"
    r"|^\W*continue to \w+", re.I)
# Needs a person: the agent never types a password or creates an account.
LOGIN_LABEL = re.compile(r"\b(?:sign ?in|log ?in|sign ?up|register|create (?:an |your )?account|join now|continue with (?:google|linkedin|facebook|apple|github))\b", re.I)
# Never pressed, whatever planned it.
DENY_LABEL = re.compile(r"\b(?:sign ?out|log ?out|delete|withdraw|unsubscribe|subscribe|pay|buy|purchase|upgrade|premium|download|install|share|report|block|deactivate)\b", re.I)
# A name that says only what kind of control it is. Some sites' form libraries put it on every box ("aria-label=textbox"), and a form library's
# `name="field-39"`-style attribute is no better. It is no question: never asked about, never saved as one. (No backslashes: it is also built into
# the page-reading script, which must see the same words.)
GENERIC_NAME = re.compile(r"^(?:text ?box|text ?field|text ?area|text|input|field|edit|editor|combo ?box|select|dropdown|value)$|^(?:field|input|text|q|question)[-_ ]?[0-9]+$", re.I)

# A field the agent never types into: it belongs to the person, or to a security check.
SECRET_FIELD = re.compile(r"\b(?:password|passcode|otp|one[- ]time|verification code|security code|captcha|cvv|card number)\b", re.I)
# Legally significant: only an answer you saved yourself is used, never the AI's.
LEGAL = re.compile(r"\b(?:sponsor\w*|work(?:ing)? authori[sz]\w*|authori[sz]ed to work|legally|right to work|visa|criminal|convict\w*|background check|clearance)\b", re.I)
CONFIRMED = re.compile(
    r"\b(?:application (?:has been |was )?(?:submitted|sent|received)|thank(?:s| you) for applying|successfully (?:applied|submitted)"
    r"|we(?:'ve| have) received your application|your application (?:is|has been) (?:in|complete|received))\b", re.I)
# A widget that sits on a job page but is not part of an application: a bookmark, a follow, a share, a job-alert or newsletter sign-up.
# It is never filled in, and it never makes a job page look like an application form.
SIDE_WIDGET = re.compile(
    r"\b(?:save(?:d)?(?: this)? jobs?|bookmark\w*|favou?rite\w*|follow(?: us| this| company)?|share|subscribe|newsletter|job alerts?|"
    r"get notified|notify me|similar jobs|stay (?:in touch|updated)|talent (?:community|network)|join (?:our|the) talent)\b", re.I)
SEARCH_BOX = re.compile(r"\b(?:search|keywords?|find jobs?|job title, keywords)\b", re.I)


def sends(label: str, in_application: bool) -> bool:
    """May pressing this button send the application? Asked by the planner (to know the last step) and by the guard (to hold it)."""
    return bool(SUBMIT_LABEL.search(label) or (in_application and MAY_SEND.search(label)))


def is_generic(question: str) -> bool:
    """The name of a box says only what kind of box it is (or is nothing), so there is no question to answer, and none to save an answer under."""
    return not question.strip().rstrip("*").strip() or bool(GENERIC_NAME.match(question.strip().rstrip("*").strip()))


def is_consent(*texts: str) -> bool:
    return any(CONSENT.search(text or "") for text in texts)


def is_secret(*texts: str) -> bool:
    return any(SECRET_FIELD.search(text or "") for text in texts)
