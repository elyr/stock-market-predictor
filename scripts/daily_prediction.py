"""
Run the day's prediction and save the results as files.

Standalone on purpose: it does not use the API server, the database or the
frontend. It runs each pipeline (stocks, crypto) once, checks that the output
is sane, and writes everything to one folder that CI uploads as an artifact
(see .github/workflows/daily-prediction.yml).

Usage:
    python scripts/daily_prediction.py                       # both universes, live data
    python scripts/daily_prediction.py --universe crypto
    python scripts/daily_prediction.py --demo --limit 20     # simulated prices, quick

Output folder (default ./predictions):
    report.md                    human-readable summary of the run
    run.json                     run metadata, timings, check results
    <universe>_picks.csv         suggested portfolio with weights and reasons
    <universe>_rankings.csv      every asset that passed the filters, best first
    <universe>_summary.json      model quality, calibration, volatility model

Exit code 0 when every universe ran and passed its checks, 1 otherwise. Files
are written either way, so a failed run can still be inspected.

Educational use only. Not financial advice.
"""

import argparse
import json
import logging
import math
import os
import platform
import sys
import time
import traceback
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.data.synthetic import SyntheticDataCollector  # noqa: E402
from src.prediction import UNIVERSES, create_pipeline  # noqa: E402

# Newest acceptable price date, in calendar days before today (live data only).
# Stocks allow for weekends and a holiday; crypto trades every day.
MAX_DATA_AGE_DAYS = {'stocks': 4, 'crypto': 2}

PICK_COLUMNS = ['Rank', 'Symbol', 'Company_Name', 'Sector', 'Weight', 'Composite_Score', 'ML_Probability',
                'ML_Confidence', 'Recommendation', 'Current_Price', 'Daily_Change_Pct', 'Volatility', 'Vol_Forecast',
                'Technical_Score', 'ML_Score', 'Momentum_Score', 'Volume_Score', 'Sentiment_Score', 'RSI',
                'Signals', 'Top_Reasons', 'Data_Date']


# ---------------------------------------------------------------- helpers

def clean(value: Any) -> Any:
    """Make numpy/pandas values JSON-safe; NaN and infinity become null."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(value) or math.isinf(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    return value


def verdict(t_stat: Any) -> str:
    """Plain-language reading of a t-statistic (same thresholds as the app)."""
    if t_stat is None or (isinstance(t_stat, float) and math.isnan(t_stat)):
        return 'not enough data'
    if t_stat >= 3:
        return 'strong evidence of skill'
    if t_stat >= 2:
        return 'some evidence of skill'
    if t_stat > -2:
        return 'indistinguishable from luck'
    return 'consistently wrong'


def reasons(explanation: Any, limit: int = 3) -> str:
    """'For: X; Against: Y' from the model's per-feature contributions."""
    if not isinstance(explanation, list):
        return ''
    parts = [f"{'For' if e['contribution'] > 0 else 'Against'}: {e['label']}" for e in explanation[:limit]]
    return '; '.join(parts)


def flat_table(frame: pd.DataFrame) -> pd.DataFrame:
    """List-valued columns joined to text so the table fits a CSV."""
    out = frame.copy()
    if 'Signals' in out:
        out['Signals'] = out['Signals'].map(lambda v: '; '.join(v) if isinstance(v, list) else '')
    if 'Explanation' in out:
        out['Top_Reasons'] = out['Explanation'].map(reasons)
        out = out.drop(columns=['Explanation'])
    return out


def fmt_price(value: Any) -> str:
    if value is None:
        return ''
    if value >= 1000:
        return f'{value:,.0f}'
    if value >= 1:
        return f'{value:,.2f}'
    return f'{value:.4f}'


def md(text: Any) -> str:
    """Escape a value for a Markdown table cell."""
    return str(text).replace('|', '\\|').replace('\n', ' ')


# ----------------------------------------------------------------- checks

