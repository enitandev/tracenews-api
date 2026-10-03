"""
Public feature flags (backend side). Off means the endpoint returns 404 and
nothing is generated; the data and code are kept.

BRIEFING_PUBLIC — Daily Briefing. Off until the rebuild (counsel's
consolidated instruction, 3 Oct 2026, section B) is cleared by counsel.
"""
BRIEFING_PUBLIC = False
