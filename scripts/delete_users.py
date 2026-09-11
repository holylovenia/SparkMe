#!/usr/bin/env python
"""
Delete users and every trace of their data.

Given a list of user hashes (the keys in users.json) and/or usernames, this
removes:

    <DATA_DIR>/<country_slug>/<user_id>/     (user_sessions.json, user_stats.json,
                                              survey.json, ...)
    <LOGS_DIR>/<country_slug>/<user_id>/     (execution_logs, ratings, statistics,
                                              evaluations, ...)
    <DATA_DIR>/<user_id>/                    legacy pre-country layout, if present
    <LOGS_DIR>/<user_id>/                    legacy pre-country layout, if present
    <ANNOTATIONS_DIR>/<user_id>/             annotations the user *made*
    <ANNOTATIONS_DIR>/*/<user_id>_*.json     annotations *about* the user's sessions
    the user's entry in <DATA_DIR>/users.json

Both roots are scanned with a glob rather than resolved through
users.json -> country, so folders survive a country change, a stale
'unknown/' bucket, or a users.json entry that is already gone.

Dry run by default. Nothing is touched until you pass --apply.

Usage
-----
    # preview (reads .env for DATA_DIR / LOGS_DIR)
    python scripts/delete_users.py alice mkcrTvehXXJapJoGv11nQA

    # from a file, one identifier per line, '#' comments allowed
    python scripts/delete_users.py --from-file to_delete.txt

    # actually delete, keeping a copy under data/_deleted_users/<timestamp>/
    python scripts/delete_users.py --from-file to_delete.txt --apply --archive

    # actually delete, no copy kept
    python scripts/delete_users.py alice --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()            # picks up DATA_DIR / LOGS_DIR, e.g. data/data and data/logs
except ImportError:
    pass


# =============================================================================
# LOADING / RESOLVING
# =============================================================================

def load_users(users_file: Path) -> dict:
    if not users_file.exists():
        raise FileNotFoundError(f"Could not find {users_file}")
    with open(users_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_identifiers(args) -> list:
    """Collect identifiers from the command line and/or a file, order-preserving."""
    idents = list(args.identifiers)

    if args.from_file:
        with open(args.from_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if line:
                    idents.append(line)

    seen, unique = set(), []
    for i in idents:
        if i not in seen:
            seen.add(i)
            unique.append(i)
    return unique


def resolve(users: dict, identifiers: list):
    """Map each identifier to a user_id.

    An identifier matches a users.json key (the hash) first, then a username.
    Returns (resolved, ambiguous, unmatched):
      resolved  : {user_id: identifier_as_given}
      ambiguous : {username: [user_id, ...]}   duplicate usernames — refuse to guess
      unmatched : [identifier, ...]            no users.json entry (may still be an
                                               orphaned folder, checked later)
    """
    by_username = {}
    for uid, info in users.items():
        by_username.setdefault((info or {}).get('username'), []).append(uid)

    resolved, ambiguous, unmatched = {}, {}, []
    for ident in identifiers:
        if ident in users:
            resolved[ident] = ident
            continue
        matches = by_username.get(ident, [])
        if len(matches) == 1:
            resolved[matches[0]] = ident
        elif len(matches) > 1:
            ambiguous[ident] = matches
        else:
            unmatched.append(ident)
    return resolved, ambiguous, unmatched


# =============================================================================
# PATH COLLECTION
# =============================================================================

def is_safe_user_id(user_id: str) -> bool:
    """Reject anything that could escape a root or match too much."""
    if not user_id or user_id in ('.', '..', '*'):
        return False
    return not any(c in user_id for c in ('/', '\\', os.sep))


def user_dirs_in(root: Path, user_id: str) -> list:
    """<root>/<user_id> and <root>/<country>/<user_id>, whichever exist.

    Only descends one level: the country segment. Anything deeper belongs to a
    session, not a second user folder.
    """
    if not root.is_dir():
        return []

    found = []
    direct = root / user_id
    if direct.is_dir():
        found.append(direct)

    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name == user_id:
            continue
        nested = child / user_id
        if nested.is_dir():
            found.append(nested)

    return found


def annotation_paths(ann_root: Path, user_id: str) -> list:
    """Annotations made by the user, plus annotations others made about them."""
    if not ann_root.is_dir():
        return []

    found = []
    own = ann_root / user_id
    if own.is_dir():
        found.append(own)

    # scripts/annotations/app.py names these "{user_id}_{session_id}.json"
    for annotator_dir in sorted(ann_root.iterdir()):
        if not annotator_dir.is_dir() or annotator_dir.name == user_id:
            continue
        found.extend(sorted(annotator_dir.glob(f"{user_id}_*.json")))

    return found


def collect(user_id: str, roots: list, ann_root: Path,
            keep_annotations: bool) -> list:
    """Every path on disk belonging to this user."""
    paths = []
    for root in roots:
        paths.extend(user_dirs_in(root, user_id))
    if not keep_annotations:
        paths.extend(annotation_paths(ann_root, user_id))
    return paths


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


def human(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.0f}B" if unit == 'B' else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


# =============================================================================
# DELETION
# =============================================================================

def remove_path(path: Path, archive_root: Path | None, base: Path) -> None:
    """Delete, or move under archive_root preserving the relative layout."""
    if archive_root is None:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return

    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        rel = Path(path.name)

    dest = archive_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name(f"{dest.name}.{int(time.time() * 1000)}")
    shutil.move(str(path), str(dest))


def write_users_json(users_file: Path, users: dict) -> None:
    """Temp file + os.replace, with a unique temp name so a concurrent writer
    in the running app can't collide with us."""
    tmp = users_file.with_name(f"{users_file.name}.{os.getpid()}.{int(time.time() * 1000)}.tmp")
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, users_file)


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('identifiers', nargs='*',
                        help="User hashes (users.json keys) and/or usernames")
    parser.add_argument('--from-file',
                        help="File with one identifier per line ('#' comments allowed)")
    parser.add_argument('--data-dir', default=os.getenv('DATA_DIR', 'data'))
    parser.add_argument('--logs-dir', default=os.getenv('LOGS_DIR', 'logs'))
    parser.add_argument('--annotations-dir', default=os.getenv('ANNOTATIONS_DIR'),
                        help="Defaults to <parent of DATA_DIR>/annotations")
    parser.add_argument('--extra-root', action='append', default=[],
                        help="Additional root holding per-user folders, e.g. "
                             "data/final_logs. Repeatable.")
    parser.add_argument('--keep-annotations', action='store_true',
                        help="Leave annotation files alone")
    parser.add_argument('--keep-users-entry', action='store_true',
                        help="Delete the folders but leave users.json untouched "
                             "(the account can still log in)")
    parser.add_argument('--archive', action='store_true',
                        help="Move everything into <DATA_DIR>/../_deleted_users/"
                             "<timestamp>/ instead of deleting outright")
    parser.add_argument('--apply', action='store_true',
                        help="Actually make the changes. Without this, dry run.")
    parser.add_argument('--yes', action='store_true',
                        help="Skip the confirmation prompt (for --apply)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    logs_dir = Path(args.logs_dir)
    users_file = data_dir / 'users.json'
    ann_root = Path(args.annotations_dir) if args.annotations_dir \
        else data_dir.parent / 'annotations'

    roots = [data_dir, logs_dir] + [Path(p) for p in args.extra_root]
    for extra in ('final_logs',):
        candidate = data_dir.parent / extra
        if candidate.is_dir() and candidate not in roots:
            roots.append(candidate)

    identifiers = read_identifiers(args)
    if not identifiers:
        parser.error("No identifiers given. Pass them as arguments or via --from-file.")

    users = load_users(users_file)
    print(f"Loaded {len(users)} users from {users_file}\n")

    resolved, ambiguous, unmatched = resolve(users, identifiers)

    if ambiguous:
        for username, uids in ambiguous.items():
            print(f"ERROR: username {username!r} maps to {len(uids)} user ids: "
                  f"{', '.join(uids)}")
        print("\nPass the specific hash instead. Nothing was changed.")
        return 2

    # An identifier with no users.json entry may still have orphaned folders.
    orphans = {}
    for ident in unmatched:
        if not is_safe_user_id(ident):
            print(f"ERROR: refusing to treat {ident!r} as a user id (unsafe path)")
            return 2
        if any(collect(ident, roots, ann_root, args.keep_annotations)):
            orphans[ident] = ident
            print(f"NOTE: {ident} has no users.json entry but does have folders on "
                  f"disk — treating it as an orphaned user id.")
        else:
            print(f"SKIP: {ident} — no users.json entry and nothing on disk.")

    targets = {**resolved, **orphans}
    if not targets:
        print("\nNothing to do.")
        return 1

    print()

    # --- plan ---------------------------------------------------------------
    plan, total_bytes, total_paths = {}, 0, 0
    for user_id, ident in targets.items():
        if not is_safe_user_id(user_id):
            print(f"ERROR: refusing to act on user id {user_id!r} (unsafe path)")
            return 2

        paths = collect(user_id, roots, ann_root, args.keep_annotations)
        plan[user_id] = paths

        username = (users.get(user_id) or {}).get('username', '<not in users.json>')
        country = (users.get(user_id) or {}).get('country', '?')
        label = f"{user_id}  (username={username}, country={country})"
        if ident != user_id:
            label += f"  [matched by {ident!r}]"
        print(label)

        if not paths:
            print("    (no files on disk)")
        for p in paths:
            size = dir_size(p)
            total_bytes += size
            total_paths += 1
            kind = 'dir ' if p.is_dir() else 'file'
            print(f"    {kind} {p}   {human(size)}")

        if user_id in users and not args.keep_users_entry:
            print(f"    entry users.json[{user_id}]")
        print()

    print(f"{len(plan)} user(s), {total_paths} path(s), {human(total_bytes)} total.")

    if not args.apply:
        print("\nDry run — nothing was changed. Re-run with --apply to delete.")
        return 0

    # --- confirm ------------------------------------------------------------
    archive_root = None
    if args.archive:
        stamp = time.strftime('%Y%m%d_%H%M%S')
        archive_root = data_dir.parent / '_deleted_users' / stamp
        print(f"\nArchiving into {archive_root}")

    if not args.yes:
        verb = 'archive' if args.archive else 'permanently delete'
        answer = input(f"\nType 'yes' to {verb} the above: ").strip().lower()
        if answer != 'yes':
            print("Aborted. Nothing was changed.")
            return 1

    # --- back up users.json before touching it ------------------------------
    if not args.keep_users_entry and any(uid in users for uid in plan):
        backup = users_file.with_name(
            f"users.json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(users_file, backup)
        print(f"\nBacked up users.json -> {backup}")

    # --- execute ------------------------------------------------------------
    failures = []
    for user_id, paths in plan.items():
        for p in paths:
            try:
                remove_path(p, archive_root, data_dir.parent)
                print(f"  removed {p}")
            except OSError as e:
                failures.append((p, e))
                print(f"  FAILED  {p}: {e}")

    if not args.keep_users_entry:
        # Re-read: the app may have registered someone since we loaded.
        current = load_users(users_file)
        removed = [uid for uid in plan if current.pop(uid, None) is not None]
        if removed:
            write_users_json(users_file, current)
            for uid in removed:
                print(f"  removed users.json[{uid}]")

    if failures:
        print(f"\nDone with {len(failures)} failure(s) — see above.")
        return 1

    print("\nDone.")
    if not args.archive:
        print("Note: sessions already in memory in a running app are not "
              "affected. Restart the app if a deleted user has a live session.")
    return 0


if __name__ == '__main__':
    sys.exit(main())