def run_checks(universe: str, result: Dict[str, Any], top_n: int, live: bool,
               today: date, downloaded: int) -> List[Dict[str, Any]]:
    """Sanity checks on one universe's output. Each is a dict with name, passed, detail."""
    rankings, picks, summary = result['full_rankings'], result['top_10'], result['analysis_summary']
    attempted = summary.get('total_symbols_attempted')
    checks: List[Dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = '') -> None:
        checks.append({'name': name, 'passed': bool(passed), 'detail': detail})

    check('Price data downloaded', downloaded > 0, f'{downloaded} of {attempted} symbols'
          + ('' if downloaded else ': the data source returned nothing (network blocked or rate-limited?)'))
    if not downloaded:
        return checks
    check('Assets ranked', len(rankings) > 0, f'{len(rankings)} of {downloaded} passed the price and volume filters')
    if rankings.empty:
        return checks

    expected = min(top_n, len(rankings))
    check('Portfolio size', len(picks) == expected, f'{len(picks)} picks, expected {expected}')
    weight_sum = float(picks['Weight'].sum()) if 'Weight' in picks else 0.0
    check('Weights add up to 100%', abs(weight_sum - 1) < 1e-6, f'{weight_sum:.6f}')

    scores = rankings[['Composite_Score', 'Technical_Score', 'Momentum_Score', 'Volume_Score', 'ML_Score']]
    check('Scores between 0 and 100', bool(scores.notna().all().all() and scores.ge(0).all().all()
                                          and scores.le(100).all().all()))
    check('Ranked best first', bool(rankings['Composite_Score'].is_monotonic_decreasing))
    check('Indicators computed', bool(rankings['RSI'].notna().all()), 'RSI present for every asset')

    models = summary.get('ml_models_used') or []
    check('Models trained', len(models) > 0, ', '.join(models) or 'none')
    probabilities = rankings['ML_Probability']
    check('Probabilities between 0 and 1', bool(probabilities.notna().all() and probabilities.between(0, 1).all()))

    if live:
        data_date = pd.Timestamp(summary.get('data_date')).date()
        age = (today - data_date).days
        limit = MAX_DATA_AGE_DAYS.get(universe, 4)
        check('Prices are recent', age <= limit, f'latest price {data_date}, {age} days old (limit {limit})')
    return checks


# ------------------------------------------------------------------ run

def run_universe(universe: str, args: argparse.Namespace, out_dir: str, today: date) -> Dict[str, Any]:
    started = time.time()
    labels = {'stocks': 'US Stocks', 'crypto': 'Crypto'}
    record: Dict[str, Any] = {'universe': universe, 'label': labels.get(universe, universe),
                              'status': 'failed', 'checks': []}
    try:
        collector = SyntheticDataCollector(reversal=0.2) if args.demo else None
        pipeline = create_pipeline(universe, args.config, data_collector=collector)
        if args.demo or args.no_sentiment:
            pipeline.use_sentiment = False
        symbols = pipeline.symbols[:args.limit] if args.limit else pipeline.symbols
        top_n = args.top_n or pipeline.ranking_config.get('top_picks', 10)
        print(f'[{universe}] ranking {len(symbols)} assets ({"simulated" if args.demo else "live"} prices)...', flush=True)

        result = pipeline.get_top_10_recommendations(symbols, top_n=top_n)
        rankings, picks, summary = result['full_rankings'], result['top_10'], result['analysis_summary']

        record['label'] = pipeline.label
        record['checks'] = run_checks(universe, result, top_n, live=not args.demo, today=today,
                                      downloaded=len(pipeline.last_prepared))
        record['status'] = 'passed' if all(c['passed'] for c in record['checks']) else 'failed'
        record['data_date'] = summary.get('data_date')
        record['horizon_days'] = summary.get('horizon_days')
        record['assets_ranked'] = int(len(rankings))
        record['model_quality'] = clean(summary.get('model_quality') or {})
        record['picks'] = clean(flat_table(picks).assign(Rank=range(1, len(picks) + 1))
                                .reindex(columns=PICK_COLUMNS).to_dict(orient='records')) if len(picks) else []

        if not rankings.empty:
            flat_table(picks).assign(Rank=range(1, len(picks) + 1)).reindex(columns=PICK_COLUMNS) \
                .to_csv(os.path.join(out_dir, f'{universe}_picks.csv'), index=False, float_format='%.6g')
            flat_table(rankings).assign(Rank=range(1, len(rankings) + 1)) \
                .to_csv(os.path.join(out_dir, f'{universe}_rankings.csv'), index=False, float_format='%.6g')
        with open(os.path.join(out_dir, f'{universe}_summary.json'), 'w') as f:
            json.dump(clean(summary), f, indent=2)
    except Exception as e:  # recorded in run.json and the report; the other universe still runs
        record['error'] = f'{type(e).__name__}: {e}'
        record['traceback'] = traceback.format_exc()
        print(f'[{universe}] failed: {record["error"]}', flush=True)
    record['seconds'] = round(time.time() - started, 1)
    passed = sum(c['passed'] for c in record['checks'])
    print(f'[{universe}] {record["status"]}: {passed}/{len(record["checks"])} checks passed in {record["seconds"]}s',
          flush=True)
    for c in record['checks']:
        if not c['passed']:
            print(f'[{universe}]   FAILED {c["name"]}: {c["detail"]}', flush=True)
    return record


