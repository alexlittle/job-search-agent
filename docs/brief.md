Build a multi-agent system to help me with my job search, following the basic outline in this course: https://github.com/LinkedInLearning/claude-agents-build-a-multi-agent-research-system-in-7-days-28658013

This idea is that this system will search the web for relevant job postings for me to apply for. The system will not actually appy for any jobs, it will only highlight jobs that are a good fit for me

The system should be customisable and reusable - so others can also use it for their job hunting.

I should be able to enter/load my CV and give some initial ideas for the types of jobs I'm looking for, personal requirements for roles I'm looking for etc.

When it makes recommendations, users should have the option to say if the job is relevant or not,a nd the system should learn from this, so over time the recommendations get more tailored and accurate 

The system should work very efficiently with token usage, allowing the user to carefully control how much is being spent, and should also different models for different tasks (eg Haiku for basic searching, then Sonnet for analysing the fit)

Initial converstaion from Claude: 

I'm thinking a bout building a AI agent to help me in my job search, would this be a useful thing to do, and (more importantly) would it be able to access the types of jobs I'm looking for (ie would it be able to get "into" jobs boards etc?

Short answer: yes, worth building — but the version that's actually useful isn't "an agent that logs into LinkedIn and applies for you." It's more of an aggregator/triage layer that feeds your tracker. The board-by-board picture looks quite different depending on which one:

- **LinkedIn** — this is the one where a scraping/login bot genuinely won't work well. Their user agreement explicitly prohibits scraping and unauthorized automated access to the platform, and enforcement has gotten more aggressive through 2026, with account restrictions being the real consequence rather than anything legal.LinkedIn's official User Agreement prohibits scraping software, automated bots, and any access method outside LinkedIn's official interfaces What *is* fair game natively is saved-search job alerts by email — an agent that parses those alert emails rather than touching linkedin.com directly sidesteps the whole problem, since you're using LinkedIn's own delivery mechanism rather than automating against the site.

- **jobs.ac.uk** — good news, since this is one you already use: it publishes genuine RSS feeds for jobs, organised by location and subject area, no login needed. An agent can just poll the relevant feeds and diff against what's new.

- **EURAXESS** — I'd want to check its specific feed/API situation before promising it behaves the same way, but as an EU research portal it's plausible it offers something similar.

- **Adzuna** — has a proper free public API (few hundred calls/day on the free tier) for search, salary and company data, so it's easy to pull into your own tool. It's more of a mainstream/commercial aggregator though, so it may not surface the niche med-ed/academic roles as well as jobs.ac.uk does.

- **Employer/ATS career pages** — a lot of companies run their listings on Greenhouse, Lever, etc., which are far more scrape-friendly than LinkedIn. Since your target list is fairly specific (med-ed product companies, universities, NHS, health-tech), a small watchlist of those exact employer pages could be more useful than trying to cover every board.

On the "is it useful" question generally — I'd split "find and organise listings" from "apply." The first is a genuinely good agent task: pull from feeds/APIs into your tracker, flag matches against your search strings, maybe draft a first-pass fit summary. The second (auto-applying) tends to work against what you're already doing well — the interview-first CV approach only pays off because each application is actually tailored, and a bot cranking out generic applications undercuts that.

Given you're already running Django on your own infra, this is a genuinely small project: an RSS/API poller feeding a database or straight into your spreadsheet, maybe with an LLM step to score postings against your criteria. Want me to sketch an actual architecture, or start narrower — e.g. just jobs.ac.uk feeds + the Adzuna API landing in your tracker?

Thanks, I was thinking more about an agent that woul dhelp me to find the jobs that are actually of interest to me, and that I'm qualified for - I certainly do not want it to actually apply to jobs on my behalf. The reason I ask is because I was looking at this course: https://www.linkedin.com/learning/claude-agents-build-a-multi-agent-research-system-in-7-days and thought it could be interesting thing to build anyway  even if it doesnt work, I've learned about using agents

That's a much easier problem than "apply for me" — mostly reading and scoring, not interacting with the boards, so most of the LinkedIn ban-risk from before barely applies here. The hard part shifts from access to judgment: is this job actually for me.

On the course — the LinkedIn Learning page itself is locked behind login, but it has a public GitHub repo, and it's a genuinely good structural fit for what you want to build. It's Kesha Williams' 7-day series, with each day building on the last, ending with a complete system of five agents plus validation, retry logic, and a refinement loop by day 7, extended with a sixth agent you design as the final challenge. That maps almost directly onto a job-matching pipeline:

- one or more **source agents** — polling jobs.ac.uk's RSS feeds, the Adzuna API, maybe specific employer career pages, pulling in raw listings
- a **normalize/dedupe step** — the same posting showing up on three boards shouldn't count three times
- a **fit agent** — the actual judgment call: reads each listing against a structured profile of what you're qualified for and interested in, and explains/scores fit rather than just keyword-matching
- a **validation/refine loop** — this is exactly the Day 7 pattern: if the fit agent is uncertain, go pull the full job description and re-check against specific criteria instead of guessing from a snippet
- an **output step** — write matches into your tracker, and stop there

Building it as your own project rather than just following along with the tutorial is probably the better way to learn the pattern, too — a toy example won't throw you the messy real problems (inconsistent feed formats, ambiguous fit calls, what counts as "confident enough") that you'll only hit on something you actually care about getting right.

Want to work through the course first and treat this as a "day 8" extension, or start sketching the fit-agent's criteria now — that's the piece that's specific to you and isn't in the course at all?


If I have this running, how can I control the API usage?


A few layers, roughly from "hard stop no matter what" down to "make each run cheaper":

**Set a hard cap first.** In the Claude Console, under Settings → Billing, you can set your own monthly spend limit below your account's tier cap. Once you hit it, requests fail cleanly with an error rather than quietly running up cost — worth doing before you let this run unattended on a schedule.

**Cut the number of calls, not just their cost** — this matters more than any single setting for a job like yours:
- Deduplicate against what you've already seen. Keep a small local table of listing IDs (or a hash of title+company+url) so a daily/weekly run only scores genuinely new postings, not the whole feed again.
- Pre-filter cheaply before anything touches Claude. Rule-based checks — location, salary band, keywords in the title — can throw out obvious non-matches for free, so the LLM only sees the cases where a real judgment call is worth paying for.

**Tier the model.** Use a cheap/fast model (Haiku) for the bulk first pass, and reserve a stronger one only for borderline cases or the final write-up. This is usually the single biggest lever in a pipeline like this — bigger than anything else on this list.

**Use the Batch API, since nothing here needs an instant answer.** Your pipeline runs on a schedule with nobody waiting on a live response — that's exactly what Anthropic's Message Batches API is for: submit a run's new listings as one batch, it processes asynchronously, at 50% off standard per-token pricing.

**Cache the repeated part of the prompt.** Your "here's what I'm qualified for and interested in" profile is presumably identical on every call within a run — mark it for prompt caching so it's billed once and reused cheaply instead of re-charged per listing.

**Cap the agent loop itself.** This is literally the pattern the course builds toward by day 7 — a turn/retry cap per agent, so a bug or an unusually messy job posting can't spin the fit-agent into an expensive loop.

The spend cap plus the dedupe/pre-filter step do most of the work — together they mean nothing runs away on you even if something misbehaves while you're not watching it.

Want me to sketch what the dedupe-and-prefilter step would actually look like, given it's the piece that does double duty (saves money *and* is genuinely part of the pipeline logic)?


## Follow-up decisions (2026-09-25)

A few design questions came up once Phase 2 was built (the first RSS source agent), worth
recording alongside the original brief above:

**Non-programmer source configuration.** Plain RSS-based sources (like the THE unijobs feed
built in Phase 2) will be config-driven — listed by name and feed URL in a config file, no code
required to add one. Sources that need bespoke API handling (e.g. Adzuna) still need code, via a
small documented plugin interface (`fetch_listings() -> list[Listing]`).

**Batch API.** Used specifically for the fit-agent scoring stages (Haiku coarse pass, Sonnet
detailed pass) — the high-volume, no-rush part of the pipeline this brief's cost-control
discussion already had in mind. Built first as ordinary synchronous calls (easier to learn from),
then switched over to the Anthropic Message Batches API as a dedicated cost-optimization step
once the synchronous version works.

**Results & status visibility.** Results are viewed through a small local web dashboard (Flask)
reading from the SQLite store, rather than a plain Markdown report file. The dashboard also
doubles as the feedback-capture UI — relevant/not-relevant buttons per listing — rather than a
CLI prompt.
