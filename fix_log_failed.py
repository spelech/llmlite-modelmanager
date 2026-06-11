with open("main.py", "r") as f:
    content = f.read()

# I am replacing the print line with a more verbose one
old_line = 'if resp.status_code == 200: print(f"DEBUG: Verified model: {m_data[\'id\']}"); return m_data'
new_line = 'if resp.status_code == 200: print(f"DEBUG: Verified model: {m_data[\'id\']}"); return m_data\n                        else: print(f"DEBUG: Model {m_data[\'id\']} failed ping: {resp.status_code} - {resp.text}")'

content = content.replace(old_line, new_line)
with open("main.py", "w") as f:
    f.write(content)
