from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


DATE_RANGE_RE = re.compile(
    r"Date\s*range:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*-\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)
REPORT_GEN_RE = re.compile(
    r"Report\s*generated\s*(?:on)?\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)
USAGE_DAYS_RE = re.compile(
    r"Usage\s*Days\s*:?\s*(\d+)\s*/\s*(\d+)\s*days?\s*\(([\d.]+)%\)",
    re.IGNORECASE,
)
DAYS_GE_4H_RE = re.compile(
    r">=\s*4\s*hours\s*:?\s*(\d+)\s*days?",
    re.IGNORECASE,
)
BEST_30_RE = re.compile(
    r"Best\s*30\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*-\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+(\d+)\s*/\s*(\d+)\s*days?\s*\(([\d.]+)%\)",
    re.IGNORECASE,
)
PATIENT_NAME_RE = re.compile(
    r"Patient\s*(?:Name)?\s*:?\s*([A-Za-z][A-Za-z0-9 ,.'-]{1,80})",
    re.IGNORECASE,
)
AVG_PRESSURE_RE = re.compile(r"Avg\s*Pressure\s*:?\s*([\d.]+)", re.IGNORECASE)
AVG_P95_RE = re.compile(r"Avg\s*P95\s*:?\s*([\d.]+)", re.IGNORECASE)
AVG_LEAK_RE = re.compile(r"Avg\s*Leak\s*:?\s*([\d.]+)", re.IGNORECASE)
AVG_AHI_RE = re.compile(r"Avg\s*AHI\s*:?\s*([\d.]+)", re.IGNORECASE)
AVG_CAI_RE = re.compile(r"Avg\s*CAI\s*:?\s*([\d.]+)", re.IGNORECASE)

# Daily table row patterns:
# 1) Valid / 00:00 row:
#    11/18/26 07:09 5.0 0.1 5.5 0.0 3.9 Auto-CPAP A3126439542
VALID_ROW_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4})\s+"
    r"(\d{1,2}:\d{2})\s+"
    r"([\d.]+)\s+"
    r"([\d.]+)\s+"
    r"([\d.]+)\s+"
    r"([\d.]+)\s+"
    r"([\d.]+)\s+"
    r"([A-Za-z0-9_-]+)\s+"
    r"([A-Za-z0-9_-]+)\s*$"
)
NO_DATA_ROW_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4})\s+No\s+data\s+received\b",
    re.IGNORECASE,
)


@dataclass
class ReactHealthParseResult:
    """Structured parse output from a ReactHealth Sleep Therapy PDF."""

    report_metadata: Dict[str, Any]
    daily_rows: List[Dict[str, Any]]
    no_data_dates: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def parse_mmddyy(raw: str) -> str:
    """Convert MM/DD/YY or MM/DD/YYYY into ISO YYYY-MM-DD."""
    parts = raw.strip().split("/")
    if len(parts) != 3:
        raise ValueError(f"Invalid MM/DD/YY date: {raw!r}")
    month, day, year = int(parts[0]), int(parts[1]), int(parts[2])
    if year < 100:
        year += 2000
    return date(year, month, day).isoformat()


def parse_hhmm_duration(raw: str) -> Tuple[int, float]:
    """Convert HH:MM usage duration (not clock time!) into (usage_minutes, usage_hours)."""
    parts = raw.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM duration: {raw!r}")
    hours, mins = int(parts[0]), int(parts[1])
    total_minutes = hours * 60 + mins
    return total_minutes, round(total_minutes / 60.0, 4)


def extract_pages_text_from_pdf_bytes(pdf_bytes: bytes) -> List[str]:
    """Extract per-page text from a PDF using pdfplumber."""
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pdfplumber is required to parse ReactHealth PDF files."
        ) from exc

    pages: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text(layout=False) or "")
    return pages


