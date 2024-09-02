import re
import argparse
from datetime import datetime

def parse_timestamp(line):
    # 假设时间戳格式为 [YYYY-MM-DDTHH:MM:SS.mmm+ZZZZ]
    match = re.search(r'\[([\d\-T:\.+]+)\]', line)
    if match:
        return datetime.strptime(match.group(1), '%Y-%m-%dT%H:%M:%S.%f%z')
    return None

def merge_sort_logs(input_files, output_file):
    # 读取并解析所有输入文件
    lines = []
    for filename in input_files:
        with open(filename, 'r') as f:
            for line in f:
                timestamp = parse_timestamp(line)
                if timestamp:
                    lines.append((timestamp, line))

    # 按时间戳排序
    sorted_lines = sorted(lines, key=lambda x: x[0])

    # 写入排序后的行到新文件
    with open(output_file, 'w') as f:
        for _, line in sorted_lines:
            f.write(line)

def main():
    parser = argparse.ArgumentParser(description='Merge and sort multiple log files by timestamp.')
    parser.add_argument('input_files', nargs='+', help='Input log files to merge and sort')
    parser.add_argument('-o', '--output', default='merged_sorted.log', help='Output file name (default: merged_sorted.log)')
    
    args = parser.parse_args()
    
    merge_sort_logs(args.input_files, args.output)

if __name__ == "__main__":
    main()