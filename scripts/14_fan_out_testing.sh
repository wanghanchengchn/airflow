#!/usr/bin/env bash
# For each DAG: run e2e breakdown 5 times in a row, then move to the next DAG.

dag_names=(
  dag_w1_d3
  dag_w2_d3
  dag_w4_d3
  dag_w8_d3
  dag_w16_d3
  dag_w32_d3
  dag_w64_d3
  dag_w128_d3
  dag_w256_d3
)
dag_tasks=(3 4 6 10 18 34 66 130 254)

for i in "${!dag_names[@]}"; do
  dag="${dag_names[$i]}"
  n="${dag_tasks[$i]}"
  echo "Getting e2e for $dag (5 runs)"
  for _ in 1 2 3 4 5; do
    ./scripts/8_get_e2e_breakdown.sh 1 "$dag" 60 "$n" | tail -n 1
  done
  echo "======================================"
done