def parse_reacthealth_pages(
    pages_text: List[str],
    source_file: str,
    run_id: str,
    ingested_at_iso: str,
    pdf_bytes: Optional[bytes] = None,
) -> ReactHealthParseResult:
    """
    Parse ReactHealth Page 1 metadata and Pages 2..N daily therapy rows from extracted page texts.

    CRITICAL rules enforced:
    - Date MM/DD/YY -> ISO DATE
    - Time HH:MM is usage duration -> usage_minutes (INT64) + usage_hours (FLOAT64)
    - 'No data received' rows are skipped from daily_rows (counted in report metadata)
    - '00:00' rows are preserved as 0-minute therapy records
    """
    if not pages_text:
        raise ValueError("PDF contains no extractable pages.")

    page1 = pages_text[0]
    warnings: List[str] = []

    date_range_m = DATE_RANGE_RE.search(page1)
    report_gen_m = REPORT_GEN_RE.search(page1)
    usage_days_m = USAGE_DAYS_RE.search(page1)
    days_ge_4h_m = DAYS_GE_4H_RE.search(page1)
    best30_m = BEST_30_RE.search(page1)
    patient_m = PATIENT_NAME_RE.search(page1)
    avg_pressure_m = AVG_PRESSURE_RE.search(page1)
    avg_p95_m = AVG_P95_RE.search(page1)
    avg_leak_m = AVG_LEAK_RE.search(page1)
    avg_ahi_m = AVG_AHI_RE.search(page1)
    avg_cai_m = AVG_CAI_RE.search(page1)

    report_generated_date = (
        parse_mmddyy(report_gen_m.group(1)) if report_gen_m else None
    )
    range_start = parse_mmddyy(date_range_m.group(1)) if date_range_m else None
    range_end = parse_mmddyy(date_range_m.group(2)) if date_range_m else None

    if not report_generated_date:
        warnings.append("Could not detect 'Report generated on' date on Page 1.")

    daily_rows: List[Dict[str, Any]] = []
    no_data_dates: List[str] = []
    device_sns: List[str] = []
    zero_minute_days = 0

    for page_idx, text in enumerate(pages_text):
        # Page 1 may also contain rows in some formats; scan Pages 2..N and tolerate Page 1 if no header clash
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for ln in lines:
            no_data_m = NO_DATA_ROW_RE.match(ln)
            if no_data_m:
                no_data_dates.append(parse_mmddyy(no_data_m.group(1)))
                continue

            row_m = VALID_ROW_RE.match(ln)
            if not row_m:
                # Fallback whitespace-tokenized check in case mode has spaces (e.g. "Auto CPAP")
                parsed_fallback = _parse_flexible_daily_line(ln)
                if parsed_fallback is None:
                    continue
                (
                    raw_date,
                    raw_dur,
                    pressure_s,
                    ahi_s,
                    p95_s,
                    cai_s,
                    leak_s,
                    mode,
                    device_sn,
                ) = parsed_fallback
            else:
                (
                    raw_date,
                    raw_dur,
                    pressure_s,
                    ahi_s,
                    p95_s,
                    cai_s,
                    leak_s,
                    mode,
                    device_sn,
                ) = row_m.groups()

            usage_date = parse_mmddyy(raw_date)
            usage_minutes, usage_hours = parse_hhmm_duration(raw_dur)
            if usage_minutes == 0:
                zero_minute_days += 1
            device_sns.append(device_sn)

            row_payload = {
                "usage_date": usage_date,
                "device_sn": device_sn,
                "usage_duration_str": raw_dur,
                "usage_minutes": usage_minutes,
                "usage_hours": usage_hours,
                "pressure": float(pressure_s),
                "ahi": float(ahi_s),
                "p95": float(p95_s),
                "cai": float(cai_s),
                "avg_leak": float(leak_s),
                "mode": mode,
                "report_generated_date": report_generated_date or usage_date,
                "_ingested_at": ingested_at_iso,
                "_source_file": source_file,
                "_run_id": run_id,
            }
            row_payload["_row_hash"] = hashlib.sha256(
                f"{usage_date}|{device_sn}|{usage_minutes}|{ahi_s}|{p95_s}".encode("utf-8")
            ).hexdigest()
            daily_rows.append(row_payload)

        if page_idx == 0 and not daily_rows:
            # Expected: Page 1 is summary metadata
            pass

    primary_sn = device_sns[0] if device_sns else _extract_sn_from_text(page1)
    if pdf_bytes is not None:
        report_id = hashlib.sha256(pdf_bytes).hexdigest()[:24]
    else:
        report_id = hashlib.sha256(
            f"{primary_sn}|{range_start}|{range_end}|{report_generated_date}".encode("utf-8")
        ).hexdigest()[:24]

    report_metadata: Dict[str, Any] = {
        "report_id": report_id,
        "device_sn": primary_sn,
        "report_generated_date": report_generated_date,
        "report_date_range_start": range_start,
        "report_date_range_end": range_end,
        "usage_days": int(usage_days_m.group(1)) if usage_days_m else None,
        "total_days": int(usage_days_m.group(2)) if usage_days_m else None,
        "adherence_pct": float(usage_days_m.group(3)) if usage_days_m else None,
        "days_ge_4h": int(days_ge_4h_m.group(1)) if days_ge_4h_m else None,
        "best30_start": parse_mmddyy(best30_m.group(1)) if best30_m else None,
        "best30_end": parse_mmddyy(best30_m.group(2)) if best30_m else None,
        "best30_days": int(best30_m.group(3)) if best30_m else None,
        "best30_total_days": int(best30_m.group(4)) if best30_m else None,
        "best30_pct": float(best30_m.group(5)) if best30_m else None,
        "avg_pressure": float(avg_pressure_m.group(1)) if avg_pressure_m else None,
        "avg_p95": float(avg_p95_m.group(1)) if avg_p95_m else None,
        "avg_leak": float(avg_leak_m.group(1)) if avg_leak_m else None,
        "avg_ahi": float(avg_ahi_m.group(1)) if avg_ahi_m else None,
        "avg_cai": float(avg_cai_m.group(1)) if avg_cai_m else None,
        "valid_days_count": len(daily_rows),
        "no_data_days_count": len(no_data_dates),
        "zero_minute_days_count": zero_minute_days,
        "patient_name": patient_m.group(1).strip() if patient_m else None,
        "_ingested_at": ingested_at_iso,
        "_source_file": source_file,
        "_run_id": run_id,
        "_row_hash": report_id,
    }

    return ReactHealthParseResult(
        report_metadata=report_metadata,
        daily_rows=daily_rows,
        no_data_dates=no_data_dates,
        warnings=warnings,
    )


