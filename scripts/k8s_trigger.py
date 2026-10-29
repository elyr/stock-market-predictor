"""
Start an alert scan on the running Ledger server and wait for it to finish.

Used by the Kubernetes CronJobs (deploy/helm/ledger): the scan itself runs
inside the server, which owns the database; this script only asks for it and
reports the outcome, so the Kubernetes Job succeeds or fails with the scan.

    python scripts/k8s_trigger.py --url http://ledger --universe stocks --session close

Standard library only, so it runs in any Python image.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def call(url: str, method: str = 'GET', body: dict = None, timeout: float = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b'{}')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Trigger an alert scan and wait for it.')
    parser.add_argument('--url', required=True, help='Base URL of the Ledger server, e.g. http://ledger')
    parser.add_argument('--universe', required=True, choices=['stocks', 'crypto'])
    parser.add_argument('--session', default='close', choices=['open', 'close'])
    parser.add_argument('--timeout', type=float, default=1800, help='Seconds to wait for the scan')
    parser.add_argument('--poll', type=float, default=5, help='Seconds between status checks')
    args = parser.parse_args(argv)
    base = args.url.rstrip('/')

    try:
        job = call(f'{base}/api/{args.universe}/signals/scan', 'POST', {'session': args.session})
    except (urllib.error.URLError, OSError) as e:
        print(f'Could not reach Ledger at {base}: {e}', file=sys.stderr)
        return 1
    print(f"Started {args.session} scan for {args.universe} (job {job['id']})", flush=True)

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if job['status'] in ('succeeded', 'failed'):
            break
        time.sleep(args.poll)
        try:
            job = call(f"{base}/api/jobs/{job['id']}")
        except (urllib.error.URLError, OSError) as e:
            print(f'Lost contact with Ledger: {e}', file=sys.stderr)
            return 1

    if job['status'] == 'succeeded':
        result = job.get('result') or {}
        print(f"Scan finished: {result.get('assets_scanned', '?')} assets checked, "
              f"{result.get('new_alerts', 0)} new alerts", flush=True)
        return 0
    if job['status'] == 'failed':
        print(f"Scan failed: {job.get('error')}", file=sys.stderr)
        return 1
    print(f'Scan still running after {args.timeout:.0f}s', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
