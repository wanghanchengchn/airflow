#!/bin/bash

# 单独执行d5: 28.081756 + 27.024905 + 26.546192 + 27.783421 ==> 27.3590685 * 5 ==> 136.795343 
# 单独执行d7: 16.513162 + 14.840593 + 15.455115 + 15.019464 ==> 15.4570835 * 5 ==> 77.2854175
# 单独执行d10: 12.738637 + 12.856654 + 12.548482 + 10.462124 ==> 12.1514742 * 5 ==> 60.757371
# 单独执行d17: 37.122020 + 28.129372 + 28.229297 + 28.315428 ==> 30.4490292 * 5 ==> 152.245146

WAIT_TIME=$1   # seconds to wait for all DAG runs to finish after the last batch

# ---- Scaling factor: multiply every element in all repetition arrays by this value ----
# SCALE=1
SCALE=0.8

# ---- Per-DAG repetition arrays (runs per minute) ----
# All 20 arrays must have the same length (= number of minutes).
REPETITION_ARRAY_D5_1=(0 1 0 0 0)
REPETITION_ARRAY_D5_2=(0 1 0 1 0)
REPETITION_ARRAY_D5_3=(1 0 0 0 2)
REPETITION_ARRAY_D5_4=(1 1 1 1 1)
REPETITION_ARRAY_D5_5=(0 10 0 0 0)

REPETITION_ARRAY_D7_1=(0 0 1 0 0)
REPETITION_ARRAY_D7_2=(0 1 0 1 0)
REPETITION_ARRAY_D7_3=(0 0 0 0 3)
REPETITION_ARRAY_D7_4=(1 1 2 0 1)
REPETITION_ARRAY_D7_5=(3 3 3 3 3)

REPETITION_ARRAY_D10_1=(1 0 0 0 0)
REPETITION_ARRAY_D10_2=(0 0 0 0 2)
REPETITION_ARRAY_D10_3=(1 1 1 1 1)
REPETITION_ARRAY_D10_4=(1 1 1 1 1)
REPETITION_ARRAY_D10_5=(4 4 3 1 6)

REPETITION_ARRAY_D17_1=(0 1 0 1 0)
REPETITION_ARRAY_D17_2=(1 1 1 0 0)
REPETITION_ARRAY_D17_3=(1 1 1 1 1)
REPETITION_ARRAY_D17_4=(0 10 0 0 0)
REPETITION_ARRAY_D17_5=(0 9 11 2 0)

# ---- Apply SCALE to all arrays (supports decimals, rounds to nearest integer) ----
scale_array() {
    local -n _arr=$1
    for i in "${!_arr[@]}"; do
        _arr[$i]=$(python3 -c "import math; print(math.ceil(${_arr[$i]} * $SCALE))")
    done
}

scale_array REPETITION_ARRAY_D5_1
scale_array REPETITION_ARRAY_D5_2
scale_array REPETITION_ARRAY_D5_3
scale_array REPETITION_ARRAY_D5_4
scale_array REPETITION_ARRAY_D5_5
scale_array REPETITION_ARRAY_D7_1
scale_array REPETITION_ARRAY_D7_2
scale_array REPETITION_ARRAY_D7_3
scale_array REPETITION_ARRAY_D7_4
scale_array REPETITION_ARRAY_D7_5
scale_array REPETITION_ARRAY_D10_1
scale_array REPETITION_ARRAY_D10_2
scale_array REPETITION_ARRAY_D10_3
scale_array REPETITION_ARRAY_D10_4
scale_array REPETITION_ARRAY_D10_5
scale_array REPETITION_ARRAY_D17_1
scale_array REPETITION_ARRAY_D17_2
scale_array REPETITION_ARRAY_D17_3
scale_array REPETITION_ARRAY_D17_4
scale_array REPETITION_ARRAY_D17_5