def parse_reacthealth_pdf_bytes(
    pdf_bytes: bytes,
    source_file: str,
    run_id: str,
    ingested_at_iso: str,
) -> ReactHealthParseResult:
    """Parse ReactHealth PDF bytes directly."""
    pages_text = extract_pages_text_from_pdf_bytes(pdf_bytes)
    return parse_reacthealth_pages(
        pages_text=pages_text,
        source_file=source_file,
        run_id=run_id,
        ingested_at_iso=ingested_at_iso,
        pdf_bytes=pdf_bytes,
    )


def _parse_flexible_daily_line(
    line: str,
) -> Optional[Tuple[str, str, str, str, str, str, str, str, str]]:
    """Handle rows where Mode contains spaces (e.g., 'Auto CPAP' instead of 'Auto-CPAP')."""
    tokens = line.split()
    if len(tokens) < 9:
        return None
    if not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", tokens[0]):
        return None
    if not re.match(r"^\d{1,2}:\d{2}$", tokens[1]):
        return None
    for idx in range(2, 7):
        if not re.match(r"^\d+(?:\.\d+)?$", tokens[idx]):
            return None
    device_sn = tokens[-1]
    mode = " ".join(tokens[7:-1])
    if not mode or not re.match(r"^[A-Za-z0-9_-]{4,}$", device_sn):
        return None
    return (
        tokens[0],
        tokens[1],
        tokens[2],
        tokens[3],
        tokens[4],
        tokens[5],
        tokens[6],
        mode,
        device_sn,
    )


def _extract_sn_from_text(text: str) -> Optional[str]:
    m = re.search(r"Device\s*SN\s*:?\s*([A-Za-z0-9_-]{5,})", text, re.IGNORECASE)
    return m.group(1) if m else None
