"""Print the end of a log file as a GitHub Actions annotation, so a failure's
output shows on the run's summary page (and through the checks API).

    python .github/scripts/annotate.py error "kube.sh up" up.log
"""
import sys

level, title, path = sys.argv[1:4]
try:
    text = open(path, errors='replace').read()[-6000:]
except OSError as e:
    text = f'(no log: {e})'
text = text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
print(f'::{level} title={title}::{text}')
