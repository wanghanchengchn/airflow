import sys
import re
import json
import argparse

def process_group(lines, group_size, bool_get_min):
    total_time = 0
    total_time_list = []
    for i, line in enumerate(lines):
        if i % 2 == 0:  # 处理组内的奇数行
            match = re.search(r'"function": "worker_execution", "times": (\[.*?\])', line)
            if match:
                times = json.loads(match.group(1))
                total_time += sum(times)
                total_time_list.append(sum(times))
    if bool_get_min:
        return min(total_time_list) * len(total_time_list)
    else:
        return total_time

def main():
    parser = argparse.ArgumentParser(description="Process time data from input groups.")
    parser.add_argument("num_groups", type=int, help="Number of groups to process")
    parser.add_argument("lines_per_group", type=int, help="Number of lines in each group")
    parser.add_argument("bool_get_min", type=int, help="Get min time of each group")
    args = parser.parse_args()

    for group_number in range(1, args.num_groups + 1):
        group_lines = [sys.stdin.readline().strip() for _ in range(args.lines_per_group)]
        group_total_time = process_group(group_lines, args.lines_per_group, args.bool_get_min)
        print(group_total_time)

if __name__ == "__main__":
    main()