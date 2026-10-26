# Lelouvre: internship agent system design

Status: October 19, 2026. The local tracker and first read-only scouting loop are implemented. The scout checks two employer feeds and two scholarship pages, records source health, evaluates with explicit evidence/rules, and supports six-hour scheduling while the server runs. Three sources were readable in the initial live check; one scholarship source requires follow-up. See README.md for exact coverage. No language model, account connections, email delivery, or automatic submissions are active. The remainder describes the broader target system.

## Product goal

Lelouvre also supports scholarships as a parallel opportunity track. See SCHOLARSHIPS.md for scholarship eligibility, award-cycle handling, manual imports, submission rules, and award/renewal tracking. Internship season and location restrictions do not automatically apply to scholarships.

Find and evaluate Summer 2027 internships for a student, alert on verified openings, prepare truthful applications, submit routine applications within an approved answer policy, and maintain an auditable application history.

## Candidate profile and search policy

Candidate facts and screening answers belong in the private local database.
Public demonstration data is fictional; authorization requires explicit review.


## Workflow

1. Discover listings from verified employer career pages and supported ATS feeds. Supplement discovery with public internship repositories.
2. Resolve every candidate listing to an official employer source; retain source URL, requisition ID, source-provided dates, first seen time, last checked time, and description snapshot.
3. Normalize and deduplicate across sources, tracking edits and reopenings. Use employer/requisition ID first and a canonical URL fallback; review uncertain duplicates.
4. Apply deterministic season, location, degree, and explicit eligibility rules before ranking.
5. Extract required versus preferred skills with supporting description excerpts. Resume evidence informs truthful application preparation but never gates discovery.
6. Rank discovery by role category, season, location, deadline urgency, and user company priority. Skill overlap does not determine whether a role is found or prioritized.
7. Deliver an email digest plus urgent email alerts, per user preference. Put routine matches in the digest; urgent alerts cover high-priority verified openings, approaching deadlines, and time-sensitive responses or required decisions. Cadence, priority thresholds, recipient, and delivery connection remain to be configured. Suppress repeat alerts. Never present discovery time as publication time.
8. Prepare an application packet with resume version and exact field answers. Recheck availability and application questions immediately before execution.
9. Route any unapproved fields or substantive requirements to review. Run permitted routine submissions through supported site adapters.
10. Record confirmed submission evidence. A timeout after clicking submit becomes submission_unknown and requires reconciliation before any retry.
11. Track responses and follow-up tasks through user updates first, then an explicitly connected mailbox integration. No recruiter messages sent automatically.

## Submission policy

User permits routine resume uploads and factual form filling/submission. This is conditional on a complete, approved answer profile and a supported site.

Automatic: approved contact/education/profile links, approved factual answers, and an approved resume. Check exact field meaning; similar wording does not guarantee equivalent meaning.

Review required: essays, cover letters, research statements, unfamiliar screening questions, compensation commitments, relocation commitments not already approved, assessments, authorization/sponsorship ambiguity, changed attestations, new consent choices, demographic questions without saved preferences, and new resume variants.

Pause for login, CAPTCHA, MFA, unsupported forms, uncertain eligibility, or conflicting information. Do not bypass access controls or fabricate answers. Critical means substantive decisions, not merely employer prestige; user may additionally mark any company as always-review.

Approval is tied to a specific packet revision, question set, and listing snapshot; material changes invalidate it. Each submission records the policy or approval that authorized it. Support pause-all and per-company disable controls.

## Helpful additions

- Broad scouting: employer careers, LinkedIn, general web search, Reddit, X, public internship repositories, and research-program pages. These are intended discovery channels, not claims that access is already connected. Maintain per-source access, freshness, and failure visibility. Never promise exhaustive internet coverage.
- Social/community posts are leads. Resolve employer identity and the actual application destination before sharing personal data or submitting. Retain original discovery attribution alongside verified application evidence.
- Supported Easy Apply and other routine forms may submit automatically using approved facts and documents when eligibility, platform access, destination verification, and duplicate checks pass. Required unknown answers or substantive questions still block submission; an Easy Apply label does not override policy.
- Confirmed automatic submissions appear immediately in My applications with submitted materials, date, origin, and receipt. Uncertain outcomes appear separately and do not count as confirmed submissions.

