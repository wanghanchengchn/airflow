#!/bin/bash

DAG_NAME=$1
WAIT_TIME=$2   # seconds to wait for all DAG runs to finish after the last batch
# REPETITION_ARRAY=(76 81 71 69 75) # 30 users
# REPETITION_ARRAY=(67 68 62 59 66) # 20 users
# REPETITION_ARRAY=(5 9 5 6 5) # 10 users
# REPETITION_ARRAY=(61 55 56 52 60) # 1 users

REPETITION_ARRAY=(67)

TOTAL_MINUTES=${#REPETITION_ARRAY[@]}
TOTAL_RUNS=0
for n in "${REPETITION_ARRAY[@]}"; do
    TOTAL_RUNS=$((TOTAL_RUNS + n))
done

echo "=== Production Testing: $DAG_NAME ==="
echo "    Schedule: ${REPETITION_ARRAY[*]} (runs per minute, $TOTAL_MINUTES minutes)"
echo "    Total runs: $TOTAL_RUNS"

################################################################################################################
echo "Recording start timestamp for log filtering..."
START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "Start time: $START_TIME"

################################################################################################################

log_dir=./benchmark/"$(date +%s)"
mkdir -p "$log_dir"

kubectl port-forward svc/airflow-webserver 8080:8080 --namespace airflow 1>/dev/null 2>&1 &
PORTFORWARD_PID=$!
sleep 2  # wait for port-forward to establish

################################################################################################################
ALL_TRIGGER_PIDS=()

for minute in $(seq 1 "$TOTAL_MINUTES")
do
    n=${REPETITION_ARRAY[$((minute - 1))]}
    BATCH_START=$(date +%s)
    echo "Minute $minute/$TOTAL_MINUTES: triggering $n DAG runs in parallel..."

    BATCH_PIDS=()
    for i in $(seq 1 "$n")
    do
        python3 ./workflow-gateway/main.py "$DAG_NAME" &
        pid=$!
        BATCH_PIDS+=($pid)
        ALL_TRIGGER_PIDS+=($pid)
    done

    wait "${BATCH_PIDS[@]}"
    echo "  Minute $minute done: $n runs triggered."

    if [ "$minute" -lt "$TOTAL_MINUTES" ]; then
        ELAPSED=$(( $(date +%s) - BATCH_START ))
        REMAINING=$((60 - ELAPSED))
        if [ "$REMAINING" -gt 0 ]; then
            echo "  Waiting ${REMAINING}s before next batch (batch took ${ELAPSED}s)..."
            sleep "$REMAINING"
        else
            echo "  WARNING: batch took ${ELAPSED}s, already past 60s window, starting next batch immediately."
        fi
    fi
done

echo "All $TOTAL_RUNS DAG runs triggered across $TOTAL_MINUTES minutes."

################################################################################################################
echo "Waiting ${WAIT_TIME}s for last batch to complete..."
sleep "$WAIT_TIME"

################################################################################################################
echo "Collecting scheduler logs..."

scheduler="$(kubectl -n airflow get pods | grep scheduler | awk '{print $1}')"
kubectl -n airflow logs "$scheduler" scheduler --since-time="$START_TIME" > "$log_dir"/log_scheduler.log
grep WHC_E2E_LATENCY "$log_dir"/log_scheduler.log > "$log_dir"/log_whc_e2e_latency.log

echo "Scheduler log lines collected:      $(wc -l < "$log_dir"/log_scheduler.log)"
echo "Raw WHC_E2E_LATENCY lines collected: $(wc -l < "$log_dir"/log_whc_e2e_latency.log)"

################################################################################################################
echo "=== E2E Latencies (seconds) ==="
cat "$log_dir"/log_whc_e2e_latency.log | python3 scripts/12_process_random_e2e_latency.py $TOTAL_RUNS
