# Repository History Note

On 2026-10-22, before this repository was first published, its Git history was rewritten once
for privacy. Nothing else was changed. This note records exactly what was done so that the
history can still be audited.

## What changed

1. **Contact details.** A personal email address was replaced in commit, committer and tag
   metadata by the author's GitHub no-reply address.
2. **One line of code.** The HTTP User-Agent string in `src/transport_energy/data/download.py`
   contained the same email address. In every commit it now reads
   `transport-energy-quant research`. The string is sent as a request header when downloading
   public EIA and Internet Archive files. It is not used in any calculation.
3. **One document removed.** `docs/INTERVIEW_PREP.md`, a private preparation file, was removed
   from every commit. No code, data, result or analysis document depended on it.
4. **Learning notes reworded.** In `docs/learning/02_data_and_eda.md`, three first-person
   sample interview answers were rewritten as neutral "Takeaway" notes with the same facts,
   and one header bullet was reworded. The file was added in the Phase 7 commit and never
   edited, so only that commit and later ones changed.

The rewrite was done with `git-filter-repo` on a separate copy. The original history is kept
privately as a backup.

## What did not change

- Every other file in every commit is byte-identical to the original, including all of
  `configs/`, every other file in `src/`, and every table, figure and PDF in `reports/`.
- Commit order, author and committer dates, commit messages, tag names, and the tag date of
  `spec-freeze-v1` are unchanged.
- `main` and `spec-freeze-v1` still have identical `src/` and `configs/`, so the frozen-code
  check in `transport_energy.analysis.locked_test.verify_frozen` passes.
- The locked test was **not** re-run as part of this change.

## Commit hashes

Rewriting changes every commit hash. Old and new hashes:

| Commit | Original | Rewritten |
|---|---|---|
| Phase 2: repository scaffolding (tag `phase-2`) | `d4ec631` | `0ff35af` |
| Phase 3 code (WIP) and pre-registered analysis protocol | `87a5b09` | `c4d6b0e` |
| Phase 3 data build and Phase 4 EDA | `03b0dcd` | `347da43` |
| Phases 5–6 development results and spec freeze (tag `spec-freeze-v1`) | `201c204` | `613f473` |
| Phase 7: locked out-of-sample test results | `08ea03e` | `50fa0ac` |
| Phases 8–9: final report, README, report figures | `0d33784` | `a4f16e2` |
| Portfolio presentation: paper PDF, summary, figures | `11f199e` | `7461c9f` |

## What Git history does and does not show

Commit dates are recorded by the author's own machine and were first made public when the
repository was published. They are **not** independent, third-party proof of when the analysis
protocol or specification freeze happened. What the history does show is the order in which
work was committed and the exact contents of each step, so a reader can check that the protocol
and frozen specification precede the locked-test results and that the evaluated code matches the
frozen tag.
