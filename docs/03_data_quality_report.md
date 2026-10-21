# Phase 3: Data Collection, Point-in-Time Construction and Data Quality

*Built 2026-10-21 by `uv run python -m transport_energy.data.build`. A re-run with
`--offline` regenerates every table from the cached files. All numbers below come from
`reports/tables/phase3/`. Test-period (2017+) checks report **counts only**.*

## 1. What was collected

| Group | Files | Source | Use |
|---|---|---|---|
| EIA weekly fundamentals | 6 | `eia.gov/dnav/pet/hist_xls/*.xls` | demand, inventories |
| EIA NYMEX settlements (CL, RB, contracts 1–3) | 6 | same | futures prices, 1983/2005 to 2024-04-05 |
| EIA WTI spot | 1 | same | context only |
| WPSR archive index | 1 | `eia.gov/petroleum/supply/weekly/archive/` | **observed** release dates |
| WPSR Table 1, every edition | 793 | `archive/<edition>/csv/table1.csv` | **first-published** values |
| EIA release-schedule pages | 1 live + 194 archived copies | `schedule.php` / `.cfm` / `.html` (Internet Archive) | **documented** release times |
| CME contract calendars | 96 archived copies | cmegroup.com product calendars (Internet Archive) | exchange-published last-trade dates |
| NYMEX Rulebook ch. 200 (CL), ch. 191 (RB) | 4 archived copies | cmegroup.com (Internet Archive) | expiry rules and contract specs |

**Provenance.** Every one of the 1,105 files is recorded in `data/raw/MANIFEST.json` with
its URL, the original page it copies (for archived copies), UTC download time, size and
SHA-256 hash. `reports/tables/phase3/manifest_eia.csv` lists the EIA series files.

**Access notes.**
- cmegroup.com blocks automated access, and its terms prohibit scripts. Only Internet Archive
  copies of CME pages were used.
- FRED, needed for the VMT driving data, timed out on 2026-10-21. VMT was a secondary
  validation only and was dropped. See §7.
- No data was purchased; Databento was deferred.

## 2. Release calendar: observed dates, documented times

- **Dates are observed.** The archive lists 793 editions, from 2011-08-03 to 2026-10-21.
  - Every data week ends on a Friday, and none is duplicated.
  - Two editions have folder names that differ from their release dates: `2022_06_17_data`,
    released 2022-06-29 during the EIA systems outage, and `2023_11_03_data`, released
    2023-11-15.
- **Times are documented schedules, never observations.**
  - A time is used only when an EIA schedule page in force for that period stated it, *and*
    the observed release date equals the scheduled date.
  - Otherwise the release is treated as possibly anywhere in that day, 00:00–23:59:59 ET.
  - Windows *close* at the earliest possible time and *open* after the latest, so an uncertain
    time can only delay entry, never advance it.

| Outcome | Editions |
|---|---|
| Time documented by a schedule page, date matches | **791** |
| Conservative whole-day window | **2**: 2012-11-01 (Hurricane Sandy week; scheduled 10-31) and 2023-11-15 (scheduled 11-08) |

- **Release times that were used:**

  | Release time | Editions |
  |---|---|
  | Wednesday 10:30 | 674 |
  | Thursday 11:00 | 94 |
  | Thursday 12:00 | 11 |
  | Friday 11:00 | 9 |
  | Monday 10:30, Friday 13:00, Monday 17:00 | 1 each |
  | Conservative whole day | 2 |

  Holiday times changed over the years: 10:30 in 2007, 11:00 in 2014–15, 12:00 in 2025. So no
  holiday time is assumed.
- **Schedule copies that disagreed.** 16 data weeks have schedule copies that disagree. The
  latest copy captured before the release wins. Details are in `schedule_conflicts.csv`.

### Assumption A: the pre-2011 timing rule

> **Assumption A:** in non-holiday weeks, the report for data week F is public by Friday F+7
> at 14:29 ET.

| Weeks (2011-08 → 2026-10) | Releases | Violations |
|---|---|---|
| Non-holiday | 635 | **0** |
| Holiday (excluded by the rule) | 158 | 4: 2013-10-21 (shutdown/Columbus Day), 2022-06-29 (outage/Juneteenth), 2023-11-15, 2025-12-29 (Christmas) |

- Archived pre-2011 schedule pages document 40 holiday exceptions from 2006 to 2011. All were
  Thursday releases at F+6, at 10:30 or 11:00.
- The assumption is therefore **validated** and set in `configs/research.yaml` as
  `days_after_reference: 7`. Before this check it was `null`, and the code refused to build
  pre-2011 trades.

## 3. First-release vs current history (revisions)

Archived Table 1 from all 793 editions was compared with today's history files. Tolerance is
0.5 thousand barrels or kb/d.

| Series | Development weeks matching (2011-08 → 2016) | Test weeks matching (counts only) |
|---|---|---|
| Crude stocks ex-SPR (level) | **10 / 283** | 509 / 510 |
| Gasoline stocks | 281 / 283 | 509 / 510 |
| Distillate stocks | 281 / 283 | 509 / 510 |
| Gasoline product supplied | 282 / 283 | 510 / 510 |
| Crude production | 283 / 283 | 510 / 510 |
| Total product supplied (not used) | 182 / 283 | 343 / 510 |

**Crude stocks were restated in October 2016.**
- The edition after the week of 2016-09-30 re-printed that week 30,640 kb lower.
- The current history file applies the new definition backwards. It is lower than what was
  published by about 22–33 million barrels, depending on the year:

  | Year | Mean gap, history − first-release (kb) |
  |---|---|
  | 2011 | −22,136 |
  | 2012 | −26,063 |
  | 2013 | −28,815 |
  | 2014 | −31,619 |
  | 2015 | −32,607 |

