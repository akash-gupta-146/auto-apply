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
from pathlib import Path
from typing import Callable, Iterator, List, Optional

from ..models import Job, JobCard, NotLoggedIn, NothingSent, Result, Status
from .base import Adapter, first_visible, find_salary, slug
from .forms import let_person_answer
from .naukri_chat import Drawer
from .naukri_api import (
    apply_questions, card_from_item, job_detail, job_items, logged_in_flag, paged_url, plain_text, salary_text, thin_description_note,
)

HOME = "https://www.naukri.com/mnjuser/homepage"
RECOMMENDED = "https://www.naukri.com/mnjuser/recommendedjobs"
PROFILE = "https://www.naukri.com/mnjuser/profile"
MAX_PAGES = 3
MAX_CHAT_STEPS = 15
DRAWER_POLLS = 30  # x 0.5s: how long the question side bar gets to draw itself once Naukri has said it has questions
CHAT_REPLY_POLLS = 16  # x 0.5s: how long the bar gets to ask its next question after one is answered
CHAT_SCRIPT = "chatbot"  # the question side bar is drawn by a script with this in its address (fix-plan N1: a gateway may refuse it)
CAPTURE_POLLS = 24  # x 0.5s: how long to wait for the page's job calls
VERIFY_RELOADS = 2  # how many times to reload and look for Naukri's own "applied" state
SPINNING_JS = """() => [...document.querySelectorAll('button')].some(b => {
  const r = b.getBoundingClientRect(), s = getComputedStyle(b);
  return r.width >= 100 && r.height >= 30 && s.visibility !== 'hidden' && s.display !== 'none'
    && !(b.innerText || '').trim() && !b.getAttribute('aria-label') && !b.getAttribute('title'); })"""
log = logging.getLogger("jobapply")
QUIET_POLLS = 4  # x 0.5s with no new response, once jobs were seen, means the page is done

SEL = {
    # Verified live (new "TopTier" UI): a floating pill button reading "Quick apply". Its text is the SAME
    # before and after applying (a hidden "Applied" label lives inside it); the only difference is the
    # `disabled` attribute: applied job -> disabled, untouched job -> enabled.
    "apply": "button:has-text('Quick apply')",
    "dialog": "[role='dialog']",
    # The question side bar's selectors are in naukri_chat.py. This one is from the OLD UI and UNVERIFIED against the new one.
    "resume_upload": "input#attachCV, input[type='file']",
}

