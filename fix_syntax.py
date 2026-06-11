import re

with open("main.py", "r") as f:
    content = f.read()

# Completely rewrite the mangled block
mangled_pattern = r"FALLBACK_PRICING = {.*?}"
correct_block = """FALLBACK_PRICING = {
    "gemini-3.5-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.5-pro": {"prompt_1m": 3.50, "completion_1m": 10.50},
    "gemini-3.1-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
    "gemini-3.1-flash-lite": {"prompt_1m": 0.03, "completion_1m": 0.10},
    "gemini-2.5-flash": {"prompt_1m": 0.10, "completion_1m": 0.40},
    "gemini-2.5-pro": {"prompt_1m": 3.50, "completion_1m": 10.50},
    "gemini-2.0-flash": {"prompt_1m": 0.10, "completion_1m": 0.40},
    "gemini-1.5-pro": {"prompt_1m": 1.25, "completion_1m": 3.75},
    "gemini-1.5-flash": {"prompt_1m": 0.075, "completion_1m": 0.30},
}

GEMINI_SPECS = {
    "gemini-2.5-pro": {"ctx": 2000000, "out": 8192},
    "gemini-2.5-flash": {"ctx": 1000000, "out": 8192},
    "gemini-3.5-flash": {"ctx": 1000000, "out": 8192},
    "gemini-3.1-flash-lite": {"ctx": 1000000, "out": 8192},
    "gemini-2.0-flash-exp": {"ctx": 1048576, "out": 8192},
    "gemini-1.5-pro": {"ctx": 2097152, "out": 8192},
    "gemini-1.5-flash": {"ctx": 1048576, "out": 8192},
}"""

content = re.sub(mangled_pattern, correct_block, content, flags=re.DOTALL)

with open("main.py", "w") as f:
    f.write(content)
