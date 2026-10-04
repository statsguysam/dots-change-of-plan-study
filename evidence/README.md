# Dots change-of-plan case study

This is an explicitly redacted public derivative of a private study archive. It is not byte-identical to the original freeze. The local ZIP does not imply a public upload.

## Provenance and integrity

- `provenance/original-local-freeze.json` preserves the original local timestamp, protocol identity and protected-file hashes exactly. The study was locally frozen, not independently publicly preregistered.
- `PUBLIC_INTEGRITY.json` and the identical `data/freeze.json` identify the sanitized protected bytes in this export. Their derived protocol ID is a public integrity identifier, not a claim that the experiment ran against different prompts.
- Exported observations retain `source_protocol_sha256` and use the public derived ID in `protocol_sha256` solely for the unchanged scorer's integrity checks. Reviewed state, check values and outcomes remain unchanged.
- `PUBLIC_MANIFEST.json` records original and public hashes for every included source, identifies changed protected files, and reports omitted binary evidence.
- `provenance/source-scores.redacted.json` preserves the reviewed source scores. `results/scores.json` contains a recomputation on this public derivative. The builder requires identical episode results and headline counts before releasing a final package.
- Original audit/evidence hashes inside records refer to original private bytes. Consult the public manifest for hashes of redacted copies. Raw private originals remain with the study operator.

Private product URLs, native job identifiers, local/cloud file paths and system identifiers receive consistent aliases. Images and other binary evidence are excluded because text substitution cannot sanitize them. These omissions limit reconstruction of the complete native UI state.

## Recompute the exported analysis

Run Python 3 from this bundle's root:

```sh
python3 scripts/study.py validate
python3 scripts/study.py score
```

The first command checks fixtures and arithmetic. The second verifies the public derived protected-file hashes and recomputes outcomes from reviewed observations. It does not authenticate the original cloud session or original private artifact bytes. No source code modification is required for this path.

## Scope

One persistent Dot and one reused conversation permit carryover. Six related scenario families and repeated episodes do not provide an independent population sample. Two changed episodes have separate native scheduling observations and retained-event jobs, without matched native procurement controls. Never pool those native cases into the primary score.

The completed-draft action rule requires inspected current unsent drafts. A chat acknowledgment cannot establish saved-file correctness or cancellation. Download hashes identify locally inspected bytes, not an unexposed cloud original. An AI operator performed UI and evidence work, so no user correction does not mean zero operational effort.
