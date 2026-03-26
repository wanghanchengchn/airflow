import re
import sys
import argparse
from dateutil import parser as dt_parser


# RUNNING line example:
#   [2026-03-19T09:52:01.584+0000] ... update dag_run <DagRun dag_w1_d3 @ ...: manual_847e..., state:queued, queued_at: 2026-03-19 09:52:01.031581+00:00. ...> from queued to RUNNING
RUNNING_RUN_ID_RE = re.compile(r':\s+(manual_[a-f0-9]+),')
RUNNING_QUEUED_AT_RE = re.compile(r'queued_at:\s+([\d\-\+:. T]+)\.')

# SUCCESS line example (after dagrun.py patch):
#   [2026-03-19T09:52:21.792+0000] ... Marking run dag_w1_d3 run_id=manual_847e... state=success
SUCCESS_TS_RE = re.compile(r'^\[([\d\-\+:. TZ]+)\]')
SUCCESS_RUN_ID_RE = re.compile(r'run_id=(manual_[a-f0-9]+)')


def parse_running_line(line):
    run_id_m = RUNNING_RUN_ID_RE.search(line)
    queued_at_m = RUNNING_QUEUED_AT_RE.search(line)
    if not run_id_m or not queued_at_m:
        return None, None
    run_id = run_id_m.group(1)
    queued_at = dt_parser.parse(queued_at_m.group(1))
    return run_id, queued_at


def parse_success_line(line):
    ts_m = SUCCESS_TS_RE.match(line)
    run_id_m = SUCCESS_RUN_ID_RE.search(line)
    if not ts_m or not run_id_m:
        return None, None
    end_time = dt_parser.parse(ts_m.group(1))
    run_id = run_id_m.group(1)
    return run_id, end_time


def main():
    arg_parser = argparse.ArgumentParser(
        description="Match parallel DAG run start/end by run_id and compute e2e latency."
    )
    arg_parser.add_argument(
        "groups_to_process", type=int, nargs="?", default=0,
        help="Max number of matched pairs to output (0 = all)"
    )
    args = arg_parser.parse_args()

    start_times = {}   # run_id -> queued_at
    end_times = {}     # run_id -> end timestamp
    unmatched_success = []

    for line in sys.stdin:
        line = line.rstrip()
        if "from queued to RUNNING" in line:
            run_id, queued_at = parse_running_line(line)
            if run_id:
                start_times[run_id] = queued_at
        elif "Marking run" in line and "state=success" in line:
            run_id, end_time = parse_success_line(line)
            if run_id:
                end_times[run_id] = end_time
            else:
                unmatched_success.append(line)

    matched = 0
    for run_id, queued_at in sorted(start_times.items(), key=lambda x: x[1]):
        if run_id in end_times:
            latency = (end_times[run_id] - queued_at).total_seconds()
            print(f"{latency:.6f}", end = ", ")
            matched += 1
            if args.groups_to_process > 0 and matched >= args.groups_to_process:
                break
        else:
            print(f"WARNING: no success line found for run_id={run_id}", file=sys.stderr)
    print()
    print(f"Matched: {matched} / {len(start_times)} starts, {len(end_times)} ends", file=sys.stderr)

    if unmatched_success:
        print(
            f"WARNING: {len(unmatched_success)} success line(s) had no run_id "
            f"(dagrun.py patch not applied?)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
