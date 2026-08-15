#!/usr/bin/env python3
"""Remove consecutive duplicate turns from existing ratings CSVs.

Backfill for the duplicate-row bug: several delivery paths could record the
same logical turn twice, each time with a fresh `message_id`, so the only
thing that identifies a duplicate is the content. Turns strictly alternate
User -> Interviewer, so any row whose `liked_response` repeats the previous
row's is a duplicate.

Walks  <root>/<country_slug>/<user_hash>/ratings/*.csv  and rewrites each file
in place, keeping the FIRST row of every consecutive identical run.

Usage:
    python scripts/dedup_ratings_csv.py --root data/logs --dry-run
    python scripts/dedup_ratings_csv.py --root data/logs
    python scripts/dedup_ratings_csv.py --root data/logs --no-backup
"""

import argparse
import csv
import glob
import os
import shutil
import sys

# Fields can be long (full model responses with embedded newlines).
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# Must match the dialect save_rating_to_csv() writes with, so untouched rows
# round-trip byte-for-byte instead of having their backslashes re-escaped.
DIALECT = dict(quoting=csv.QUOTE_ALL, escapechar='\\')


def dedup_rows(rows, keep='first'):
    """Collapse runs of rows sharing the same `liked_response` to one row.

    `keep` selects which row of each run survives. They differ: a duplicated
    model turn has one row whose `message_id` belongs to the same option set
    as its `rejected_option_message_ids`, and one whose doesn't (the stale
    rating form). Only the matching row has a trustworthy `liked_model`.

    `rows` is a list of lists, header included. Returns (kept_rows, dropped).
    """
    if not rows:
        return rows, []

    header = rows[0]
    try:
        col = header.index('liked_response')
    except ValueError:
        raise ValueError("no 'liked_response' column")

    kept, dropped, previous = [header], [], None
    for row in rows[1:]:
        current = row[col] if col < len(row) else ''
        if current and current == previous:
            if keep == 'last':
                dropped.append(kept[-1])
                kept[-1] = row
            else:
                dropped.append(row)
            continue
        kept.append(row)
        previous = current

    return kept, dropped


def process_file(path, dry_run=False, backup=True, keep='first'):
    """Dedup one CSV in place. Returns the number of rows removed."""
    with open(path, 'r', newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f, escapechar='\\'))

    kept, dropped = dedup_rows(rows, keep=keep)
    if not dropped:
        return 0

    if not dry_run:
        if backup:
            shutil.copy2(path, path + '.bak')

        tmp = path + '.tmp'
        with open(tmp, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f, **DIALECT).writerows(kept)
        os.replace(tmp, path)      # atomic: never leave a half-written CSV

    return len(dropped)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', default=os.getenv('LOGS_DIR', 'data/logs'),
                        help='logs root containing <country_slug>/<user_hash>/ratings/ '
                             '(default: $LOGS_DIR or data/logs)')
    parser.add_argument('--dry-run', action='store_true',
                        help='report what would change without writing')
    parser.add_argument('--no-backup', action='store_true',
                        help='skip writing a .bak alongside each modified file')
    parser.add_argument('--keep', choices=('first', 'last'), default='first',
                        help='which row of each duplicate run to keep (default: first)')
    args = parser.parse_args()

    pattern = os.path.join(args.root, '*', '*', 'ratings', '*.csv')
    paths = sorted(p for p in glob.glob(pattern) if not p.endswith('.bak'))

    if not paths:
        print(f"No ratings CSVs found under {pattern}")
        return 0

    total_removed = files_changed = failures = 0
    for path in paths:
        try:
            removed = process_file(path, dry_run=args.dry_run,
                                   backup=not args.no_backup, keep=args.keep)
        except Exception as e:
            print(f"  SKIPPED {path}: {e}")
            failures += 1
            continue

        if removed:
            files_changed += 1
            total_removed += removed
            verb = 'would remove' if args.dry_run else 'removed'
            print(f"  {verb} {removed:>3} duplicate row(s): {path}")

    print(f"\nScanned {len(paths)} file(s); "
          f"{'would change' if args.dry_run else 'changed'} {files_changed}, "
          f"{'would remove' if args.dry_run else 'removed'} {total_removed} row(s).")
    if failures:
        print(f"{failures} file(s) skipped due to errors.")
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())