with open("main.py", "r") as f:
    content = f.read()

# Add short_id initialization
content = content.replace("for s in skus:", "for s in skus:\n                short_id = ''")
with open("main.py", "w") as f:
    f.write(content)
