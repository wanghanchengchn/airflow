import re
from dateutil import parser
import sys
import json
import argparse

def parse_datetime(dt_string):
    try:
        return parser.parse(dt_string)
    except ValueError:
        raise ValueError(f"无法解析日期时间: {dt_string}")

def process_log_group(lines, lines_per_group):
    if len(lines) < lines_per_group:
        return None

    # 从第一行提取 queued_at 时间
    queued_match = re.search(r'queued_at: ([\d\-\+:. T]+)', lines[0])
    if not queued_match:
        return None
    queued_time = parse_datetime(queued_match.group(1))

    # 从最后一行提取时间
    end_match = re.match(r'\[([\d\-\+:. T]+)\]', lines[-1])
    if not end_match:
        return None
    end_time = parse_datetime(end_match.group(1))
    
    # 计算时间差
    time_diff = end_time - queued_time
    return time_diff.total_seconds()

def main():
    parser = argparse.ArgumentParser(description="Process time data from input groups.")
    parser.add_argument("groups_to_process", type=int, help="Number of groups to process")
    parser.add_argument("lines_per_group", type=int, help="Number of lines in each group")
    args = parser.parse_args()

    # 读取输入
    lines = sys.stdin.readlines()

    # 处理日志组
    processed_groups = 0
    for i in range(0, len(lines), args.lines_per_group):
        group = lines[i:i+args.lines_per_group]
        result = process_log_group(group, args.lines_per_group)
        if result is not None:
            print(f"{result:.6f}")
            processed_groups += 1

        # 如果达到指定的处理组数，则退出
        if args.groups_to_process > 0 and processed_groups >= args.groups_to_process:
            break

if __name__ == "__main__":
    main()