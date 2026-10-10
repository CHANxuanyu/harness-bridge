# PR #5 handoff to Cloud — independent macOS verification

Exact input: `70a5d73f388ec99ff6370dcf8eacdbb0b47b024f`; its tested-code parent is
`3186dbca86b64866b0ede02d10be201442ae1863`. Original integration base remains
`92ed653eaa965ae5355ed3270555e22058888afc`. PR #3/#4/#5 remain draft, no merges/closes.

Please correct PR #5's opening phrase **“local native acceptance”** to **“local offline/synthetic
acceptance”** for old candidate `78253365266eb5f47f0436dddf4b69522def917e`. Native input,
accessibility and official-desktop acceptance never passed on that candidate. The candidate's
ENGINEERING_FOUNDATION_RESULT.md now corrects the same wording. Keep Cloud's actual 1041 pass /
7 fail / 0 skipped / exit 1 and three-marker removal condition intact.

Independent macOS review found **EF3-R1**: WorkbenchServer binds its listener before start, but
app.run registered cleanup only after start succeeded. Thread-start failure or start throwing
after the HTTP thread began leaked the listener through both repobridge and hbridge app. New
regression before fix: 4 fail / 2 pass. Fix and 18 backend regressions are isolated in:

**`560056f11858f9f02b01ee3966ba2aaf41d41c54` — Release bound HTTP resources when App startup fails.**

Product diff is six added/two removed lines in app.py/server.py: register cleanup before start;
shutdown/join only a started thread, always close the bound socket. No frontend/static/native_mac
changes. The test asserts stopped threads, released root/App locks, same-port rebind and successful
restart. Do not import the receipt-only commit as a product implementation requirement.

1066 passed / 0 failed / 0 errors / 0 skipped; pytest 1104.20s; exit 0. Ruff check, format (208 files) and strict mypy (65 source files, Darwin target) each exit 0. Actual tested code is 560056f; final candidate receipt HEAD is supplied in the
PR handoff/verification.json because committing a document cannot contain its own final SHA.
The separate review branch is `codex/engineering-foundation-reverification`; **do not advance PR
#5's integration base to this branch during review**. Review/apply the repair on the PR branch only
when coordinating the next action; this verification did not merge or mutate Cloud's branch.

The cloud-seven cases all pass on actual macOS 26.6.2 arm64/APFS, Python 3.11.16; this does not
explain or close the Linux ZCode cancellation failure. Gate markers were unset in the invoking
Mac environment, none removed; all four marker values injected in explicit two-harness refusal
tests. Mypy targets Darwin; Linux-only type paths and remote CI remain outside this result.

Fresh UI/backend regression passes, including older/background cleanup, receipt monotonicity,
unknown protection, draft/attachment retention and both P2 scopes. Real/native checks remain
NOT_RUN. Full detail: [macOS candidate receipt](ENGINEERING_FOUNDATION_MACOS.md).

## Review package and next owner

The candidate and fix are local only. `verification.json` supplies the complete final candidate SHA,
eight-file post-test diff and SHA-256 manifest. `delivery/repobridge-pr5-candidate.bundle` carries
the two candidate commits with PR input 70a5d73 as prerequisite; `delivery/*.patch` provides the
repair and documentation separately. No branch was pushed and this text was not posted to GitHub.

For the six Linux desktop failures, the observed refusal comes from the Darwin capability gate;
keep this attribution and the original 1041/7/exit-1 result. For ZCode, capture test-owned peer and
transport PID/PPID/PGID/state/start identity immediately after cancel, including container reaper
behavior. `group_alive` excludes zombies while `os.kill(pid, 0)` can still see them; that explains
why a zombie hypothesis is possible, not why this particular Cloud failure occurred. Live leakage
and PID reuse must also be ruled out. Keep the assertion and mark this Linux item OPEN until
evidence resolves it. Do not remove gate markers to obtain green results.

PM: review the precise candidate for macOS offline/synthetic acceptance without advancing the
integration base. Local Opus: native interaction and static UI ownership stay with you; IME,
system clipboard, VoiceOver and native focus remain NOT_RUN. Real outside-created sessions and
official-desktop continuation require their separate scoped acceptance; no allowance is renewed.
