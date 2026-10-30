#!/usr/bin/env python3
"""Describe the synthetic exercise without choosing business policies."""
import argparse
from collections import Counter
import csv
import json


def profile(path):
    with open(path, newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        rows = list(reader)
    required = {'lot_id', 'defects', 'inspected', 'review_status'}
    if not required.issubset(columns):
        raise ValueError(f'Missing columns: {sorted(required - set(columns))}')
    counts = Counter(row['lot_id'] for row in rows)
    return {
        'rows': len(rows),
        'distinct_lots': len(counts),
        'repeated_lot_ids': {key: value for key, value in counts.items() if value > 1},
        'blank_defects_rows': [index for index, row in enumerate(rows, 1) if row['defects'].strip() == ''],
        'review_status_counts': dict(Counter(row['review_status'] for row in rows)),
        'policy_applied': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv')
    args = parser.parse_args()
    print(json.dumps(profile(args.csv), ensure_ascii=False, indent=2))
