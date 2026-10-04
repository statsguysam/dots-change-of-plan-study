# Dots change of plan study

A study by Salim Shaikh, conducted on 4 October 2026.

Can an AI agent update saved decisions and stop the right pending work when business instructions change? This repository contains a small Dots case study, its analysis and a sanitized evidence bundle. All 12 primary episodes met the complete rubric: **6/6 authorized changes and 6/6 authority/scope controls**.

## What was tested

One synthetic onboarding workflow covered budget, delivery date, supplier approval, headcount, procurement pause and procurement cancellation. Each family paired an authorized change with a control that should preserve the approved procurement state. Business rules and updates were explicitly supplied.

A primary pass required a correct baseline and update, inspected saved artifacts, preserved history and valid obligations, no observed forbidden committed actions, and any required preservation probe.

The cancellation example shows why scope matters. Cancelling email draft v1 preserved the approved **40-kit, INR 212,000** purchase plan and produced the required unsent replacement draft. Cancelling procurement cleared the active supplier and cost, set kits to zero, and retained the event obligations.

## Pending jobs were checked separately

- **Pause case:** procurement remained disabled through the observed window, while the retained event produced an inspected checklist.
- **Cancellation case:** procurement remained disabled through the observed window, while the retained event produced an inspected checklist.

These are two individual bounded observations, without matched native procurement controls. UI labels alone did not establish execution or precise timing; the report distinguishes actual downloaded files, recorded UI observations and product-reported hidden fields.

## Read the results

- [Full analysis and evidence links](report/ANALYSIS.md)
- [Carousel PDF](assets/carousel.pdf) and [editable PowerPoint](assets/carousel.pptx)
- [Outcome chart](assets/outcome-chart.png)
- [Frozen protocol](evidence/docs/PROTOCOL.md) and [public evidence manifest](evidence/PUBLIC_MANIFEST.json)

## Reproduce the scoring

With Python 3, run these commands from the repository root:

```sh
cd evidence
python3 scripts/study.py validate
python3 scripts/study.py score
```

The intact `evidence/` bundle contains synthetic inputs, reviewed observations and the unchanged scorer. These commands validate the fixtures and recompute the recorded outcomes; they do not rerun Dots or authenticate hidden cloud state. See [evidence provenance](evidence/README.md) for original versus exported hashes and redactions. The protocol was locally hashed before scored work, not publicly preregistered.

## Scope and limitations

This was one persistent Dot, one reused conversation and six related scenario families, so carryover is possible and the results do not estimate general reliability. Explicit rules and directly delivered updates do not test spontaneous change discovery. The permitted 12-episode minimum was completed; the optional second block was not run. Two setup trials were excluded. Exact model routing was unknown, and no Muse comparison was conducted.

AI agents operated the UI and performed separate reviews of actual downloads and recorded observations; structured fields used deterministic checks. This was not independent human validation. Extra read-only export requests and native inspection/cleanup were operational work, with operator effort unmeasured.

Recorded additional spending was **INR 0**, excluding the existing ChatGPT Pro subscription.
