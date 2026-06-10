import re
with open("main.py", "r") as f:
    content = f.read()

# I will find the START of FALLBACK_PRICING and the START of extract_capabilities
start_match = re.search(r"FALLBACK_PRICING = {", content)
end_match = re.search(r"def extract_capabilities", content)

if start_match and end_match:
    prefix = content[:start_match.start()]
    suffix = content[end_match.start():]
    
    middle = """FALLBACK_PRICING = {
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
}

"""
    with open("main.py", "w") as f:
        f.write(prefix + middle + suffix)
    print("Fixed.")
else:
    print("Could not find start/end.")
