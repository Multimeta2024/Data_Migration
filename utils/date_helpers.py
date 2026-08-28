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


def get_fy_short(date_str: str) -> str:
    """Given an ISO date string (YYYY-MM-DD), returns FY short string like '1718'."""
    if not date_str or len(date_str) < 7:
        return ""
    try:
        parts = date_str.split("-")
        year = int(parts[0])
        month = int(parts[1])
        if month >= 4:
            s_year = year % 100
            e_year = (year + 1) % 100
        else:
            s_year = (year - 1) % 100
            e_year = year % 100
        return f"{s_year:02d}{e_year:02d}"
    except Exception:
        return ""



def _dmy_to_date(dmy: str) -> datetime:
    """Parse D-M-YYYY string (e.g. '1-4-2016') into a datetime object."""
    parts = dmy.strip().split("-")
    return datetime(int(parts[2]), int(parts[1]), int(parts[0]))


def _date_to_dmy(dt: datetime) -> str:
    """Format datetime into D-M-YYYY string (e.g. '31-3-2017')."""
    return f"{dt.day}-{dt.month}-{dt.year}"


def get_fy_batches(f_date: str, t_date: str) -> list:
    """
    Split a full date range (D-M-YYYY format) into 6-month half-year
    windows (April 1 → Sept 30, Oct 1 → March 31).

    This prevents Tally from timing out on large queries by
    sending smaller date range requests and combining the results.
    """
    start = _dmy_to_date(f_date)
    end   = _dmy_to_date(t_date)

    batches = []
    current = start

    while current <= end:
        if current.month >= 4 and current.month <= 9:
            chunk_end = datetime(current.year, 9, 30)
        elif current.month >= 10:
            chunk_end = datetime(current.year + 1, 3, 31)
        else:
            chunk_end = datetime(current.year, 3, 31)

        batch_end = min(chunk_end, end)
        batches.append((_date_to_dmy(current), _date_to_dmy(batch_end)))

        current = batch_end + timedelta(days=1)

    return batches

