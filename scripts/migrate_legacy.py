"""Repeatable legacy migration (F.01-F.03, F.27).

Uses exactly the same importer as the staff screen (final_release.run_import).
Safe to run more than once: records are matched on their legacy id, so a second
run reports them as skipped/updated instead of creating copies.

    # preview only (nothing is written except the run record)
    DATABASE_URL=... python scripts/migrate_legacy.py fixtures/final/legacy_export.json \
        --expected fixtures/final/legacy_expected_results.json

    # apply
    DATABASE_URL=... python scripts/migrate_legacy.py fixtures/final/legacy_export.json --apply

    # scale fixture (same importer, same tables)
    DATABASE_URL=... python scripts/migrate_legacy.py fixtures/final/scale_fixture.json --apply

Writes the full JSON report to --report (default: migration_report.json).
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('export', help='legacy_export.json or scale_fixture.json')
    ap.add_argument('--apply', action='store_true', help='write the records (default is a dry run)')
    ap.add_argument('--expected', help='legacy_expected_results.json to check the run against')
    ap.add_argument('--report', default='migration_report.json')
    a = ap.parse_args()
    if not os.environ.get('DATABASE_URL'):
        raise SystemExit('Set DATABASE_URL first (never commit it).')
    os.environ.setdefault('GITHUB_CLIENT_ID', 'unused-by-cli')
    os.environ.setdefault('GITHUB_CLIENT_SECRET', 'unused-by-cli')
    import main  # noqa: E402  (creates/updates the schema, additive only)
    import final_release  # noqa: E402
    main.setup_db()
    data = json.loads(Path(a.export).read_text(encoding='utf-8'))
    expected = json.loads(Path(a.expected).read_text(encoding='utf-8')) if a.expected else None
    with main.db() as conn:
        report = final_release.run_import(conn, data, source_name=Path(a.export).name, run_by='cli',
                                          dry_run=not a.apply, expected=expected)
    Path(a.report).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Run {report['run_id']} ({report['mode']}) source={report['source_name']} sha256={report['source_sha256'][:12]}")
    print('Source counts:', report['source_counts'])
    for entity, c in report['results'].items():
        print(f"  {entity:15} created={c['created']} updated={c['updated']} skipped={c['skipped']} conflict={c['conflict']}")
    for d in report['duplicate_candidates']:
        print(f"  duplicate: {d['entity']} {d['legacy_id']} ~ {d['possible_duplicate_of']} ({d['reason']})")
    for b in report['broken_references']:
        print('  broken reference:', {k: v for k, v in b.items() if k != 'reason'}, '-', b['reason'])
    for m in report['malformed_records']:
        print('  malformed:', m)
    if report['unclaimed_profiles']:
        print('  unclaimed profiles:', ', '.join(report['unclaimed_profiles']))
    if 'acceptance' in report:
        for c in report['acceptance']['checks']:
            print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['check']}")
        print('Acceptance:', 'PASS' if report['acceptance']['all_pass'] else 'FAIL')
    print('Full report written to', a.report)


if __name__ == '__main__':
    main()
