"""
Public feature flags (backend side). Off means the endpoint returns 404 and
nothing is generated; the data and code are kept.

BRIEFING_PUBLIC — Daily Briefing. On from 4 Oct 2026 by the owner's decision,
after counsel's launch fixes 1-6 were built and tested.
"""
BRIEFING_PUBLIC = True
