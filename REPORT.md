# dev-proxy — work report

Date: 2026-08-14

This report lists the work done to make dev-proxy useful and fully working.
The goal is one thing: give the team what Charles Proxy does, but drive it
with an agent like Claude, not with a mouse.

## Summary

- 6 open issues at the start. All 6 are now closed.
- 4 new defects found during testing. All 4 are now filed, fixed, and closed.
- 7 pull requests merged to `main`.
- The proxy works end to end on a real Android phone and in Chrome.
- Zero open issues remain.

## Issues resolved

### Original issues (closed)

| # | Title | Fix |
|---|-------|-----|
| 1 | Readme updates | README now covers the Claude skill, the USB-cable transport, and the Charles license and network friction. |
| 2 | Follow newest button does nothing | The autoscroll decision now reads the real scroll position, not the row-selection state. |
| 3 | Add a clear button | The dashboard has a Clear button. It wipes the flow log and saved bodies through a new `POST /api/clear` route. |
| 4 | Add a reset button | The dashboard has a Reset-filters button. It clears the host, path, and status filters. |
| 5 | Add setup script to install from claude | A root `CLAUDE.md` bootstraps a fresh clone. `install.sh` and `proxyctl` now point at `brew install --cask android-platform-tools` for adb. |
| 6 | No way to visualize applied rules | The rule bar is a dropdown. It lists every rule with its action kind. Each rule has a checkbox that toggles it through `POST /api/rules/toggle`. |

### New defects found and fixed (closed)

I found these while testing the merged dashboard against the live proxy.

| # | Title | Fix |
|---|-------|-----|
| 15 | `map_remote` to an excluded host hid the flow | The record step now uses the host the app called, not the rewritten target. A new `mapped_to` field shows the rewrite target. |
| 16 | A body with invalid UTF-8 crashed the recorder | Body text is sanitized on read. The writer also catches `UnicodeError`. One bad byte no longer drops the whole flow. |
| 17 | Duplicate flow ids after a clear | The id counter resets once per clear, not once per request that races the first write. |
| 18 | False "cannot reach dev-proxy files" note after a clear | The poll treats a missing flow log as zero flows, not a dead server. The live dot stays green. |

## Pull requests merged

- #7 Fix follow-newest autoscroll bug (issue 2)
- #8 Add a Clear button to the dashboard (issue 3)
- #11 README: fill remaining gaps (issue 1)
- #12 Add a root CLAUDE.md bootstrap doc; fix the missing-adb gap (issue 5)
- #13 Add a Reset-filters button to the dashboard (issue 4)
- #14 Visualize and toggle rules from the dashboard (issue 6)
- #19 Record flows under the host the app called; harden the recorder (issues 15, 16, 17, 18)

Note: PRs #9 and #10 were stacked on #8. GitHub closed them when the base
branch merged and got deleted. I rebased both onto `main` and reopened them
as #13 and #14.

## How each change was tested

### Chrome (dashboard)

I drove Google Chrome with Playwright against the live dashboard.

- #7: Selected a row, then sent a new flow. The new row lands on top and the
  view snaps to the top. Then I scrolled away and sent another flow. The view
  stayed put. The old code fails the snap check. This proves the fix.
- #8: A dismissed dialog changes nothing. An accepted clear sets the UI to 0
  flows and deletes the files on disk. curl checks: same-origin POST 200,
  cross-site POST 403, unknown route 404.
- #13: A filter drops the list from 5 rows to 3. Reset clears all inputs and
  brings back all 5 rows.
- #14: The dropdown lists both rules with their action kind. A toggle writes
  to `rules/rules.json` on disk and updates the bar. curl error paths: unknown
  id 404, malformed JSON 400, wrong shape 400.
- #15 and #18: After a clear, the dashboard stays live. A mapped flow appears
  under the original host with a "Mapped to another target" panel.

### Automated test suite

`./test/run.sh` grew from 21 checks to 28 checks. The 7 new checks cover the
addon fixes for issues 15, 16, and 17. All 28 checks pass. The three behavior
checks fail against the old addon, which proves they test the real change.

### Mobile (real device)

Device: Samsung SM-M176B (Android 16). App: ShareChat (`in.mohalla.sharechat`),
a real debug build. HTTPS decrypts, so the CA is trusted.

**Demo 1 — `json_patch` on live HTTPS traffic (the flagship feature).**

1. I opened the search screen. The app calls
   `apis.sharechat.com/v2.0.0/zero-state`.
2. The first call returned `304 Not Modified`, so the app used its cache.
3. I added a rule with two actions. First, strip the conditional request
   headers so the server returns a full `200`. Second, `json_patch` the
   response: rewrite the section heading and the `payload.popularSearches`
   list.
4. I reopened the search screen. The phone showed my injected text:
   "dev-proxy changed this live", "dev-proxy intercepted me", "Claude edited
   this response", "no Charles GUI needed", "json_patch on live traffic".

This is the exact case the README calls out: change a few fields on a real
live response, keep the rest. Charles has no direct equivalent.

**Demo 2 — force an API to fail (a core Charles feature).**

1. I swapped the rule to force a `503` on the same endpoint.
2. I reopened the search screen. The popular-search list did not render. The
   app showed its failure state.
3. The dashboard logged the flow as `503` with the rule tag
   `search_force_fail:status:503`.

## Cleanup

- I removed every demo rule. `rules/rules.json` is back to an empty list.
- I turned the device proxy off. The device proxy is global, so I must not
  leave it on.

## A note on proof screenshots

The mobile screenshots show only public content and my injected text. They
are safe to share.

The dashboard screenshots show real request headers. Those headers carry auth
tokens and secrets for a logged-in test account. I did not commit or publish
those images. I keep the dashboard proof as text in this report.