TOTAL_MINUTES=${#REPETITION_ARRAY_D5_1[@]}

# Calculate total runs per DAG
TOTAL_RUNS_D5_1=0;  for n in "${REPETITION_ARRAY_D5_1[@]}";  do TOTAL_RUNS_D5_1=$((TOTAL_RUNS_D5_1   + n)); done
TOTAL_RUNS_D5_2=0;  for n in "${REPETITION_ARRAY_D5_2[@]}";  do TOTAL_RUNS_D5_2=$((TOTAL_RUNS_D5_2   + n)); done
TOTAL_RUNS_D5_3=0;  for n in "${REPETITION_ARRAY_D5_3[@]}";  do TOTAL_RUNS_D5_3=$((TOTAL_RUNS_D5_3   + n)); done
TOTAL_RUNS_D5_4=0;  for n in "${REPETITION_ARRAY_D5_4[@]}";  do TOTAL_RUNS_D5_4=$((TOTAL_RUNS_D5_4   + n)); done
TOTAL_RUNS_D5_5=0;  for n in "${REPETITION_ARRAY_D5_5[@]}";  do TOTAL_RUNS_D5_5=$((TOTAL_RUNS_D5_5   + n)); done

TOTAL_RUNS_D7_1=0;  for n in "${REPETITION_ARRAY_D7_1[@]}";  do TOTAL_RUNS_D7_1=$((TOTAL_RUNS_D7_1   + n)); done
TOTAL_RUNS_D7_2=0;  for n in "${REPETITION_ARRAY_D7_2[@]}";  do TOTAL_RUNS_D7_2=$((TOTAL_RUNS_D7_2   + n)); done
TOTAL_RUNS_D7_3=0;  for n in "${REPETITION_ARRAY_D7_3[@]}";  do TOTAL_RUNS_D7_3=$((TOTAL_RUNS_D7_3   + n)); done
TOTAL_RUNS_D7_4=0;  for n in "${REPETITION_ARRAY_D7_4[@]}";  do TOTAL_RUNS_D7_4=$((TOTAL_RUNS_D7_4   + n)); done
TOTAL_RUNS_D7_5=0;  for n in "${REPETITION_ARRAY_D7_5[@]}";  do TOTAL_RUNS_D7_5=$((TOTAL_RUNS_D7_5   + n)); done

TOTAL_RUNS_D10_1=0; for n in "${REPETITION_ARRAY_D10_1[@]}"; do TOTAL_RUNS_D10_1=$((TOTAL_RUNS_D10_1 + n)); done
TOTAL_RUNS_D10_2=0; for n in "${REPETITION_ARRAY_D10_2[@]}"; do TOTAL_RUNS_D10_2=$((TOTAL_RUNS_D10_2 + n)); done
TOTAL_RUNS_D10_3=0; for n in "${REPETITION_ARRAY_D10_3[@]}"; do TOTAL_RUNS_D10_3=$((TOTAL_RUNS_D10_3 + n)); done
TOTAL_RUNS_D10_4=0; for n in "${REPETITION_ARRAY_D10_4[@]}"; do TOTAL_RUNS_D10_4=$((TOTAL_RUNS_D10_4 + n)); done
TOTAL_RUNS_D10_5=0; for n in "${REPETITION_ARRAY_D10_5[@]}"; do TOTAL_RUNS_D10_5=$((TOTAL_RUNS_D10_5 + n)); done

TOTAL_RUNS_D17_1=0; for n in "${REPETITION_ARRAY_D17_1[@]}"; do TOTAL_RUNS_D17_1=$((TOTAL_RUNS_D17_1 + n)); done
TOTAL_RUNS_D17_2=0; for n in "${REPETITION_ARRAY_D17_2[@]}"; do TOTAL_RUNS_D17_2=$((TOTAL_RUNS_D17_2 + n)); done
TOTAL_RUNS_D17_3=0; for n in "${REPETITION_ARRAY_D17_3[@]}"; do TOTAL_RUNS_D17_3=$((TOTAL_RUNS_D17_3 + n)); done
TOTAL_RUNS_D17_4=0; for n in "${REPETITION_ARRAY_D17_4[@]}"; do TOTAL_RUNS_D17_4=$((TOTAL_RUNS_D17_4 + n)); done
TOTAL_RUNS_D17_5=0; for n in "${REPETITION_ARRAY_D17_5[@]}"; do TOTAL_RUNS_D17_5=$((TOTAL_RUNS_D17_5 + n)); done

TOTAL_RUNS_D5=$((TOTAL_RUNS_D5_1 + TOTAL_RUNS_D5_2 + TOTAL_RUNS_D5_3 + TOTAL_RUNS_D5_4 + TOTAL_RUNS_D5_5))
TOTAL_RUNS_D7=$((TOTAL_RUNS_D7_1 + TOTAL_RUNS_D7_2 + TOTAL_RUNS_D7_3 + TOTAL_RUNS_D7_4 + TOTAL_RUNS_D7_5))
TOTAL_RUNS_D10=$((TOTAL_RUNS_D10_1 + TOTAL_RUNS_D10_2 + TOTAL_RUNS_D10_3 + TOTAL_RUNS_D10_4 + TOTAL_RUNS_D10_5))
TOTAL_RUNS_D17=$((TOTAL_RUNS_D17_1 + TOTAL_RUNS_D17_2 + TOTAL_RUNS_D17_3 + TOTAL_RUNS_D17_4 + TOTAL_RUNS_D17_5))

TOTAL_RUNS=$((TOTAL_RUNS_D5 + TOTAL_RUNS_D7 + TOTAL_RUNS_D10 + TOTAL_RUNS_D17))

echo "=== Production Testing: 20 DAGs (dag_w1_d5_{1..5} / dag_w1_d7_{1..5} / dag_w1_d10_{1..5} / dag_w1_d17_{1..5}) ==="
echo "    D5_1: ${REPETITION_ARRAY_D5_1[*]}  D5_2: ${REPETITION_ARRAY_D5_2[*]}  D5_3: ${REPETITION_ARRAY_D5_3[*]}  D5_4: ${REPETITION_ARRAY_D5_4[*]}  D5_5: ${REPETITION_ARRAY_D5_5[*]}  (total: $TOTAL_RUNS_D5)"
echo "    D7_1: ${REPETITION_ARRAY_D7_1[*]}  D7_2: ${REPETITION_ARRAY_D7_2[*]}  D7_3: ${REPETITION_ARRAY_D7_3[*]}  D7_4: ${REPETITION_ARRAY_D7_4[*]}  D7_5: ${REPETITION_ARRAY_D7_5[*]}  (total: $TOTAL_RUNS_D7)"
echo "    D10_1: ${REPETITION_ARRAY_D10_1[*]} D10_2: ${REPETITION_ARRAY_D10_2[*]} D10_3: ${REPETITION_ARRAY_D10_3[*]} D10_4: ${REPETITION_ARRAY_D10_4[*]} D10_5: ${REPETITION_ARRAY_D10_5[*]} (total: $TOTAL_RUNS_D10)"
echo "    D17_1: ${REPETITION_ARRAY_D17_1[*]} D17_2: ${REPETITION_ARRAY_D17_2[*]} D17_3: ${REPETITION_ARRAY_D17_3[*]} D17_4: ${REPETITION_ARRAY_D17_4[*]} D17_5: ${REPETITION_ARRAY_D17_5[*]} (total: $TOTAL_RUNS_D17)"
echo "    Minutes: $TOTAL_MINUTES  |  Grand total runs: $TOTAL_RUNS"

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
    idx=$((minute - 1))
    n_d5_1=${REPETITION_ARRAY_D5_1[$idx]}
    n_d5_2=${REPETITION_ARRAY_D5_2[$idx]}
    n_d5_3=${REPETITION_ARRAY_D5_3[$idx]}
    n_d5_4=${REPETITION_ARRAY_D5_4[$idx]}
    n_d5_5=${REPETITION_ARRAY_D5_5[$idx]}

    n_d7_1=${REPETITION_ARRAY_D7_1[$idx]}
    n_d7_2=${REPETITION_ARRAY_D7_2[$idx]}
    n_d7_3=${REPETITION_ARRAY_D7_3[$idx]}
    n_d7_4=${REPETITION_ARRAY_D7_4[$idx]}
    n_d7_5=${REPETITION_ARRAY_D7_5[$idx]}

    n_d10_1=${REPETITION_ARRAY_D10_1[$idx]}
    n_d10_2=${REPETITION_ARRAY_D10_2[$idx]}
    n_d10_3=${REPETITION_ARRAY_D10_3[$idx]}
    n_d10_4=${REPETITION_ARRAY_D10_4[$idx]}
    n_d10_5=${REPETITION_ARRAY_D10_5[$idx]}

    n_d17_1=${REPETITION_ARRAY_D17_1[$idx]}
    n_d17_2=${REPETITION_ARRAY_D17_2[$idx]}
    n_d17_3=${REPETITION_ARRAY_D17_3[$idx]}
    n_d17_4=${REPETITION_ARRAY_D17_4[$idx]}
    n_d17_5=${REPETITION_ARRAY_D17_5[$idx]}

    BATCH_TOTAL=$(( n_d5_1+n_d5_2+n_d5_3+n_d5_4+n_d5_5 + n_d7_1+n_d7_2+n_d7_3+n_d7_4+n_d7_5 + n_d10_1+n_d10_2+n_d10_3+n_d10_4+n_d10_5 + n_d17_1+n_d17_2+n_d17_3+n_d17_4+n_d17_5 ))

    BATCH_START=$(date +%s)
    echo "Minute $minute/$TOTAL_MINUTES: triggering $BATCH_TOTAL runs across 20 DAGs in parallel..."

    BATCH_PIDS=()

    for i in $(seq 1 "$n_d5_1");  do python3 ./workflow-gateway/main.py "dag_w1_d5_1"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d5_2");  do python3 ./workflow-gateway/main.py "dag_w1_d5_2"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d5_3");  do python3 ./workflow-gateway/main.py "dag_w1_d5_3"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d5_4");  do python3 ./workflow-gateway/main.py "dag_w1_d5_4"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d5_5");  do python3 ./workflow-gateway/main.py "dag_w1_d5_5"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done

    for i in $(seq 1 "$n_d7_1");  do python3 ./workflow-gateway/main.py "dag_w1_d7_1"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d7_2");  do python3 ./workflow-gateway/main.py "dag_w1_d7_2"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d7_3");  do python3 ./workflow-gateway/main.py "dag_w1_d7_3"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d7_4");  do python3 ./workflow-gateway/main.py "dag_w1_d7_4"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d7_5");  do python3 ./workflow-gateway/main.py "dag_w1_d7_5"  & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done

    for i in $(seq 1 "$n_d10_1"); do python3 ./workflow-gateway/main.py "dag_w1_d10_1" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d10_2"); do python3 ./workflow-gateway/main.py "dag_w1_d10_2" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d10_3"); do python3 ./workflow-gateway/main.py "dag_w1_d10_3" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d10_4"); do python3 ./workflow-gateway/main.py "dag_w1_d10_4" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d10_5"); do python3 ./workflow-gateway/main.py "dag_w1_d10_5" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done

    for i in $(seq 1 "$n_d17_1"); do python3 ./workflow-gateway/main.py "dag_w1_d17_1" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d17_2"); do python3 ./workflow-gateway/main.py "dag_w1_d17_2" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d17_3"); do python3 ./workflow-gateway/main.py "dag_w1_d17_3" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d17_4"); do python3 ./workflow-gateway/main.py "dag_w1_d17_4" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done
    for i in $(seq 1 "$n_d17_5"); do python3 ./workflow-gateway/main.py "dag_w1_d17_5" & pid=$!; BATCH_PIDS+=($pid); ALL_TRIGGER_PIDS+=($pid); done

    wait "${BATCH_PIDS[@]}"
    echo "  Minute $minute done: $BATCH_TOTAL runs triggered."

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
echo "Splitting latency log by DAG type..."

