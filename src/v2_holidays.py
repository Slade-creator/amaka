"""
Zambian public-holiday calendar for 2024-2025.

Sources: Public Holidays Act (Zambia); national holiday lists. The generator and
the feature pipeline both call this module so the target effect and the
categorical feature cannot drift apart.

Notes for the prototype period:
  * Easter weekend is four public holidays (Good Friday, Holy Saturday, Easter
    Sunday, Easter Monday).
  * Heroes' Day is the first Monday in July; Unity Day is the following day.
  * Farmers' Day is the first Monday in August.
  * National Day of Prayer and Christian Heritage was observed on 18 October in
    2024/2025; it moved to 29 December in 2026 (outside this dataset).
  * If a holiday falls on a Sunday, the following Monday is observed.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from dateutil.easter import easter


def _first_monday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(7 - d.weekday()) % 7)


def zambian_holidays(year: int) -> set[date]:
    """Return all observed public holidays for a Zambian calendar year."""
    holidays: set[date] = {
        date(year, 1, 1),          # New Year's Day
        date(year, 3, 8),          # International Women's Day
        date(year, 3, 12),         # Youth Day
        date(year, 4, 28),         # Kenneth Kaunda Day
        date(year, 5, 1),          # Labour Day
        date(year, 5, 25),         # Africa Freedom Day
        date(year, 10, 18),        # National Day of Prayer (2024/2025)
        date(year, 10, 24),        # Independence Day
        date(year, 12, 25),        # Christmas Day
    }

    easter_sunday = easter(year)
    holidays.update({
        easter_sunday - timedelta(days=2),  # Good Friday
        easter_sunday - timedelta(days=1),  # Holy Saturday
        easter_sunday,                      # Easter Sunday
        easter_sunday + timedelta(days=1),  # Easter Monday
    })

    heroes = _first_monday(year, 7)
    holidays.add(heroes)                    # Heroes' Day
    holidays.add(heroes + timedelta(days=1))  # Unity Day
    holidays.add(_first_monday(year, 8))    # Farmers' Day

    # If a public holiday falls on a Sunday, the following Monday is observed.
    observed = {d + timedelta(days=1) for d in holidays if d.weekday() == 6}
    return holidays | observed


def holiday_set(start_year: int = 2024, end_year: int = 2025) -> set[date]:
    out: set[date] = set()
    for year in range(start_year, end_year + 1):
        out |= zambian_holidays(year)
    return out


def holiday_mask(index: pd.DatetimeIndex, start_year: int = 2024, end_year: int = 2025) -> np.ndarray:
    """Boolean mask aligned to a DatetimeIndex."""
    holidays = holiday_set(start_year, end_year)
    return np.fromiter(
        (ts.date() in holidays for ts in index),
        dtype=bool,
        count=len(index),
    )


if __name__ == "__main__":
    for year in (2024, 2025):
        days = sorted(zambian_holidays(year))
        print(f"{year}: {len(days)} observed holidays")
        for d in days:
            print(f"  {d.isoformat()} {d.strftime('%A')}")
