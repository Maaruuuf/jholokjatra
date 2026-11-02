"""Cross-session user preferences (SQLite)."""
from ..db import db
from ..schemas import Preferences


def load_prefs(user_id: str) -> Preferences:
    with db() as c:
        row = c.execute("SELECT data FROM preferences WHERE user_id=?", (user_id,)).fetchone()
    return Preferences.model_validate_json(row["data"]) if row else Preferences()


def save_prefs(user_id: str, prefs: Preferences) -> Preferences:
    with db() as c:
        c.execute("INSERT OR REPLACE INTO preferences(user_id,data) VALUES (?,?)", (user_id, prefs.model_dump_json()))
    return prefs
