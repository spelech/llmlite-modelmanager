with open("main.py", "r") as f:
    content = f.read()

# Add a print statement in the check function
# Using regex to match the check function content more reliably
import re
new_content = re.sub(r'if resp\.status_code == 200: return m_data', 'if resp.status_code == 200: print(f"DEBUG: Verified model: {m_data[\'id\']}"); return m_data', content)

with open("main.py", "w") as f:
    f.write(new_content)
