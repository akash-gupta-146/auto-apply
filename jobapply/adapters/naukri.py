"""Naukri.com adapter.

Flow: search URL -> the page's own JSON job list (see naukri_api.py) -> goto each job URL
(never click: it opens new tabs) -> "Apply": usually one click using the profile resume;
sometimes a chatbot Q&A.

Discovery reads network responses, not page markup (Naukri's new UI hides job links and uses
obfuscated classes). The job-PAGE and apply selectors below are still UNVERIFIED guesses and live
in SEL so repairs are one-line edits. Run `jobapply probe naukri`; failures save to data/failures/.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable, Iterator, List, Optional

from ..models import Job, JobCard, NotLoggedIn, Result, Status
from .base import Adapter, first_visible, find_salary, slug
from .naukri_api import (
    apply_questions, card_from_item, job_detail, job_items, logged_in_flag, paged_url, plain_text, salary_text,
)

HOME = "https://www.naukri.com/mnjuser/homepage"
RECOMMENDED = "https://www.naukri.com/mnjuser/recommendedjobs"
PROFILE = "https://www.naukri.com/mnjuser/profile"
MAX_PAGES = 3
MAX_CHAT_STEPS = 15
CAPTURE_POLLS = 24  # x 0.5s: how long to wait for the page's job calls
VERIFY_RELOADS = 2  # how many times to reload and look for Naukri's own "applied" state
log = logging.getLogger("jobapply")
QUIET_POLLS = 4  # x 0.5s with no new response, once jobs were seen, means the page is done

SEL = {
    # Verified live (new "TopTier" UI): a floating pill button reading "Quick apply". Its text is the SAME
    # before and after applying (a hidden "Applied" label lives inside it); the only difference is the
    # `disabled` attribute: applied job -> disabled, untouched job -> enabled.
    "apply": "button:has-text('Quick apply')",
    "dialog": "[role='dialog']",
    # Everything below is from the OLD UI and UNVERIFIED against the new one.
    "chatbot": "[class*='chatbot_Drawer'], .chatbot_DrawerContentWrapper",
    "bot_message": "[class*='botMsg'], .botItem, [class*='botItem']",
    "chips": "[class*='chatbot_Chip'], .ssrc__label, [class*='singleselect'] label, [class*='multiselect'] label",
    "chat_input": "div[contenteditable='true'], [class*='chatbot'] input[type='text'], [class*='chatbot'] textarea",
    "chat_send": "[class*='sendMsg'], button:has-text('Save'), button:has-text('Send')",
    "chat_close": "[class*='chatbot_Close'], [class*='chatbot'] [class*='close']",
    "resume_upload": "input#attachCV, input[type='file']",
}

class NaukriAdapter(Adapter):
    name = "naukri"
    _detail: Optional[dict] = None  # the current job's /jobapi/v4/job/<id> object, set by read_job()
    logged_out_markers = ("input[type='password']", "a:text-is('Login')", "button:text-is('Login')", "#login_Layer")

    def is_logged_in(self) -> bool:
        try:
            self.goto(HOME)  # raises NotLoggedIn if the login form / Login button is already showing
        except NotLoggedIn:
            return False
        return self.wait_logged_in()  # Naukri is a single-page app: wait out the spinner, fail closed

    def queries(self) -> Iterator[str]:
        yield RECOMMENDED
        years = int(round(self.profile.total_experience_years))
        for role in self.criteria.target_roles:
            for location in self.criteria.locations or [""]:
                where = f"-in-{slug(location)}" if location else ""
                yield f"https://www.naukri.com/{slug(role)}-jobs{where}?experience={years}"

    def suggested_queries(self) -> Iterator[str]:
        yield RECOMMENDED

    def discover(self, query: str) -> Iterator[JobCard]:
        seen = set()
        for page_no in range(1, MAX_PAGES + 1):
            payloads = self._capture_payloads(paged_url(query, page_no), lambda p: bool(job_items(p)))
            if any(logged_in_flag(p) is False for p in payloads):  # the server's own verdict
                raise NotLoggedIn(f"{self.name}: the server says this session is logged out")
            cards = [c for p in payloads for item in job_items(p) if (c := card_from_item(item, self.name))]
            fresh = [c for c in cards if c.url not in seen]
            if not fresh:
                if page_no == 1:
                    self.check_login()  # a login wall is not "zero jobs"
                return  # genuinely no (more) jobs; the engine records it and saves the page
            for card in fresh:
                seen.add(card.url)
                yield card

    def _capture_payloads(self, url: str, got_it: Callable[[object], bool]) -> List[object]:
        """Open `url` and return the JSON bodies of the page's own calls.

        Stops once some body satisfies `got_it` and the page has gone quiet (or after ~12s).
        """
        page, responses = self.active, []

        def on_response(response) -> None:  # only collect: never block inside an event handler
            if response.status == 200 and "json" in (response.headers.get("content-type") or ""):
                responses.append(response)

        page.on("response", on_response)
        payloads: List[object] = []
        try:
            self.goto(url)
            parsed, quiet = 0, 0
            for _ in range(CAPTURE_POLLS):
                page.wait_for_timeout(500)
                new = responses[parsed:]
                parsed = len(responses)
                for response in new:
                    try:
                        payloads.append(response.json())
                    except Exception:
                        continue
                quiet = 0 if new else quiet + 1
                if any(got_it(p) for p in payloads) and quiet >= QUIET_POLLS:
                    break
        finally:
            page.remove_listener("response", on_response)
        return payloads

    def read_job(self, card: JobCard) -> Job:
        """Description, salary and apply type come from the page's own /jobapi/v4/job/<id> JSON."""
        payloads = self._capture_payloads(card.url, lambda p: job_detail([p], card.url) is not None)
        if any(logged_in_flag(p) is False for p in payloads):
            raise NotLoggedIn(f"{self.name}: the server says this session is logged out")
        self._detail = job_detail(payloads, card.url)
        if self._detail:
            description, salary = plain_text(self._detail.get("description", "")), salary_text(self._detail)
        else:  # the API shape changed: fall back to whatever text the page shows
            description = self.body_text()
            salary = find_salary(description)
        # Verified live: an applied job's Quick apply button is disabled (also catches jobs applied to elsewhere).
        return Job.from_card(card, description=description[:8000], salary=salary, already_applied=self._button_disabled())

    def apply(self, job: Job, resolver, dry_run: bool) -> Result:
        button = first_visible(self.active, [SEL["apply"]])
        if button is None:
            kind = (self._detail or {}).get("jobApplyType", "unknown")
            if kind not in ("quickApply", "unknown"):  # explicit: applies somewhere else
                return Result(Status.SKIPPED_EXTERNAL, f"apply type '{kind}', not Naukri Quick apply")
            raise RuntimeError("Quick apply button not found (selector changed?)")
        if dry_run:  # Naukri's apply is the submit: questions only appear live
            return Result(Status.DRY_RUN_OK, "Quick apply available")
        calls = []

        def on_response(response) -> None:
            if response.request.method == "POST" and "apply" in response.url.lower():
                calls.append(response)

        self.active.on("response", on_response)
        try:
            button.click()
            return self._await_outcome(resolver, calls)
        finally:
            self.active.remove_listener("response", on_response)

    def sync_resume(self, path: Path) -> None:
        """Upload `path` to the Naukri profile (Naukri applies with the stored resume)."""
        self.goto(PROFILE)
        self.active.locator(SEL["resume_upload"]).first.set_input_files(str(path))
        self.settle(3, 5)

    # -- internals ---------------------------------------------------------------
    def _text(self, selector: str) -> str:
        locator = first_visible(self.active, [selector])
        return locator.inner_text() if locator is not None else ""

    def _button_disabled(self) -> bool:
        button = first_visible(self.active, [SEL["apply"]])
        return button is not None and button.is_disabled()

    def _verified_applied(self) -> bool:
        """The only real proof: reload, and Naukri itself shows the job as applied (button disabled).

        An HTTP 200 and a disabled button right after the click are NOT proof: both are also true while
        the page spins waiting for screening questions (seen live on Svitla Systems).
        """
        for _ in range(VERIFY_RELOADS):
            self.active.reload(wait_until="domcontentloaded")
            for _ in range(8):  # ~4s for the single-page app to render the button
                if self._button_disabled():
                    return True
                self.active.wait_for_timeout(500)
        return False

    def _await_outcome(self, resolver, calls) -> Result:
        """After the click: screening questions, a failed call, or an accepted call that must then be verified."""
        for _ in range(40):  # ~20 seconds
            self.check_challenge()
            ok = [c for c in calls if c.status == 200]
            failed = [c for c in calls if c.status >= 400]
            if first_visible(self.active, [SEL["chatbot"]]) is not None:
                return self._run_chatbot(resolver)
            if first_visible(self.active, [SEL["dialog"]]) is not None:
                self.capture_failure(JobCard(self.name, self.active.url, "unexpected dialog after Quick apply"))
                raise RuntimeError("an unrecognised dialog appeared after Quick apply (page saved to data/failures)")
            if failed and not ok:
                self._log_calls(calls)
                raise RuntimeError(f"the apply call failed: HTTP {failed[0].status}")
            if ok:
                self._log_calls(calls)
                questions = [q for call in ok for q in apply_questions(self._body(call))]
                if questions:  # unsubmitted: a person has to answer these on Naukri
                    reason = "screening questions the bot cannot answer here: " + " | ".join(questions)
                    return Result(Status.SKIPPED_EXTERNAL, reason[:300])
                if self._verified_applied():
                    self.capture_failure(JobCard(self.name, self.active.url, "audit: after Quick apply"))
                    return Result(Status.APPLIED, "apply accepted and Naukri shows the job as applied")
                self.capture_failure(JobCard(self.name, self.active.url, "apply 200 but not shown as applied"))
                raise RuntimeError("the apply call returned 200 but Naukri does not show the job as applied")
            self.active.wait_for_timeout(500)
        raise RuntimeError("no response to Quick apply within 20s")

    @staticmethod
    def _body(call):
        try:
            return call.json()
        except Exception:
            return None

    @staticmethod
    def _log_calls(calls) -> None:
        for call in calls:
            log.info("naukri apply call: %s %s -> %s", call.request.method, call.url.split("?")[0][-80:], call.status)

    def _chat_options(self) -> List[str]:
        return [t.strip() for t in self.active.locator(SEL["chips"]).all_inner_texts() if t.strip()]

    def _last_bot_message(self) -> str:
        messages = self.active.locator(SEL["bot_message"])
        return messages.last.inner_text().strip() if messages.count() else ""

    def _run_chatbot(self, resolver) -> Result:
        last, repeats = "", 0
        for _ in range(MAX_CHAT_STEPS):
            self.check_challenge()
            if self._applied():
                return Result(Status.APPLIED, "Naukri shows the job as applied")
            question = self._last_bot_message()
            if not question:
                self.active.wait_for_timeout(1000)
                continue
            repeats = repeats + 1 if question == last else 0
            if repeats >= 2:
                raise RuntimeError(f"chatbot keeps re-asking: {question[:80]}")
            last = question
            options = self._chat_options()
            answer = resolver.resolve(question, options or None)
            if answer is None:
                self._close_chatbot()
                resolver.require_complete()  # raises NeedsAnswer -> job parked
            self._send_chat_answer(answer, bool(options))
            self.active.wait_for_timeout(1200)
        raise RuntimeError("chatbot did not finish")

    def _send_chat_answer(self, answer: str, is_choice: bool) -> None:
        page = self.active
        if is_choice:
            chip = page.locator(SEL["chips"]).filter(has_text=re.compile(rf"^\s*{re.escape(answer)}\s*$", re.I)).first
            chip.click()
        else:
            box = first_visible(page, [SEL["chat_input"]])
            if box is None:
                raise RuntimeError("chatbot text box not found")
            box.click()
            page.keyboard.type(answer, delay=40)
        send: Optional[object] = first_visible(page, [SEL["chat_send"]])
        if send is not None:
            send.click()
        elif not is_choice:
            page.keyboard.press("Enter")

    def _close_chatbot(self) -> None:
        close = first_visible(self.active, [SEL["chat_close"]])
        if close is not None:
            close.click()
        else:
            self.active.keyboard.press("Escape")
