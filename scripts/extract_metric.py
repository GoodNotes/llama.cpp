import io
from pathlib import Path
import pandas as pd


# Benchmark constant
NUM_INPUT_TOKENS = 512
NUM_OUTPUT_TOKENS = 512


def parse_model_name(run_log: list[str]) -> str:
    for line in run_log:
        if line.startswith('Model info:'):
            return line.split(':')[1].strip()


def parse_battery_used(run_log: list[str]) -> float:
    for line in run_log:
        if line.startswith('Benchmark used ') and line.endswith(' battery'):
            return float(line.lstrip('Benchmark used ').rstrip(r'% battery'))


def parse_performance_table(run_log: list[str]) -> pd.DataFrame:
    markdown_table = []
    for line in run_log:
        if line.strip() == '| --- | --- | --- | --- | --- | --- |':
            continue
        if line.strip() == '| model | size | params | backend | test | t/s |':
            markdown_table.append(line)
        elif line.strip().startswith('|'):
            markdown_table.append(line)
        elif markdown_table:
            break
    markdown_table = "\n".join(markdown_table)
    benchmark_result_df = pd.read_csv(io.StringIO(markdown_table), sep='|', header=0, index_col=False).dropna(axis=1, how='all')
    benchmark_result_df.columns = [each.strip() for each in benchmark_result_df.columns.astype(str)]
    for each in benchmark_result_df.columns:
        benchmark_result_df[each] = benchmark_result_df[each].str.strip()
    benchmark_result_df[['stage', 'num_tokens']] = benchmark_result_df['test'].str.split(' ', expand=True)
    benchmark_result_df['num_tokens'] = benchmark_result_df['num_tokens'].astype(int)
    benchmark_result_df[['avg_token_per_sec', '± std_token_per_sec']] = benchmark_result_df['t/s'].str.split('±', expand=True)
    benchmark_result_df['avg_token_per_sec'] = benchmark_result_df['avg_token_per_sec'].astype(float)
    benchmark_result_df['± std_token_per_sec'] = benchmark_result_df['± std_token_per_sec'].astype(float)
    return benchmark_result_df


def convert_metric(benchmark_result_df: pd.DataFrame) -> dict[str, float]:
    temp = benchmark_result_df.set_index(['stage']).drop(columns=['test', 't/s', 'backend', 'model', 'size', 'params', 'num_tokens'])
    avg_token_per_sec_pp = temp.loc['pp']['avg_token_per_sec']
    avg_token_per_sec_tg = temp.loc['tg']['avg_token_per_sec']

    # Time To First Token (TTFT): How quickly users start seeing the model's output after entering their query. Low waiting times for a response are essential in real-time interactions, but less important in offline workloads. This metric is driven by the time required to process the prompt and then generate the first output token.

    time_to_first_token_sec =  NUM_INPUT_TOKENS / avg_token_per_sec_pp + 1 / avg_token_per_sec_tg
    time_to_first_token_ms = time_to_first_token_sec * 1000

    # Time Per Output Token (TPOT): Time to generate an output token for each user that is querying our system. This metric corresponds with how each user will perceive the "speed" of the model. For example, a TPOT of 100 milliseconds/tok would be 10 tokens per second per user, or ~450 words per minute, which is faster than a typical person can read.

    time_per_output_token_ms = 1 / avg_token_per_sec_tg * 1000

    # Latency: The overall time it takes for the model to generate the full response for a user. Overall response latency can be calculated using the previous two metrics: latency = (TTFT) + (TPOT) * (the number of tokens to be generated).

    latency_ms = time_to_first_token_ms + time_per_output_token_ms * NUM_OUTPUT_TOKENS

    # Throughput: The number of output tokens per second an inference server can generate across all users and requests.
    throughput = avg_token_per_sec_tg

    return {
        'time_to_first_token_ms': time_per_output_token_ms,
        'time_per_output_token_ms': time_per_output_token_ms,
        'latency_ms': latency_ms,
        'throughput_per_s': throughput
    }


def process_single_run(run_log_path: Path) -> dict:
    run_log = open(run_log_path, 'r')
    run_log_lines = [each.strip() for each in run_log.readlines()]
    benchmark_result_df = parse_performance_table(run_log_lines)
    result = convert_metric(benchmark_result_df)
    result['model_name'] = parse_model_name(run_log_lines)
    result['model_size'] = benchmark_result_df['size'].iloc[0]
    result['model_params'] = benchmark_result_df['params'].iloc[0]
    result['percent_battery_used'] = parse_battery_used(run_log_lines)
    result['test'] = run_log_path.stem
    return result


def generate_summary_table(run_log_dir: Path) -> pd.DataFrame:
    result = []
    for each in run_log_dir.glob('*.log'):
        result.append(process_single_run(each))
    result = pd.DataFrame(result)
    result = result[['test', 'model_name', 'model_size', 'model_params', 'time_to_first_token_ms', 'time_per_output_token_ms', 'latency_ms', 'throughput_per_s', 'percent_battery_used']]
    # Convert columns name to human readable format
    result.columns = ['Test', 'Model Name', 'Model Size', 'Model Params', 'Time To First Token (ms)', 'Time Per Output Token (ms)', 'Latency (ms)', 'Throughput (tokens/s)', 'Battery Used (%)']
    result = result.set_index('Test')
    # Dump to markdown compatible table
    result = result.to_markdown(index=True)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--run_log_dir', type=str, help='Path to all the run log file.', default='./run_logs')
    args = parser.parse_args()

    run_log_dir = Path(args.run_log_dir)
    result = generate_summary_table(run_log_dir)
    print(result)
