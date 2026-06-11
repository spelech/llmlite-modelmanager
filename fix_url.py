with open("main.py", "r") as f:
    content = f.read()
# Replace the URL base
old_url = 'f"https://{DEFAULT_LOCATION}-aiplatform.googleapis.com/v1/projects/{DEFAULT_PROJECT}/locations/{DEFAULT_LOCATION}/publishers/google/models"'
new_url = 'f"https://aiplatform.googleapis.com/v1/projects/{DEFAULT_PROJECT}/locations/{DEFAULT_LOCATION}/publishers/google/models"'
content = content.replace(old_url, new_url)
with open("main.py", "w") as f:
    f.write(content)