class NaukriAdapter(Adapter):
    _chat_refused: Optional[int] = None  # the HTTP status the side bar's script was refused with during this apply, if it was
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
        thin = thin_description_note(self._detail, description, card.url)
        if thin:
            log.warning(thin)
        # Verified live: an applied job's Quick apply button is disabled (also catches jobs applied to elsewhere).
        return Job.from_card(card, description=description[:8000], salary=salary, already_applied=self._button_disabled())

    def apply(self, job: Job, resolver, dry_run: bool) -> Result:
        button = first_visible(self.active, [SEL["apply"]])
        if button is None:
            kind = (self._detail or {}).get("jobApplyType", "unknown")
            if kind not in ("quickApply", "unknown"):  # explicit: applies somewhere else
                return Result(Status.SKIPPED_EXTERNAL, f"apply type '{kind}', not Naukri Quick apply", elsewhere=True)
            raise RuntimeError("Quick apply button not found (selector changed?)")
        if dry_run:  # Naukri's apply is the submit: questions only appear live
            return Result(Status.DRY_RUN_OK, "Quick apply available")
        calls: list = []
        on_response = self._watch_apply(calls)
        self.active.on("response", on_response)
        try:
            button.click()
            return self._await_outcome(resolver, calls)
        finally:
            self.active.remove_listener("response", on_response)

    def _watch_apply(self, calls: list):
        """The listener for what the page's network answers after Quick apply: the apply calls go into `calls`, and a refusal of the side bar's
        own script is remembered in `_chat_refused`. Used by a real apply and by the side bar probe alike."""
        self._chat_refused = None

        def on_response(response) -> None:
            if response.request.method == "POST" and "apply" in response.url.lower():
                calls.append(response)
            elif CHAT_SCRIPT in response.url.lower() and response.url.split("?")[0].endswith(".js") and response.status >= 400:
                self._chat_refused = response.status  # the side bar's own script was refused: it cannot draw, whatever we wait for

        return on_response

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
            if Drawer(self.active).is_open():
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
                if questions:  # unsubmitted: they are answered in Naukri's side bar, which may take a moment to draw
                    return self._await_drawer(resolver, questions)
                if self._verified_applied():
                    self.capture_failure(JobCard(self.name, self.active.url, "audit: after Quick apply"))
                    return Result(Status.APPLIED, "apply accepted and Naukri shows the job as applied")
                self.capture_failure(JobCard(self.name, self.active.url, "apply 200 but not shown as applied"))
                raise RuntimeError(self._why_unconfirmed())
            self.active.wait_for_timeout(500)
        raise RuntimeError("no response to Quick apply within 20s")

    def _why_unconfirmed(self) -> str:
        """Naukri accepted the apply call (HTTP 200) but, after a reload, does not show the job as applied. Say which it is, as far as the page
        and the network can tell, so the person knows whether to change something, check by hand, or just look at the site."""
        base = "the apply call returned 200 but Naukri does not show the job as applied"
        if self._chat_refused is not None:
            return (f"{base}: it then needed its question window, and your network refused that script (HTTP {self._chat_refused} from "
                    "static.naukri.com), so the application was most likely waiting for answers there and was NOT sent. Ask IT to allow "
                    "static.naukri.com, or run Naukri from another network")
        if self._apply_button_spinning():
            return f"{base}: its Apply button was still showing a spinner after a reload, so whether it went through is unknown. Check Naukri's Applied jobs before trying this job again"
        return base

    def _apply_button_spinning(self) -> bool:
        """The Apply button is there but shows no words: Naukri draws dots in place of \"Quick apply\" while it waits for something. Wide on purpose:
        the page's small icon buttons have no words either."""
        try:
            return first_visible(self.active, [SEL["apply"]]) is None and bool(self.active.evaluate(SPINNING_JS))
        except Exception:
            return False

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

    # -- Naukri's question side bar ---------------------------------------------------
    def _await_drawer(self, resolver, questions: List[str]) -> Result:
        """Naukri said it has screening questions. Its side bar draws a moment later (and not at all where its script is blocked)."""
        drawer = Drawer(self.active)
        for _ in range(DRAWER_POLLS):
            if drawer.is_open():
                return self._run_chatbot(resolver)
            self.active.wait_for_timeout(500)
        self.capture_failure(JobCard(self.name, self.active.url, "questions came back but the question window never opened"))
        if self._chat_refused is not None:
            log.warning("Naukri's question window is blocked by your network: its chat script was refused (HTTP %s). Ask IT to allow "
                        "static.naukri.com, or run Naukri from another network. The questions are listed on the Questions page.", self._chat_refused)
        resolver.note_unanswered(questions)  # still listed on the Questions page, so they can be answered once and for all
        resolver.waited = True  # there is no form to type into: a wait for the panel would only end in the same closed window
        resolver.require_complete()  # raises NeedsAnswer for what has no saved answer
        raise NothingSent(f"Naukri asked screening questions but its question window never opened{self._why_not_drawn()}; nothing was sent")

    def _why_not_drawn(self) -> str:
        """The reason, when it is known: a refused script is certain, anything else is only the usual suspect."""
        if self._chat_refused is None:
            return " (a network that blocks static.naukri.com does this)"
        return (f", because your network refused Naukri's chat script (HTTP {self._chat_refused} from static.naukri.com). "
                "Ask IT to allow static.naukri.com, or run Naukri from another network")

    def _run_chatbot(self, resolver) -> Result:
        """Work through the side bar. If something in it is not as expected (no question to read, no text box, a question asked again, the bar
        gone but the job not applied) the page is saved first: the bar's markup has never been seen live (see naukri_chat.py), so the first
        time it opens is the evidence its selectors can be repaired from. Not having an answer is no failure and saves nothing."""
        try:
            return self._chat_steps(resolver)
        except RuntimeError as exc:
            self.capture_failure(JobCard(self.name, self.active.url, f"question window: {exc}"))
            raise

    def _chat_steps(self, resolver) -> Result:
        drawer, last, repeats = Drawer(self.active), "", 0
        for _ in range(MAX_CHAT_STEPS):
            self.check_challenge()
            if not drawer.is_open():  # it closes by itself after the last answer
                return self._chat_finished()
            question = drawer.question()
            if not question:
                self.active.wait_for_timeout(1000)
                continue
            repeats = repeats + 1 if question == last else 0
            if repeats >= 2:
                raise RuntimeError(f"chatbot keeps re-asking: {question[:80]}")
            last = question
            self._answer_in_drawer(drawer, question, resolver)
            self._wait_for_next_question(drawer, question)
        raise RuntimeError("chatbot did not finish")

    def _answer_in_drawer(self, drawer: Drawer, question: str, resolver) -> None:
        """Answer from the saved answers, the rules or the AI; failing that, leave the bar open for you (typed, ticked or answered in
        the panel), exactly as LinkedIn's form does. Whatever you answer by hand is saved."""
        options, said = drawer.options(), drawer.said()

        def answer_it() -> bool:
            """True when the question has an answer, or no longer needs one."""
            if not drawer.is_open():  # you answered the last question and the bar closed: there is nothing left to ask
                return True
            answer = resolver.resolve(question, options or None, read=lambda: drawer.given(options, said))
            if answer is not None and not drawer.moved_on(question, said):  # you may have answered it in the bar already
                drawer.send(answer, bool(options))
            return answer is not None

        resolver.start_pass()
        if not answer_it():
            let_person_answer(self.active, resolver, answer_it)
            if resolver.waiting_on():
                drawer.close()
                resolver.require_complete()  # raises NeedsAnswer -> job parked, nothing was sent

    def _wait_for_next_question(self, drawer: Drawer, question: str) -> None:
        for _ in range(CHAT_REPLY_POLLS):
            if not drawer.is_open() or drawer.question() != question:
                return
            self.active.wait_for_timeout(500)

    def _chat_finished(self) -> Result:
        if self._verified_applied():
            return Result(Status.APPLIED, "answered Naukri's questions and it shows the job as applied")
        raise RuntimeError("Naukri's question window closed but it does not show the job as applied")  # saved by _run_chatbot
