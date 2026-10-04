# Can an AI agent stop the right work?

“Cancel the draft” should retire an email. “Cancel procurement” should retire the purchase plan. Both instructions can leave the onboarding event intact.

That distinction makes a useful applied AI experiment. A convincing reply is only one piece of evidence. The saved decision, the draft and the pending jobs can each retain an older instruction. I wanted to inspect those consequences separately.

I tested Dots on a synthetic onboarding procurement task, using one persistent cloud agent and one conversation. The baseline called for 40 kits by October 30 within INR 225,000. A supplied supplier table made Alder the cheapest approved option at INR 212,000. The packet explicitly defined who could change the plan and how active, paused and cancelled states should behave.

## What the study actually measured

Six related families covered budget, delivery date, supplier approval, headcount, pause and cancellation. Each had an authority/scope control: a message that should preserve the approved procurement state, even when a particular artifact should change.

Authorized changes: 6/6 complete-episode passes. Authority/scope controls: 6/6 complete-episode passes.

A pass required a correct baseline and update, actual saved artifacts, preserved valid obligations and history, no observed forbidden committed action, and any required routine probe. Baseline and update limits were 15 and 10 minutes. The probe checked preservation separately.

Structured fields used fixed checks, with a separate review of the saved artifacts. The [methods](ANALYSIS.md#execution-and-review) describe execution and review. A raw action such as `await_owner_approval` counted as the expected draft-preparation action only when the required complete unsent draft was actually present, under the rule frozen before scored work.

## One word, two different changes

The most useful trace was cancellation. CEDAR-007 cancelled supplier-email draft v1. Procurement stayed active at 40 kits and INR 212,000. The updated plan saved the exact requested unsent v2 and preserved the earlier draft as superseded history.

CEDAR-008 cancelled procurement. Its saved decision set current kits to 0 and cleared the active supplier and total. The event obligations remained. Those are different consequences of different supplied instructions, supported by downloaded files. They do not demonstrate discovery of unstated business policy.

This is a practical test to add to an agent evaluation: after a change, inspect both what should stop and what should continue. The scope of a cancellation matters as much as the word “cancel”.

## Saved files and pending jobs are separate evidence

Only the changed pause and cancellation episodes also received actual native scheduled jobs: one procurement job and one retained-event job. The update explicitly instructed Dots to disable procurement while keeping the event.

Pause: the procurement job stayed disabled through the observed window; the retained event produced its inspected checklist. Cancellation: the procurement job stayed disabled through the observed window; the retained event produced its inspected checklist.

These are two individual observations, with retained-event positive controls but no matched no-change procurement controls. They do not establish a population reliability rate.

The cancellation case also exposed an evidence trap. After cleanup, both cards said Completed. Before cleanup, procurement had remained Paused with Resume and no visible execution entry through the observed window; the event had produced an actual inspected checklist. A Completed label by itself was insufficient to tell what ran.

The evidence has layers. JSON and Markdown downloads are actual local bytes with hashes. Native UI history is recorded mainly in timestamped operator notes. The review covered these notes and files, without independent access to hidden backend state. File absence and last-run fields were Dots reports. The cancellation finding is bounded by the observation window.

In the pause case, the event card said Completed before its nominal 15:02 UTC due time; the actual checklist was first observed at 15:04:49, within the grace window. Dots reported early dispatch, but hidden timestamps were not independently verified. This is no claim of exact schedule punctuality.

## The limitations belong beside the result

The agent received explicit rules and direct updates. This did not test spontaneous detection of a changed document, inferred policy or stale memory in general. Shared conversation and unchanged memory permit carryover; separate project folders do not make the six families independent.

Routine probes needed additional read-only export requests when no new attachments appeared. Post-probe downloads matched the update bytes. Native inspections, cleanup and recovery from a cached view and a collapsed-sidebar selector added operational work. No result-based reruns occurred.

Observed median baseline and update intervals were 104.1 and 105.0 seconds, respectively, with 0 recorded timeouts or late completions. These are UI-acceptance-to-first-attachment capture intervals, affected by polling, Send/AX duration and operator delay; they are neither exact model runtime nor uniformly strict upper bounds. No task-solving human correction was logged, but operator effort was unmeasured.

The study used ChatGPT Pro on 4 October 2026. Exact model routing was unknown. Additional spend was INR 0, excluding the existing subscription. Two setup trials were excluded. The permitted 12-episode minimum was chosen for the ASAP deadline before the remaining four primary and final native outcomes; the optional second block was not run. There was no Muse comparison.

## What I would add to an evaluation

Check the revised files and relevant pending jobs separately. Preserve history without treating superseded work as current authority. Test a narrowly scoped cancellation alongside one that ends the underlying work. Record what continued as carefully as what stopped.

The protocol was locally hashed, not publicly preregistered. The [full study report](ANALYSIS.md) contains the rubric, timing details, evidence links and sources. [Dots controls](https://learn.chatgpt.com/docs/dots/controls) documents distinct pause/schedule behavior; [TRACE](https://arxiv.org/abs/2609.33517) provides research motivation for information validity after state changes. This experiment is not a TRACE replication.