- Company watchlist: verified career URLs, track preferences, always-review flags, last successful check, and upcoming programs. Candidate employers are targets, not claims of currently open jobs.
- Application board: separate posting availability, application progress, execution status, and review tasks. See ARCHITECTURE.md for the lifecycle and logical schema.
- Separate posting availability from application progress so a closed posting does not erase an active interview process.
- Evidence-backed skill map: frequently requested skills by track, evidence already present, genuine gaps, and suggested portfolio improvements.
- Three truthful resume variants: SWE, security/cloud, and research; user review before use. Preserve originals and version every uploaded file.
- Deadline queue, interview preparation from the actual posting, response reminders, and a manual corrections interface.
- Relocation, housing, pay, duration, and employer caps; unknown values visible rather than guessed.
- Source health dashboard: successful checks, failed checks, rate limits, stale sources, and coverage. No promise to observe openings instantly or across every employer.
- Analytics: confirmed applications, response rates, stage conversion, and fit by track. Never count a click or draft as an application.
- Export to CSV/JSON, backup/restore, account disconnect, and deletion controls.

## Proposed open-source-first architecture

Start with a modular Python service, SQLite, and a small local dashboard; use PostgreSQL only when concurrent or hosted deployment requires it. Avoid a multi-agent framework in the first version.

Modules: source adapters, normalization, policy engine, evidence/ranking, application planner, browser executor, notification outbox, scheduler, and dashboard/API.

- Public Greenhouse and Lever listing APIs where available; dedicated employer adapters elsewhere. Public listing access does not imply permission or credentials to submit through an API.
- Browser execution via Playwright on supported flows after site compatibility review; employer-controlled APIs must not be assumed available to applicants.
- Optional local model via Ollama for structured extraction and drafting; model and license selected after checking hardware. Rules control eligibility and submission authorization. Model output must validate against a schema and cite supplied evidence.
- Application and notification outboxes with retry budgets, deduplication keys, backoff, and persistent state. Submission side effects are not blindly retried.
- Local scheduler initially; an always-on deployment is necessary for monitoring while the computer is off. Proposed cadence: every six hours, adjustable by source limits. Alerts require an actual configured delivery channel.
- Keep secrets in an OS credential store and sensitive session files out of version control. Bind local service to loopback with authentication where appropriate. Minimize personal data in logs; protect backups and provide retention settings.
- Treat listing text, resumes, and emails as untrusted data. They cannot alter policy, invoke tools, select credentials, or redirect uploads. Allowlist destination domains and validate final upload/submission destinations.

Core records: CandidateProfile, ProfileFact, AnswerPolicy, Company, Source, SourceCheck, Posting, PostingSnapshot, SkillRequirement, MatchExplanation, ResumeVersion, ApplicationPacket, Approval, SubmissionAttempt, ApplicationEvent, Notification, MessageLink.

Detailed component boundaries, logical database schema, manual import workflow, permission matrix, and state transitions are specified in ARCHITECTURE.md. These documents describe the intended system; no services are deployed.

## Implementation sequence and acceptance checks

1. Discovery and tracker: approved candidate profile, employer registry, two public source adapters, persistent deduplication, evidence-based filtering, dashboard, CSV export. Verify repeated ingestion creates no duplicate listings and a failed source is visible.
2. Ranking and notifications: structured extraction, explicit unknowns, skill evidence, deadline queue, notification delivery and deduplication. Verify changed listings create revisions and repeated checks do not repeat alerts.
3. Application preparation: approved answer bank, versioned packets, review queue, mock-form browser tests. Verify unknown fields and changed packets block submission.
4. Limited submissions: enable one verified site adapter at a time. Require a receipt or explicit confirmation; test uncertain outcomes and duplicate prevention before broadening coverage.
5. Response tracking: user-connected mailbox with narrowly scoped access where supported; correlate by requisition/company/thread, retain message references, and route ambiguity to review. Never treat silence as rejection.

## Open decisions

Work authorization is explicitly unconfirmed. Confirm exact approved screening answers with the user; school adviser verification may be needed. Email digest plus urgent alerts is selected; configure recipient, cadence, urgency thresholds, and delivery connection before activation. Confirm remote preference, summer availability, paid-only preference, research interests, and hosting budget. These do not block initial discovery implementation, but unresolved required answers block submissions.

## Sources checked for this design

- Greenhouse Job Board API: https://docs.greenhouse.io/job-board
- Lever public posting API: https://github.com/lever/postings-api
- Summer 2027 discovery repository: https://github.com/SimplifyJobs/Summer2027-Internships
- Playwright: https://playwright.dev/docs/intro
- Ollama: https://docs.ollama.com/

These references support integration choices, not verified open roles at particular employers. Verify each library's selected version and license during implementation.