- The gap moves at month boundaries. As a result, **the weekly change the market saw differs
  from the history-file change in 61 of 283 development weeks**: usually by a few hundred kb,
  but by 3,133 kb on 2012-01-06.

**Decision (as doc 01 prescribed).**
- Surprises use the **as-first-published** values wherever an archived edition exists.
  - For stock series, the change printed in that edition (current-week column minus
    prior-week column).
  - For demand, the printed level.
- Before August 2011 no archive exists, so the history file is used and flagged.
- Editions are admitted to the development sample only if *released* before 2017-01-01. The
  edition for the week of 2016-12-30 came out on 2017-01-04 and is excluded.

**Week-to-week revisions are negligible.** Each edition's "prior week" column matches the
previous edition's "current" column in 280–282 of 282 development weeks. The exceptions are
the restatement and two small corrections.

## 4. Contract expiries

**Documentation, in order of precedence:**
1. **CME-published last-trade dates**, from archived product calendars:
   - CL: 123 contracts, last trades 2010-03 → 2022-11;
   - RB: 68 contracts, last trades 2011-04 → 2016-11.

   Later copies of CME's page are rendered by JavaScript and carry no dates.
2. **The rulebook rule**, elsewhere. The text in NYMEX ch. 200 / ch. 191, 2015 and 2024/2026
   copies, is identical to EIA's series definitions:
   - CL: 3 business days before the 25th of the month before delivery;
   - RB: the last business day of the month before delivery.

   The rule is applied to a **scheduled exchange calendar**: weekdays minus federal holidays
   and Good Fridays *with no settlement*.

**Why not use EIA's price dates as the business-day calendar?** EIA's files omit days the
exchange was open:
- abbreviated sessions after Thanksgiving, on Christmas Eve and around July 4;
- isolated data gaps, such as 2016-06-02.

Counting EIA dates would move some expiries by a day. For example, CLZ2001 comes out as
Nov 16 instead of Nov 19; `tests/unit/test_exchange_and_expiry.py` covers this case.

**Rule vs CME, where both exist:**
- **RB: 68 / 68.**
- **CL: 119 / 123.** The four misses (CLZ2011, CLZ2012, CLZ2018, CLF2019) all involve the
  day after Thanksgiving or Christmas week, which CME treated inconsistently across years.
- Wherever CME dates exist they are used. The rule supplies pre-2010 contracts, RB after 2016,
  and CL after 2022.

**Settlement diagnostic (secondary, never sets a date).**
- Calendar spreads move much less from day to day than outright prices. So if contract 1
  rolled after day e, the C1−C2 spread on the next day should match day e's C2−C3 spread.
- The first version compared outright prices instead. It had no power: it flagged 57 of 82
  CME-published expiries, which are authoritative. It was replaced.

| Development 1996–2016, informative cases | Best-fitting roll day = documented date |
|---|---|
| CL | 180 / 225 (80%); 26 fit one day earlier |
| RB | 106 / 134 (79%) |

- CME-published and rule-based dates score the same. The remaining ~20% is therefore the
  diagnostic's own noise, not dating error.
- **Residual risk.** A possible one-day labelling ambiguity on the expiry day affects only a
  window that *starts or ends* on that day:
  - 18% of CL and 17% of RB events do;
  - the error is about one calendar spread, roughly 0.5% of price, in the ~12% of expiries
    where it may occur;
  - that is around 2% of events, against a 3.3% event standard deviation.

  Positions roll 5 business days before expiry, so the expiring contract is never held.

## 5. Contract specifications (rulebook)

| | CL | RB |
|---|---|---|
| Contract size | 1,000 bbl | 42,000 gal |
| Tick size | $0.01/bbl, so $10 per contract | $0.0001/gal, so $4.20 per contract |

Both match `configs/research.yaml`.

## 6. Automated quality counts (`quality_weekly.csv`, `quality_futures.csv`)

- **Weekly series.**
  - No non-Friday dates, duplicates or non-positive values.
  - Missing Fridays are 0–6 per series, all before 2017 and almost all before 1996. The test
    period has none.
- **Futures.**
  - In the test period, 3–4 scheduled business days are missing per nearby series.
  - One non-positive settlement: CL contract 1 at −$37.63 on 2020-04-20. P&L is computed in
    dollars, and positions roll 5 days before expiry, so that contract is not held.
  - **Partial rows** are days when only some nearbys have prices: 878 for CL (636 before 1996,
    mostly before contract 2 began in 1985) and 78 for RB.
  - Any event whose held contract lacks a settlement inside its window is skipped and counted.

## 7. Limitations carried forward

1. **Surprises before August 2011 use the history file**, not first releases. For crude
   stocks, the October 2016 restatement means the changes differ from what was published in
   some month-start weeks.
2. **Futures end on 2024-04-05**, when EIA stopped publishing them. The locked test therefore
   covers 2017-01 → 2024-04-05.
3. **Release times are scheduled, not observed.** A release delayed by more than about 4 hours
   on a normal Wednesday would be missed. None is known; the documented outages moved the
   release date and are treated as such.
4. **VMT validation was dropped**, because FRED was unreachable and FHWA publishes VMT only as
   per-month report workbooks. VMT was never a trading input.
5. **RB expiries after 2016 and CL expiries after 2022-11 rely on the rulebook rule.** That
   rule was validated at 68/68 and 119/123 against CME.
