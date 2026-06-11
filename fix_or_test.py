import re
with open("main.py", "r") as f:
    content = f.read()

# I am using os.environ.get('OPENROUTER_API_KEY') in the test endpoint.
# Let me make sure it is correctly used.
# Wait, I noticed earlier OpenRouter returned 401 "User not found".
# This often happens if the 'Authorization' header is malformed or key is invalid.
# I will check the key.

# Also, I will add logic to check if PROJECT should be global.
# But for now, let's fix the header and double headers.