def write_report(path: str, run: Dict[str, Any]) -> str:
    source = 'Simulated prices (demo mode)' if run['demo'] else 'Live Yahoo Finance prices'
    commit = (run.get('commit') or '')[:7]
    lines = [
        f"# Daily prediction, {run['date']}",
        '',
        f"{source}. Generated {run['generated_at'][:16].replace('T', ' ')} UTC"
        + (f", commit {commit}" if commit else '') + '.',
        '',
    ]
    for u in run['universes']:
        label = u.get('label', u['universe'])
        lines.append(f"## {label}")
        lines.append('')
        if u.get('error'):
            lines += [f"Failed: `{md(u['error'])}`", '']
            continue
        q = u.get('model_quality') or {}
        ic, t = q.get('ic_mean'), q.get('ic_t_stat')
        if u.get('assets_ranked'):
            lines.append(f"Prices as of {u.get('data_date')}, {u.get('horizon_days')}-day outlook, "
                         f"{u.get('assets_ranked')} assets ranked.")
        if ic is not None:
            lines.append(f"Model on unseen dates: rank IC {ic:+.3f} (t = {t:.1f}), {verdict(t)}.")
        if u.get('assets_ranked') or ic is not None:
            lines.append('')
        if u.get('picks'):
            lines.append('| # | Symbol | Name | Score | Chance to beat the field | Weight | Price | Signals |')
            lines.append('|---:|---|---|---:|---:|---:|---:|---|')
            for p in u['picks']:
                prob = p.get('ML_Probability')
                lines.append(
                    f"| {p['Rank']} | {md(p['Symbol'])} | {md(p.get('Company_Name') or '')} | "
                    f"{p['Composite_Score']:.1f} | {'' if prob is None else f'{prob:.1%}'} | {p['Weight']:.0%} | "
                    f"{fmt_price(p['Current_Price'])} | {md((p.get('Signals') or '').split('; ')[0])} |")
            lines.append('')
        checks = u.get('checks', [])
        failed = [c for c in checks if not c['passed']]
        if failed:
            lines.append(f"Checks: {len(checks) - len(failed)} of {len(checks)} passed. Failed:")
            lines += [f"- {c['name']}: {c['detail']}" for c in failed]
        else:
            lines.append(f"Checks: all {len(checks)} passed.")
        lines.append('')
    lines.append('Educational use only. Not financial advice.')
    text = '\n'.join(lines) + '\n'
    with open(path, 'w') as f:
        f.write(text)
    return text


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the day's prediction and save the results as files.")
    parser.add_argument('--universe', nargs='+', choices=UNIVERSES, default=list(UNIVERSES),
                        help='Which universes to run (default: both)')
    parser.add_argument('--demo', action='store_true', help='Use simulated prices (no network needed)')
    parser.add_argument('--top-n', type=int, default=None, help='Picks per universe (default from config)')
    parser.add_argument('--limit', type=int, default=None, help='Only use the first N symbols (quick runs)')
    parser.add_argument('--no-sentiment', action='store_true', help='Skip news and sector sentiment (faster)')
    parser.add_argument('--config', default='config/config.yaml', help='Config file')
    parser.add_argument('--output-dir', default='predictions', help='Where to write the results')
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    os.makedirs(args.output_dir, exist_ok=True)
    today = datetime.now(timezone.utc).date()

    run: Dict[str, Any] = {
        'date': str(today),
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'demo': args.demo,
        'commit': os.environ.get('GITHUB_SHA'),
        'python': platform.python_version(),
        'arguments': {k: v for k, v in vars(args).items() if k != 'output_dir'},
        'universes': [],
    }
    for universe in args.universe:
        run['universes'].append(run_universe(universe, args, args.output_dir, today))
    run['status'] = 'passed' if all(u['status'] == 'passed' for u in run['universes']) else 'failed'

    with open(os.path.join(args.output_dir, 'run.json'), 'w') as f:
        json.dump(clean(run), f, indent=2)
    report = write_report(os.path.join(args.output_dir, 'report.md'), run)

    # On GitHub Actions, show the report on the run's summary page too
    summary_file = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_file:
        with open(summary_file, 'a') as f:
            f.write(report)

    print(f"Results written to {os.path.abspath(args.output_dir)} ({run['status']})", flush=True)
    return 0 if run['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
