# utils/date_helpers.py

from datetime import datetime, timedelta

def format_date(tally_date_str: str) -> str:
    """Formats Tally Date (YYYYMMDD) to ISO format (YYYY-MM-DD)."""
    if not tally_date_str:
        return ""
    t_str = tally_date_str.strip()
    if len(t_str) == 8:
        return f"{t_str[:4]}-{t_str[4:6]}-{t_str[6:8]}"
    return t_str

def calculate_due_date(date_str: str, due_days: int) -> str:
    """Adds due_days to date_str (YYYY-MM-DD) and returns YYYY-MM-DD."""
    if not date_str:
        return ""
    if due_days <= 0:
        return date_str
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return (dt + timedelta(days=due_days)).strftime("%Y-%m-%d")
    except Exception:
        return date_str


def _dmy_to_date(dmy: str) -> datetime:
    """Parse D-M-YYYY string (e.g. '1-4-2016') into a datetime object."""
    parts = dmy.strip().split("-")
    return datetime(int(parts[2]), int(parts[1]), int(parts[0]))


def _date_to_dmy(dt: datetime) -> str:
    """Format datetime into D-M-YYYY string (e.g. '31-3-2017')."""
    return f"{dt.day}-{dt.month}-{dt.year}"


def get_fy_batches(f_date: str, t_date: str) -> list:
    """
    Split a full date range (D-M-YYYY format) into Indian financial year
    windows of April 1 → March 31.

    This prevents Tally from timing out on large all-history queries by
    sending one financial year per request and combining the results.

    Returns list of (batch_from, batch_to) tuples in D-M-YYYY format.

    Example:
        get_fy_batches('1-4-2016', '2-2-2026')
        → [('1-4-2016','31-3-2017'), ('1-4-2017','31-3-2018'), ..., ('1-4-2025','2-2-2026')]
    """
    start = _dmy_to_date(f_date)
    end   = _dmy_to_date(t_date)

    batches = []
    current = start

    while current <= end:
        # Determine the end of this financial year (March 31)
        if current.month >= 4:
            fy_end = datetime(current.year + 1, 3, 31)
        else:
            fy_end = datetime(current.year, 3, 31)

        batch_end = min(fy_end, end)
        batches.append((_date_to_dmy(current), _date_to_dmy(batch_end)))

        # Move to April 1 of next FY
        next_fy_start = datetime(fy_end.year, 4, 1)
        if next_fy_start > end:
            break
        current = next_fy_start

    return batches

