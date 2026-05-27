path = "/home/jamesearlpace/smart-garden-server/templates/index.html"
with open(path) as f:
    html = f.read()
# Sidebar nav
old_sidebar = 'data-panel="settings"><span class="icon">&#x2699;&#xFE0F;</span> Settings</div>'
if "Forecast</a>" not in html:
    html = html.replace(
        'data-panel="settings"><span class="icon">\u2699\ufe0f</span> Settings</div>',
        'data-panel="settings"><span class="icon">\u2699\ufe0f</span> Settings</div>\n    <a href="/forecast" class="nav-item" style="text-decoration:none;color:inherit"><span class="icon">\U0001f327\ufe0f</span> Forecast</a>'
    )
    # Mobile nav
    html = html.replace(
        'data-panel="settings"><span class="mob-icon">\u2699\ufe0f</span>Settings</div>',
        'data-panel="settings"><span class="mob-icon">\u2699\ufe0f</span>Settings</div>\n    <a href="/forecast" class="mob-nav-item" style="text-decoration:none;color:inherit"><span class="mob-icon">\U0001f327\ufe0f</span>Forecast</a>'
    )
    with open(path, "w") as f:
        f.write(html)
    print("Added Forecast link to sidebar and mobile nav")
else:
    print("Forecast link already exists")
