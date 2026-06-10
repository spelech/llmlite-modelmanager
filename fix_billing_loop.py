with open("main.py", "r") as f:
    content = f.read()

# I will replace the entire loop block
old_loop = 'for s in skus:\n                short_id = \'\'\n                desc = s.get("description", "")'
new_loop = 'for s in skus:\n                desc = s.get("description", "")'
content = content.replace(old_loop, new_loop)

# Also ensure short_id is not used outside the if
content = content.replace('models_data[short_id]["pricing"]', 'models_data[short_id]["pricing"]')

with open("main.py", "w") as f:
    f.write(content)
