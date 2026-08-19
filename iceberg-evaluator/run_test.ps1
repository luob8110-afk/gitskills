$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$env:DASHSCOPE_API_KEY = "***"
$env:OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:OPENAI_MODEL = "qwen3.5-plus"

cd C:\Users\huangjialin\.openclaw\skill-workshop\iceberg-evaluator
python scripts/iceberg_evaluator.py --resume test_candidate_resume.txt --interview test_candidate_interview.json --benchmark test_benchmark.json --html output\test_fixed_evaluation.html
