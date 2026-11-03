"""Run the regression suites of tests/ one after the other and report pass / fail and run time.

Usage (from the repository root, qudi-core 1.8 environment):
    python tests/run_suites.py                 # all suites
    python tests/run_suites.py roi_path him    # suites whose file name contains one of the words

Each suite runs in its own process (offscreen Qt) and prints "<passed>/<total> passed" at the end;
a suite fails if its exit code is not 0. The short settings and the shared test data are in
tests/_short.py and tests/data/ (rules in docs/TESTING.md).

Modified with Claude code (Anthropic)
"""
import os
import re
import subprocess
import sys
from time import monotonic

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)

# pure logic first (rule 5 of docs/TESTING.md), then the module / task suites
SUITES = [
    'test_roi_path.py',
    'test_roi_tour.py',
    'test_roi_optimize.py',
    'test_random_roi_list.py',
    'test_data_folders.py',
    'test_param_hints.py',
    'test_task_progress.py',
    'test_photobleaching_progress.py',
    'test_roi_scan_progress.py',
    'test_roi_scan_zen_checklist.py',
    'test_roi_scan_zen_folder.py',
    'test_fluidics_task.py',
    'test_probe_valve.py',
    'test_him.py',
    'test_probe_valve_him.py',
]


def main(words):
    suites = [s for s in SUITES if not words or any(w in s for w in words)]
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    failed = []
    total_time = 0.0
    for suite in suites:
        start = monotonic()
        proc = subprocess.run([sys.executable, os.path.join(TESTS, suite), REPO], capture_output=True, text=True,
                              env=env, cwd=REPO)
        elapsed = monotonic() - start
        total_time += elapsed
        counts = re.findall(r'(\d+)/(\d+) passed', proc.stdout)
        summary = f'{counts[-1][0]}/{counts[-1][1]} passed' if counts else 'no summary'
        status = 'ok  ' if proc.returncode == 0 else 'FAIL'
        print(f'{status} {suite:34s} {elapsed:7.1f} s  {summary}', flush=True)
        if proc.returncode != 0:
            failed.append(suite)
            fails = [line for line in proc.stdout.splitlines() if line.startswith('[FAIL]')]
            for line in fails or (proc.stdout + proc.stderr).strip().splitlines()[-8:]:
                print(f'       {line[:300]}')
    print(f'{len(suites) - len(failed)}/{len(suites)} suites passed, {total_time:.0f} s')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
