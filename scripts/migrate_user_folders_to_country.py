#!/usr/bin/env python
"""
One-off migration: move existing flat data/<user_id> and logs/<user_id>
folders into a per-country subfolder, matching the new layout:

    data/<user_id>/...   ->  data/<country_slug>/<user_id>/...
    logs/<user_id>/...   ->  logs/<country_slug>/<user_id>/...
...
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv       # noqa: E402
load_dotenv()                        # picks up DATA_DIR / LOGS_DIR from .env, e.g. data/data and data/logs

from src.utils.user_paths import country_slug  # noqa: E402


def load_users(data_dir: str) -> dict:
    users_file = os.path.join(data_dir, 'users.json')
    if not os.path.exists(users_file):
        raise FileNotFoundError(f"Could not find {users_file}")
    with open(users_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def migrate_root(root: str, users: dict, label: str,
                  dry_run: bool, skip_unknown: bool) -> None:
    if not os.path.isdir(root):
        print(f"[{label}] {root} does not exist, skipping.")
        return

    known_slugs = {country_slug(u.get('country')) for u in users.values()}

    for entry in sorted(os.listdir(root)):
        entry_path = os.path.join(root, entry)
        if not os.path.isdir(entry_path):
            continue                      # leave files (users.json, flask_app.log) alone
        if entry in known_slugs:
            continue                      # already a country folder (e.g. prior run)

        user_id = entry
        country = users.get(user_id, {}).get('country')

        if country:
            slug = country_slug(country)
        elif skip_unknown:
            print(f"[{label}] SKIP {user_id}: not found in users.json")
            continue
        else:
            slug = 'unknown'
            print(f"[{label}] WARN {user_id}: not found in users.json, filing under '{slug}/'")

        dest_dir  = os.path.join(root, slug)
        dest_path = os.path.join(dest_dir, user_id)

        if os.path.exists(dest_path):
            print(f"[{label}] SKIP {user_id}: destination already exists ({dest_path})")
            continue

        print(f"[{label}] {entry_path}  ->  {dest_path}")
        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(entry_path, dest_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=os.getenv('DATA_DIR', 'data'))
    parser.add_argument('--logs-dir', default=os.getenv('LOGS_DIR', 'logs'))
    parser.add_argument('--dry-run', action='store_true',
                         help="Print what would move without moving anything")
    parser.add_argument('--skip-unknown', action='store_true',
                         help="Leave folders with no users.json entry untouched "
                              "instead of filing them under 'unknown/'")
    args = parser.parse_args()

    users = load_users(args.data_dir)
    print(f"Loaded {len(users)} users from {args.data_dir}/users.json")

    migrate_root(args.data_dir, users, 'data', args.dry_run, args.skip_unknown)
    migrate_root(args.logs_dir, users, 'logs', args.dry_run, args.skip_unknown)

    if args.dry_run:
        print("\nDry run only — nothing was moved. Re-run without --dry-run to apply.")


if __name__ == '__main__':
    main()