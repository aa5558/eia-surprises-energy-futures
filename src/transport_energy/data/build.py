"""Phase 3 data build: ``uv run python -m transport_energy.data.build [--offline]``.

Steps (each writes audit tables to ``reports/tables/phase3/``):

1. EIA weekly fundamentals, futures and spot files (keyless bulk Excel).
2. WPSR release calendar: archive index (observed dates) + schedule documentation.
3. Assumption A (pre-2011 release window) checked on observed 2011+ releases.
4. First-release vs current history, from archived WPSR Table 1 of every edition.
5. Contract expiries: CME-published dates + rulebook rule, rule validated against CME,
   settlement diagnostic on the development sample only.
6. Data-quality counts.

``--offline`` re-parses what is already in ``data/raw`` without any network access.
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from transport_energy.config import REPO_ROOT, load_config
from transport_energy.data import (
    eia,
    exchange_calendar,
    expiry_check,
    quality,
    wayback,
    wpsr_tables,
)
from transport_energy.data import release_calendar as rc
from transport_energy.data.download import DEFAULT_RAW, DownloadError, Fetcher, load_manifest
from transport_energy.integrity import default_test_start, development_slice, guard_development

log = logging.getLogger("build")
OUT = REPO_ROOT / "reports" / "tables" / "phase3"
PROCESSED = REPO_ROOT / "data" / "processed"


def _write(df: pd.DataFrame, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / name, index=False)
    log.info("wrote %s (%d rows)", name, len(df))


# --------------------------------------------------------------------------- step 1
def step_eia(fetcher: Fetcher | None, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    if fetcher is not None:
        for group in ("weekly", "futures_daily", "spot_daily"):
            eia.download_group(group, fetcher, cfg)
    weekly = eia.load_group("weekly", DEFAULT_RAW, cfg)
    futures = eia.load_group("futures_daily", DEFAULT_RAW, cfg)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    weekly.to_csv(PROCESSED / "eia_weekly_history.csv", index_label="week_ending")
    futures.to_csv(PROCESSED / "eia_futures_nearby.csv", index_label="date")
    return weekly, futures


# --------------------------------------------------------------------------- step 2
def _schedule_pages(
    fetcher: Fetcher | None, archive: Fetcher | None, cfg: dict
) -> list[rc.SchedulePage]:
    e = cfg["eia"]
    if fetcher is not None:
        fetcher.fetch(e["schedule_live_url"], "eia/schedule/live_schedule.html")
    if archive is not None:
        for url in e["schedule_archived_urls"]:
            for _, snap in wayback.snapshots(archive, url).iterrows():
                rel = f"eia/schedule/wayback_{snap['timestamp']}.html"
                try:
                    archive.fetch(wayback.raw_url(snap["timestamp"], snap["original"]), rel,
                                  original_url=snap["original"])
                except DownloadError as exc:
                    log.warning("schedule copy skipped: %s", exc)
    pages = []
    for rel, entry in load_manifest(DEFAULT_RAW).items():
        if not rel.startswith("eia/schedule/"):
            continue
        html = (DEFAULT_RAW / rel).read_text(encoding="utf-8", errors="replace")
        if rel.endswith("live_schedule.html"):
            snap = pd.Timestamp(entry["downloaded_at"]).tz_localize(None)
        else:
            snap = pd.Timestamp(rel.split("_")[-1].removesuffix(".html"))
        pages.append(rc.parse_schedule_page(html, snap, entry["original_url"]))
    return pages


def step_release_calendar(
    fetcher: Fetcher | None, archive: Fetcher | None, cfg: dict
) -> pd.DataFrame:
    if fetcher is not None:
        fetcher.fetch(cfg["eia"]["wpsr_archive_url"], "eia/wpsr_archive/index.html",
                      refresh=True)
    html = (DEFAULT_RAW / "eia/wpsr_archive/index.html").read_text(encoding="utf-8",
                                                                   errors="replace")
    editions = rc.parse_archive_index(html)
    pages = _schedule_pages(fetcher, archive, cfg)
    exceptions, coverage, conflicts = rc.combine_schedules(pages)
    cal = rc.build_release_calendar(editions, exceptions, coverage)
    cal["holiday_week"] = rc.holiday_week_flags(cal["data_ending"])
    _write(exceptions, "schedule_exceptions.csv")
    _write(coverage, "schedule_coverage.csv")
    _write(conflicts, "schedule_conflicts.csv")
    _write(cal, "release_calendar.csv")
    PROCESSED.mkdir(parents=True, exist_ok=True)
    cal.to_csv(PROCESSED / "release_calendar.csv", index=False)
    return cal


# --------------------------------------------------------------------------- step 3
def step_assumption_a(cal: pd.DataFrame) -> pd.DataFrame:
    chk = rc.check_release_window(cal, days_after=7, assumed_by="14:29")
    _write(chk[chk["violates"]], "assumption_a_violations.csv")
    summary = (chk.groupby("holiday_week")
               .agg(releases=("violates", "size"), violations=("violates", "sum"))
               .reset_index())
    _write(summary, "assumption_a_summary.csv")
    _write(chk.groupby(["holiday_week", "days_after_reference"]).size()
              .rename("releases").reset_index(), "release_lag_distribution.csv")
    return chk


# --------------------------------------------------------------------------- step 4
def step_first_release(
    fetcher: Fetcher | None, cal: pd.DataFrame, weekly: pd.DataFrame
) -> pd.DataFrame:
    frames, missing = [], []
    for _, ed in cal.iterrows():
        folder = ed["edition_url"].rsplit("/", 1)[0]
        tag = folder.rsplit("/", 1)[1]
        rel = f"eia/wpsr_archive/{tag}/table1.csv"
        path = DEFAULT_RAW / rel
        if fetcher is not None and not path.exists():
            try:
                fetcher.fetch(f"{folder}/csv/table1.csv", rel)
            except DownloadError as exc:
                missing.append({"edition": tag, "error": str(exc)})
                continue
        if not path.exists():
            missing.append({"edition": tag, "error": "not downloaded"})
            continue
        try:
            t = wpsr_tables.parse_table1(path.read_text(encoding="latin-1"))
        except ValueError as exc:
            missing.append({"edition": tag, "error": str(exc)})
            continue
        frames.append(t.assign(edition=tag, release_date=ed["release_date"]))
    first = pd.concat(frames, ignore_index=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    first.to_csv(PROCESSED / "wpsr_first_release_long.csv", index=False)
    _write(pd.DataFrame(missing, columns=["edition", "error"]), "table1_missing.csv")

    cmp_ = wpsr_tables.compare_with_history(first, weekly)
    w2w = wpsr_tables.week_to_week_revisions(first)
    test_start = default_test_start()
    # Detail (values, differences) only for development weeks; test weeks -> counts only.
    _write(cmp_[cmp_["week"] < test_start], "first_release_vs_history_development.csv")
    cmp_["period"] = (cmp_["week"] >= test_start).map({False: "development", True: "test"})
    w2w["period"] = (w2w["week"] >= test_start).map({False: "development", True: "test"})
    summary = (cmp_.groupby(["series", "period"])
               .agg(weeks=("matches", "size"), matches=("matches", "sum"),
                    missing_in_history=("history", lambda s: int(s.isna().sum())))
               .reset_index())
    _write(summary, "first_release_summary.csv")
    _write(w2w.groupby(["series", "period"])
              .agg(weeks=("matches", "size"), unchanged_next_edition=("matches", "sum"))
              .reset_index(), "week_to_week_revision_summary.csv")
    _write(w2w[(w2w["period"] == "development") & ~w2w["matches"]],
           "week_to_week_revisions_development.csv")
    return cmp_


# --------------------------------------------------------------------------- step 5
def _cme_calendars(archive: Fetcher | None, cfg: dict, root: str) -> pd.DataFrame:
    frames = []
    if archive is not None:
        for url in cfg["cme"]["calendar_archived_urls"][root]:
            snaps = wayback.snapshots(archive, url, collapse="timestamp:6")
            snaps = snaps.groupby(snaps["captured"].dt.to_period("Q")).head(1)  # quarterly
            for _, s in snaps.iterrows():
                rel = f"cme/calendar/{root}_{s['timestamp']}.html"
                try:
                    archive.fetch(wayback.raw_url(s["timestamp"], s["original"]), rel,
                                  original_url=s["original"])
                except DownloadError as exc:
                    log.warning("CME calendar copy skipped: %s", exc)
    for path in sorted((DEFAULT_RAW / "cme" / "calendar").glob(f"{root}_*.html")):
        ts = pd.Timestamp(path.stem.split("_")[1])
        frames.append((ts, exchange_calendar.parse_cme_calendar(
            path.read_text(encoding="utf-8", errors="replace"), root)))
    cme, conflicts = exchange_calendar.combine_cme_calendars(frames)
    _write(conflicts, f"cme_calendar_conflicts_{root}.csv")
    used = pd.DataFrame([{"snapshot": ts, "contracts_listed": len(df)} for ts, df in frames])
    _write(used, f"cme_calendar_snapshots_{root}.csv")
    return cme


def _rulebooks(archive: Fetcher | None, cfg: dict) -> None:
    if archive is None:
        return
    for root, spec in cfg["cme"]["rulebook_archived"].items():
        for ts in spec["captures"]:
            archive.fetch(wayback.raw_url(ts, spec["url"]), f"cme/rulebook/{root}_{ts}.pdf",
                          original_url=spec["url"])


def step_expiries(archive: Fetcher | None, cfg: dict, futures: pd.DataFrame) -> dict:
    research = load_config("research")
    _rulebooks(archive, cfg)
    results = {}
    for root in ("CL", "RB"):
        r = root.lower()
        nearby = futures[[f"{r}_c1", f"{r}_c2", f"{r}_c3"]].dropna(how="all")
        price_dates = nearby.index
        # scheduled calendar: from price coverage to two years past the last CME listing
        bdays = exchange_calendar.scheduled_business_days(
            price_dates[0], pd.Timestamp("2030-12-31"), price_dates)
        rule = expiry_check.rule_expiries(root, research["contracts"][root]["expiry_rule"],
                                          bdays)
        rule = rule[rule["expiry"] <= price_dates[-1]]   # rule needs observed holidays
        cme = _cme_calendars(archive, cfg, root)
        cmp_ = expiry_check.compare_rule_to_cme(rule, cme)
        _write(cmp_, f"expiry_rule_vs_cme_{root}.csv")
        final = expiry_check.final_expiries(rule, cme)
        _write(final, f"expiries_{root}.csv")
        _write(exchange_calendar.exchange_holidays(
            price_dates[0], price_dates[-1], price_dates).to_frame(name="holiday"),
            f"exchange_holidays_{root}.csv")
        # settlement diagnostic: development sample only
        dev = guard_development(development_slice(nearby))
        dev = dev.rename(columns=lambda c: c.split("_")[1])
        dev_exp = final[final["expiry"] < default_test_start()]
        diag = expiry_check.settlement_diagnostic(
            dev, dev_exp, tick=research["contracts"][root]["tick_size"])
        _write(diag, f"expiry_settlement_diagnostic_{root}.csv")
        results[root] = {"rule_vs_cme": cmp_, "final": final, "diagnostic": diag,
                         "business_days": bdays}
    return results


# --------------------------------------------------------------------------- step 6
def step_quality(weekly: pd.DataFrame, futures: pd.DataFrame, expiries: dict) -> None:
    _write(quality.weekly_quality(weekly), "quality_weekly.csv")
    frames = []
    for root in ("CL", "RB"):
        r = root.lower()
        cols = [f"{r}_c1", f"{r}_c2", f"{r}_c3"]
        frames.append(quality.futures_quality(futures[cols], expiries[root]["business_days"]))
        part = quality.partial_rows(futures[cols].dropna(how="all"))
        _write(part.reset_index(names="date"), f"futures_partial_rows_{root}.csv")
    _write(pd.concat(frames, ignore_index=True), "quality_futures.csv")


def write_manifest_summary() -> None:
    m = pd.DataFrame(load_manifest(DEFAULT_RAW).values())
    m["group"] = m["path"].str.split("/").str[:2].str.join("/")
    _write(m.groupby("group").agg(files=("path", "size"), bytes=("bytes", "sum"),
                                  first_download=("downloaded_at", "min"),
                                  last_download=("downloaded_at", "max")).reset_index(),
           "manifest_summary.csv")
    eia_files = m[m["group"].isin(["eia/weekly", "eia/futures_daily", "eia/spot_daily"])]
    _write(eia_files[["path", "url", "downloaded_at", "sha256", "bytes"]], "manifest_eia.csv")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="parse cached files only")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg = load_config("data")
    fetcher = None if args.offline else Fetcher(DEFAULT_RAW, min_interval=1.0)
    # the Internet Archive rate-limits aggressively: one request every 4 s
    archive = None if args.offline else Fetcher(DEFAULT_RAW, min_interval=4.0)
    weekly, futures = step_eia(fetcher, cfg)
    cal = step_release_calendar(fetcher, archive, cfg)
    step_assumption_a(cal)
    step_first_release(fetcher, cal, weekly)
    exp = step_expiries(archive, cfg, futures)
    step_quality(weekly, futures, exp)
    write_manifest_summary()


if __name__ == "__main__":
    main()

