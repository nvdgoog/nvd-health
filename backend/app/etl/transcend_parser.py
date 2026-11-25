from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.etl.pdf_parser import extract_pages_text_from_pdf_bytes

TRANSCEND_HEADER_RE = re.compile(r"(?:CPAP Compliance Report|FAA CPAP Compliance Report)", re.IGNORECASE)
TRANSCEND_DAYS_HEADER_RE = re.compile(r"CPAP Compliance Report\s+(\d+)\s+day", re.IGNORECASE)
DEVICE_SERIAL_RE = re.compile(
    r"Device\s+Serial(?:\s+Number)?\s*:?\s*([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
DATES_OF_REPORT_RE = re.compile(
    r"Dates\s+of\s+Report\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+to\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    re.IGNORECASE,
)
FAA_DATE_RANGE_RE = re.compile(
    r"From\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+To\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    re.IGNORECASE,
)
DAYS_USED_RE = re.compile(
    r"Days\s+Used\s*:?\s*(\d+)\s+of\s+(\d+)\s+days?",
    re.IGNORECASE,
)
FAA_DAYS_USED_RE = re.compile(
    r"#\s*of\s*Days\s*Used\s*:?\s*(\d+)\s+#\s*of\s*Days\s*Covered\s*:?\s*(\d+)",
    re.IGNORECASE,
)
AVG_HOURS_NIGHT_RE = re.compile(
    r"Average\s+Hours/Night\s*:?\s*([\d.]+)",
    re.IGNORECASE,
)
FAA_HOURS_MINS_RE = re.compile(
    r"Hours\s*:?\s*(\d+)\s+Minutes\s*:?\s*(\d+)",
    re.IGNORECASE,
)
REPORT_GENERATED_RE = re.compile(
    r"Report\s+Generated\s+on\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)?)",
    re.IGNORECASE,
)

# Numeric metric extractors
AHI_INDEX_RE = re.compile(r"(?:AHI\s+Index|AHI\s+with\s+Treatment.*?AHI\s*:)\s*([\d.]+)", re.IGNORECASE)
FAA_AHI_RE = re.compile(r"\bAHI\s*:\s*([\d.]+)", re.IGNORECASE)
APNEA_INDEX_RE = re.compile(r"\bApnea\s+Index\s*:?\s*([\d.]+)", re.IGNORECASE)
HYPOPNEA_INDEX_RE = re.compile(r"\bHypopnea\s+Index\s*:?\s*([\d.]+)", re.IGNORECASE)
TOTAL_APNEA_DUR_RE = re.compile(r"Total\s+Apnea\s+Duration\s*\(sec\)\s*:?\s*([\d.]+)", re.IGNORECASE)
PCT_TIME_APNEA_RE = re.compile(r"%\s+of\s+Time\s+Spent\s+in\s+Apnea\s*:?\s*([\d.]+)", re.IGNORECASE)
AVG_LEN_APNEA_RE = re.compile(r"Average\s+Length\s+of\s+Apneas\s*\(sec\)\s*:?\s*([\d.]+)", re.IGNORECASE)
LONGEST_APNEA_RE = re.compile(r"Longest\s+Apnea\s*\(sec\)\s*:?\s*([\d.]+)", re.IGNORECASE)
FLOW_LIMITED_RE = re.compile(r"Flow-Limited\s+Index\s*:?\s*([\d.]+)", re.IGNORECASE)
SNORE_INDEX_RE = re.compile(r"Snore\s+Index\s*:?\s*([\d.]+)", re.IGNORECASE)

AVG_LEAK_RE = re.compile(r"Average\s+Leak\s*:?\s*([\d.]+)\s*\(L/Min\)", re.IGNORECASE)
P95_LEAK_RE = re.compile(r"95\s+Percentile\s+Leak\s*:?\s*([\d.]+)\s*\(L/Min\)", re.IGNORECASE)

SLEEP_SCORE_RE = re.compile(r"Sleep\s+Score\s+(\d+(?:\.\d+)?)\s+of\s+100", re.IGNORECASE)
MASK_REMOVED_RE = re.compile(r"Mask\s+Removed\s+Average\s*:?\s*([\d.]+)", re.IGNORECASE)

# Pressure Summary appears below Patient Setting; capture all matches and take Pressure Summary values
MIN_PRESSURE_RE = re.compile(r"Minimum\s+Pressure\s*:?\s*([\d.]+)\s*\(cmH2O\)", re.IGNORECASE)
MAX_PRESSURE_RE = re.compile(r"Maximum\s+Pressure\s*:?\s*([\d.]+)\s*\(cmH2O\)", re.IGNORECASE)
AVG_PRESSURE_RE = re.compile(r"Average\s+Pressure\s*:?\s*([\d.]+)\s*\(cmH2O\)", re.IGNORECASE)
P95_PRESSURE_RE = re.compile(r"95\s+Percentile\s+Pressure\s*:?\s*([\d.]+)\s*\(cmH2O\)", re.IGNORECASE)


@dataclass
class TranscendParseResult:
    """Structured parse output from a Transcend Micro CPAP Compliance PDF."""

    report_metadata: Dict[str, Any]
    daily_rows: List[Dict[str, Any]]
    warnings: List[str] = field(default_factory=list)


def parse_flexible_us_date(raw: str) -> str:
    """Convert MM-DD-YYYY, MM/DD/YYYY, MM-DD-YY, or MM/DD/YY to ISO YYYY-MM-DD."""
    parts = re.split(r"[-/]", raw.strip())
    if len(parts) != 3:
        raise ValueError(f"Invalid US date: {raw!r}")
    month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
    if year < 100:
        year += 2000
    return date(year, month, day).isoformat()


def _parse_report_generated_iso(raw: str) -> Optional[str]:
    cleaned = re.sub(r"\s+", " ", raw.replace(",", " ").strip())
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%m/%d/%y %I:%M:%S %p"):
        try:
            return datetime.strptime(cleaned, fmt).isoformat()
        except ValueError:
            continue
    return None


def _match_float(pattern: re.Pattern[str], text: str, take_last: bool = False) -> Optional[float]:
    matches = pattern.findall(text)
    if not matches:
        return None
    raw = matches[-1] if take_last else matches[0]
    try:
        return float(raw)
    except ValueError:
        return None


def parse_transcend_pages(
    pages_text: List[str],
    source_file: str,
    run_id: str,
    ingested_at_iso: str,
    pdf_bytes: Optional[bytes] = None,
) -> TranscendParseResult:
    """
    Parse Transcend Micro CPAP PDF reports (Standard Compliance, Extended Sleep Score Compliance,
    or FAA Compliance) into report metadata and single-night therapy rows.
    """
    if not pages_text:
        raise ValueError("Transcend Micro PDF contains no extractable pages.")

    full_text = "\n".join(pages_text)
    if not TRANSCEND_HEADER_RE.search(full_text):
        raise ValueError(f"Unrecognized Transcend Micro report format in {source_file}")

    warnings: List[str] = []
    is_faa = bool(re.search(r"FAA\s+CPAP\s+Compliance\s+Report", full_text, re.IGNORECASE))
    is_extended = bool(
        re.search(r"Sleep\s+Score\s+Summary|Flow-Limited\s+Index|Snore\s+Index", full_text, re.IGNORECASE)
    )

    if is_faa:
        report_type = "faa_compliance"
        report_priority = 1
    elif is_extended:
        report_type = "compliance_extended"
        report_priority = 3
    else:
        report_type = "compliance_standard"
        report_priority = 2

    serial_m = DEVICE_SERIAL_RE.search(full_text)
    device_sn = serial_m.group(1) if serial_m else "UNKNOWN_TRANSCEND"

    dates_m = DATES_OF_REPORT_RE.search(full_text) or FAA_DATE_RANGE_RE.search(full_text)
    range_start = parse_flexible_us_date(dates_m.group(1)) if dates_m else None
    range_end = parse_flexible_us_date(dates_m.group(2)) if dates_m else None

    days_m = DAYS_USED_RE.search(full_text) or FAA_DAYS_USED_RE.search(full_text)
    header_days_m = TRANSCEND_DAYS_HEADER_RE.search(full_text)
    days_used = int(days_m.group(1)) if days_m else None
    total_days = int(days_m.group(2)) if days_m else (int(header_days_m.group(1)) if header_days_m else None)

    gen_m = REPORT_GENERATED_RE.search(full_text)
    report_generated_at = _parse_report_generated_iso(gen_m.group(1)) if gen_m else None

    avg_hrs = _match_float(AVG_HOURS_NIGHT_RE, full_text)
    if avg_hrs is not None:
        usage_hours = round(avg_hrs, 4)
        usage_minutes = int(round(avg_hrs * 60.0))
    else:
        hm_m = FAA_HOURS_MINS_RE.search(full_text)
        if hm_m:
            hrs_i, mins_i = int(hm_m.group(1)), int(hm_m.group(2))
            usage_minutes = hrs_i * 60 + mins_i
            usage_hours = round(usage_minutes / 60.0, 4)
        else:
            usage_minutes = None
            usage_hours = None

    ahi = _match_float(AHI_INDEX_RE, full_text)
    if ahi is None:
        ahi = _match_float(FAA_AHI_RE, full_text)

    # Focus pressure summary extraction below "Pressure Summary" if present, else fallback take_last
    pressure_section = full_text
    ps_idx = full_text.lower().find("pressure summary")
    if ps_idx >= 0:
        pressure_section = full_text[ps_idx:]

    min_pressure = _match_float(MIN_PRESSURE_RE, pressure_section, take_last=True)
    max_pressure = _match_float(MAX_PRESSURE_RE, pressure_section, take_last=True)
    avg_pressure = _match_float(AVG_PRESSURE_RE, pressure_section, take_last=True)
    p95_pressure = _match_float(P95_PRESSURE_RE, pressure_section, take_last=True)

    avg_leak = _match_float(AVG_LEAK_RE, full_text)
    p95_leak = _match_float(P95_LEAK_RE, full_text)

    apnea_index = _match_float(APNEA_INDEX_RE, full_text)
    hypopnea_index = _match_float(HYPOPNEA_INDEX_RE, full_text)
    total_apnea_dur = _match_float(TOTAL_APNEA_DUR_RE, full_text)
    pct_time_apnea = _match_float(PCT_TIME_APNEA_RE, full_text)
    avg_len_apnea = _match_float(AVG_LEN_APNEA_RE, full_text)
    longest_apnea = _match_float(LONGEST_APNEA_RE, full_text)
    flow_limited = _match_float(FLOW_LIMITED_RE, full_text)
    snore_index = _match_float(SNORE_INDEX_RE, full_text)
    sleep_score = _match_float(SLEEP_SCORE_RE, full_text)
    mask_removed = _match_float(MASK_REMOVED_RE, full_text)

    report_id = (
        hashlib.sha256(pdf_bytes).hexdigest()[:24]
        if pdf_bytes is not None
        else hashlib.sha256(
            f"{device_sn}|{report_type}|{range_start}|{range_end}|{report_generated_at}".encode("utf-8")
        ).hexdigest()[:24]
    )

    report_metadata: Dict[str, Any] = {
        "report_id": report_id,
        "device_sn": device_sn,
        "report_type": report_type,
        "report_priority": report_priority,
        "report_generated_at": report_generated_at,
        "report_date_range_start": range_start,
        "report_date_range_end": range_end,
        "days_used": days_used,
        "total_days": total_days,
        "avg_hours_per_night": usage_hours,
        "avg_pressure": avg_pressure,
        "p95_pressure": p95_pressure,
        "avg_leak": avg_leak,
        "p95_leak": p95_leak,
        "ahi": ahi,
        "sleep_score": sleep_score,
        "_ingested_at": ingested_at_iso,
        "_source_file": source_file,
        "_run_id": run_id,
        "_row_hash": report_id,
    }

    daily_rows: List[Dict[str, Any]] = []
    # Transcend 1-day compliance reports represent sleep starting on range_start and waking on range_end.
    is_single_night = (total_days == 1) or (
        range_start is not None
        and range_end is not None
        and (date.fromisoformat(range_end) - date.fromisoformat(range_start)).days <= 1
    )

    if is_single_night and (range_end or range_start):
        usage_date = range_end or range_start
        if days_used == 0 and usage_minutes is None:
            usage_minutes = 0
            usage_hours = 0.0
        row_hash = hashlib.sha256(
            f"{usage_date}|{device_sn}|{report_type}|{usage_minutes}|{ahi}|{sleep_score}".encode("utf-8")
        ).hexdigest()
        daily_rows.append(
            {
                "usage_date": usage_date,
                "device_sn": device_sn,
                "usage_minutes": usage_minutes,
                "usage_hours": usage_hours,
                "pressure": avg_pressure,
                "min_pressure": min_pressure,
                "max_pressure": max_pressure,
                "p95_pressure": p95_pressure,
                "ahi": ahi,
                "apnea_index": apnea_index,
                "hypopnea_index": hypopnea_index,
                "total_apnea_duration_sec": total_apnea_dur,
                "pct_time_in_apnea": pct_time_apnea,
                "avg_apnea_length_sec": avg_len_apnea,
                "longest_apnea_sec": longest_apnea,
                "flow_limited_index": flow_limited,
                "snore_index": snore_index,
                "avg_leak": avg_leak,
                "p95_leak": p95_leak,
                "sleep_score": sleep_score,
                "mask_removed_avg": mask_removed,
                "mode": "Auto-CPAP (Transcend Micro)",
                "report_type": report_type,
                "report_priority": report_priority,
                "report_generated_at": report_generated_at or ingested_at_iso,
                "_ingested_at": ingested_at_iso,
                "_source_file": source_file,
                "_run_id": run_id,
                "_row_hash": row_hash,
            }
        )
    else:
        warnings.append(
            f"Multi-day Transcend summary ({total_days} days) saved to bronze_transcend_reports only; export 1-day reports for nightly rows."
        )

    return TranscendParseResult(
        report_metadata=report_metadata,
        daily_rows=daily_rows,
        warnings=warnings,
    )


def parse_transcend_pdf_bytes(
    pdf_bytes: bytes,
    source_file: str,
    run_id: str,
    ingested_at_iso: str,
) -> TranscendParseResult:
    """Extract text from raw Transcend Micro PDF bytes and parse structured metrics."""
    pages_text = extract_pages_text_from_pdf_bytes(pdf_bytes)
    return parse_transcend_pages(
        pages_text=pages_text,
        source_file=source_file,
        run_id=run_id,
        ingested_at_iso=ingested_at_iso,
        pdf_bytes=pdf_bytes,
    )
