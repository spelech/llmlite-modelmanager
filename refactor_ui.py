import re

with open("app/templates/index.html", "r") as f:
    content = f.read()

# 1. Update Layout CSS
layout_css = """
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
            line-height: 1.6; 
            color: var(--text-main); 
            background-color: var(--bg-body);
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }

        header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            padding: 10px 20px; 
            background: var(--bg-card);
            border-bottom: 1px solid var(--border); 
            flex-shrink: 0;
        }
        header h1 { margin: 0; font-size: 1.4em; border: none; padding: 0; }
        .header-actions { display: flex; align-items: center; gap: 20px; margin: 0; }
        .header-version { font-size: 0.8em; color: var(--text-dim); }

        .main-layout {
            display: flex;
            flex-grow: 1;
            overflow: hidden;
        }

        /* Sidebar */
        .sidebar {
            width: 280px;
            background: var(--bg-card);
            border-right: 1px solid var(--border);
            padding: 20px;
            overflow-y: auto;
            flex-shrink: 0;
        }

        .content-area {
            flex-grow: 1;
            padding: 20px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        .container { 
            display: flex; 
            gap: 20px; 
            height: 100%;
            overflow: hidden;
        }
        
        .column { 
            flex: 1; 
            background: var(--bg-card); 
            padding: 15px; 
            border-radius: 8px; 
            border: 1px solid var(--border); 
            display: flex; 
            flex-direction: column; 
            overflow: hidden; 
        }
        .column h2 { font-size: 1.2em; margin-bottom: 10px; }
"""

# Replace old layout CSS
content = re.sub(r"body {.*?\.column h2 {.*?}", layout_css, content, flags=re.DOTALL)

# 2. Reconstruct Body Structure
# Remove misplaced header/styles if they still exist at the bottom
content = re.sub(r"<header>.*?</style>", "", content, flags=re.DOTALL)

body_start = """<body>
    <header>
        <h1>LiteLLM Model Manager</h1>
        <div class="header-actions">
            <button type="button" class="btn-refresh" onclick="forceRefresh()">Force Metadata Refresh</button>
            <div class="header-version">v{{ version }} | {{ build_time }}</div>
        </div>
    </header>

    <div class="main-layout">
        <div class="sidebar">
            <h2>Filters</h2>
            <div class="filter-group">
                <span class="filter-label">Wildcard Search</span>
                <input type="text" id="globalSearch" placeholder="e.g. gemini*flash" onkeyup="applyAllFilters()">
            </div>

            <div class="filter-group" style="margin-top: 20px;">
                <span class="filter-label">Brand</span>
                <select id="brandFilter" onchange="applyAllFilters()">
                    <option value="all">All Brands</option>
                </select>
            </div>

            <div class="filter-group" style="margin-top: 20px;">
                <span class="filter-label">Max In Price (1M)</span>
                <input type="number" id="maxInPrice" step="0.1" placeholder="Any" onchange="applyAllFilters()">
            </div>

            <div class="filter-group" style="margin-top: 20px;">
                <span class="filter-label">Max Out Price (1M)</span>
                <input type="number" id="maxOutPrice" step="0.1" placeholder="Any" onchange="applyAllFilters()">
            </div>

            <div class="filter-group" style="margin-top: 20px;">
                <span class="filter-label">Capabilities</span>
                <div class="checkbox-group" style="flex-direction: column; gap: 10px;">
                    <label class="checkbox-item"><input type="checkbox" id="capImageIn" onchange="applyAllFilters()"> Vis In</label>
                    <label class="checkbox-item"><input type="checkbox" id="capImageOut" onchange="applyAllFilters()"> Vis Out</label>
                    <label class="checkbox-item"><input type="checkbox" id="capAudioIn" onchange="applyAllFilters()"> Aud In</label>
                    <label class="checkbox-item"><input type="checkbox" id="capAudioOut" onchange="applyAllFilters()"> Aud Out</label>
                    <label class="checkbox-item"><input type="checkbox" id="capFunc" onchange="applyAllFilters()"> Func</label>
                    <label class="checkbox-item"><input type="checkbox" id="filterSelected" onchange="applyAllFilters()"> Selected</label>
                </div>
            </div>
        </div>

        <div class="content-area">
            <form action="/sync" method="post" id="syncForm" style="height: 100%;">"""

# Replace everything from <body> to the start of the columns
content = re.sub(r"<body>.*?<form action=\"/sync\".*?>", body_start, content, flags=re.DOTALL)

# Close the new divs at the end of the form
content = content.replace("</form>", "</form>\n        </div>\n    </div>")

with open("app/templates/index.html", "w") as f:
    f.write(content)
