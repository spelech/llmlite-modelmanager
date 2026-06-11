import re

with open("app/templates/index.html", "r") as f:
    html = f.read()

# 1. Update OpenRouter list to group by brand
# I will use a custom jinja2 filter or just manual loop.
# Since I cannot easily add custom filters to Jinja2 from here, 
# I will use a grouped data structure in the context or manual grouping in template.

# Manual grouping in template:
old_loop = '''                    {% for m in or_models %}
                    <div class="model-item"'''

new_loop = '''                    {% set current_brand = "" %}
                    {% for m in or_models %}
                    {% if m.brand != current_brand %}
                        <h3 class="brand-group-header">{{ m.brand | upper }}</h3>
                        {% set current_brand = m.brand %}
                    {% endif %}
                    <div class="model-item"'''

# 2. Add Brand Header CSS
brand_css = """
        .brand-group-header {
            grid-column: 1 / -1;
            font-size: 0.75em;
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 2px;
            margin: 20px 0 10px 0;
            padding-bottom: 5px;
            border-bottom: 1px solid var(--border);
            opacity: 0.8;
        }
"""
html = html.replace("</style>", brand_css + "\n    </style>")

# Replace the loop
html = html.replace(old_loop, new_loop)

with open("app/templates/index.html", "w") as f:
    f.write(html)