grep "dag_w1_d5"  "$log_dir"/log_whc_e2e_latency.log > "$log_dir"/log_whc_e2e_latency_d5.log
grep "dag_w1_d7"  "$log_dir"/log_whc_e2e_latency.log > "$log_dir"/log_whc_e2e_latency_d7.log
grep "dag_w1_d10" "$log_dir"/log_whc_e2e_latency.log > "$log_dir"/log_whc_e2e_latency_d10.log
grep "dag_w1_d17" "$log_dir"/log_whc_e2e_latency.log > "$log_dir"/log_whc_e2e_latency_d17.log

echo "  D5  latency lines: $(wc -l < "$log_dir"/log_whc_e2e_latency_d5.log)"
echo "  D7  latency lines: $(wc -l < "$log_dir"/log_whc_e2e_latency_d7.log)"
echo "  D10 latency lines: $(wc -l < "$log_dir"/log_whc_e2e_latency_d10.log)"
echo "  D17 latency lines: $(wc -l < "$log_dir"/log_whc_e2e_latency_d17.log)"

################################################################################################################
echo "=== E2E Latencies: dag_w1_d5 (all variants) ==="
cat "$log_dir"/log_whc_e2e_latency_d5.log  | python3 scripts/12_process_random_e2e_latency.py $TOTAL_RUNS_D5

echo "=== E2E Latencies: dag_w1_d7 (all variants) ==="
cat "$log_dir"/log_whc_e2e_latency_d7.log  | python3 scripts/12_process_random_e2e_latency.py $TOTAL_RUNS_D7

echo "=== E2E Latencies: dag_w1_d10 (all variants) ==="
cat "$log_dir"/log_whc_e2e_latency_d10.log | python3 scripts/12_process_random_e2e_latency.py $TOTAL_RUNS_D10

echo "=== E2E Latencies: dag_w1_d17 (all variants) ==="
cat "$log_dir"/log_whc_e2e_latency_d17.log | python3 scripts/12_process_random_e2e_latency.py $TOTAL_RUNS_D17
