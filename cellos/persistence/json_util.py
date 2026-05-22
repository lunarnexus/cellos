"""JSON serialization utilities with datetime support."""

import datetime
import json


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""

    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        return super().default(o)


def dumps(obj):
    """Serialize obj to JSON with datetime support."""
    return json.dumps(obj, cls=DateTimeEncoder)
