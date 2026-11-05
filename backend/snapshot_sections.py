"""Shared section freshness for HTTP and assistant resource views."""
import math


def section_views(snapshot, now, max_age):
    result = {}
    for name, section in snapshot.get('sections', {}).items():
        stamp = section.get('collected_at')
        fresh = (section.get('status') == 'known' and type(stamp) in (int, float)
                 and math.isfinite(stamp) and 0 <= now-stamp <= max_age)
        result[name] = dict(section, fresh=fresh)
    return result
