"""Central helpers for resolving per-user, per-country data/logs directories.

Every user-owned file used to live directly under DATA_DIR/<user_id> or
LOGS_DIR/<user_id>. To keep annotation data organized by country, these now
live one level deeper:

    data/<country_slug>/<user_id>/...
    logs/<country_slug>/<user_id>/...

`users.json` stays at the DATA_DIR root — it's the registry that maps every
user_id to a country, so it can't itself live inside a per-country folder.

Every module that needs a per-user path should go through user_data_dir() /
user_logs_dir() instead of joining DATA_DIR/LOGS_DIR with user_id directly,
so the country segment stays consistent everywhere.
"""
import json
import os
import re


def country_slug(country: str) -> str:
    """Turn a country name into a filesystem-safe, lowercase folder name.

    e.g. 'UAE' -> 'uae', 'Saudi Arabia' -> 'saudi_arabia'
    """
    if not country:
        return "unknown"
    slug = re.sub(r"[^\w\-]+", "_", country.strip().lower())
    return slug.strip("_") or "unknown"


def get_user_country(user_id: str) -> str:
    """Look up the country a user registered with, via data/users.json.

    Returns 'unknown' if the user can't be found (e.g. called before
    users.json has been written for a brand-new registration — callers in
    that situation should pass country= explicitly instead of relying on
    this lookup).
    """
    users_file = os.path.join(os.getenv('DATA_DIR', 'data'), 'users.json')
    if os.path.exists(users_file):
        try:
            with open(users_file, 'r', encoding='utf-8') as f:
                users = json.load(f)
            country = users.get(user_id, {}).get('country')
            if country:
                return country
        except Exception:
            pass
    return 'unknown'


def user_data_dir(user_id: str, country: str = None) -> str:
    """Return data/<country>/<user_id>. Pass country= when already known
    (e.g. during registration) to avoid re-reading users.json."""
    country = country or get_user_country(user_id)
    return os.path.join(os.getenv('DATA_DIR', 'data'), country_slug(country), user_id)


def user_logs_dir(user_id: str, country: str = None) -> str:
    """Return logs/<country>/<user_id>. Pass country= when already known
    to avoid re-reading users.json."""
    country = country or get_user_country(user_id)
    return os.path.join(os.getenv('LOGS_DIR', 'logs'), country_slug(country), user_id)