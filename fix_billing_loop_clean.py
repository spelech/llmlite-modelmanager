with open("main.py", "r") as f:
    content = f.read()

# Pattern for the old faulty loop
old_pattern = r'for s in skus:.*?pricing_info = s\.get\("pricingInfo", \[{}\]\)\[0\].get\("pricingExpression", {}\)'
# This is hard to replace with regex because of newlines.
# I will manually edit it in main.py using replace.
