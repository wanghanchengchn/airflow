import sys
import re
from dateutil import parser

def parse_timestamp(timestamp_str):
    return parser.parse(timestamp_str)

def process_group(lines):
    for line in lines:
        print(line)

    output = []
    
    # Process the first line
    first_line_match = re.search(r'\[([\d\-T:\.+ ]+)\]', lines[0])
    # begin_match = re.search(r'<DagRun\s+\S+\s+@\s+([\d\-\+:. T]+):', lines[0])
    begin_match = re.search(r'queued_at: ([\d\-\+:. T]+)', lines[0])
    
    if first_line_match and begin_match:
        first_timestamp = parse_timestamp(first_line_match.group(1))
        begin_timestamp = parse_timestamp(begin_match.group(1))
        time_diff = (first_timestamp - begin_timestamp).total_seconds()
        output.append(f"{time_diff:.3f}")
    
    # Process the rest of the lines
    for i in range(1, len(lines)):
        prev_match = re.search(r'\[([\d\-T:\.+ ]+)\]', lines[i-1])
        curr_match = re.search(r'\[([\d\-T:\.+ ]+)\]', lines[i])
        
        if prev_match and curr_match:
            prev_timestamp = parse_timestamp(prev_match.group(1))
            curr_timestamp = parse_timestamp(curr_match.group(1))
            time_diff = (curr_timestamp - prev_timestamp).total_seconds()
            output.append(f"{time_diff:.3f}")
    
    return output

def format_output(results):
    formatted_output = []
    formatted_output.append(results[0])  # First number on its own line
    
    # Middle numbers, four per line
    for i in range(1, len(results) - 1, 4):
        formatted_output.append(" ".join(results[i:i+4]))
    
    formatted_output.append(results[-1])  # Last number on its own line
    return formatted_output

def analyze_columns(formatted_output):
    analyze_ans = []
    analyze_ans.append(float(formatted_output[0]))
    
    # Skip the first and last lines
    middle_lines = formatted_output[1:-1]
    
    # Initialize column sums
    column_sums = [0.0] * 4
    
    for line in middle_lines:
        values = list(map(float, line.split()))
        for i, value in enumerate(values):
            column_sums[i] += value
    
    analyze_ans.extend(column_sums)
    analyze_ans.append(float(formatted_output[-1]))
    
    return analyze_ans

def main():
    if len(sys.argv) != 3:
        print("Usage: python script.py <num_groups> <lines_per_group>")
        sys.exit(1)

    num_groups = int(sys.argv[1])
    lines_per_group = int(sys.argv[2])

    all_lines = sys.stdin.readlines()
    
    breakdown_avg = [0.0] * 6
    latency_sum = 0.0
    
    for i in range(num_groups):
        start_index = i * lines_per_group
        end_index = start_index + lines_per_group
        group_lines = all_lines[start_index:end_index]
        
        results = process_group(group_lines)
        formatted_results = format_output(results)
        
        # print(f"Group {i+1}:")
        
        total_sum = sum(float(x) for x in results)
        latency_sum += total_sum
        print(f"Sum: {total_sum:.3f}")
        
        # for line in formatted_results:
        #     print(line)
        
        group_result = analyze_columns(formatted_results)
        
        for i in range(6):
            breakdown_avg[i] += group_result[i]
        
        print(analyze_columns(formatted_results))
    
    for i in range(6):
        breakdown_avg[i] /= num_groups
        print(f"{breakdown_avg[i]:.3f}")
        
    print(f"{latency_sum / num_groups :.3f}")
    
if __name__ == "__main__":
    main()