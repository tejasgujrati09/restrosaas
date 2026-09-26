"""Per-outlet settings, not global flags (docs/CLAUDE.md §5.9). Values live on
`Outlet` columns; this module is just the defaults applied when a new
`Outlet` row is created, so the default lives in exactly one place.
"""

from __future__ import annotations

DEFAULT_ACK_THRESHOLD_PAISE = 50_000  # ₹500, docs/SPEC.md §3/§7.3
DEFAULT_WAITER_CONFIRM_MODE = False
DEFAULT_LIQUOR_APPROVAL_REQUIRED = False
DEFAULT_PRICES_INCLUDE_TAX = True  # docs/DECISIONS.md "Tax storage"
DEFAULT_EXPECTED_PREP_MINUTES = 10  # owner or manager can change it; the yardstick for "delayed"
DEFAULT_AUTO_ASSIGN = False  # a manager assigns unassigned tables unless the outlet opts in
DEFAULT_AUTO_ASSIGNMENT_STRATEGY = "least_loaded"
