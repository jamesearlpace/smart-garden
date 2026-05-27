"""Fix chart axes: all charts on same page share the same time window."""
path = "/home/jamesearlpace/smart-garden-server/templates/index.html"
with open(path) as f:
    html = f.read()

# Add a shared time bounds helper
bounds_helper = """
// Compute shared time bounds for consistent chart axes
function getChartTimeBounds(hours) {
  var now = new Date();
  var min = new Date(now.getTime() - hours * 3600000);
  return {min: min, max: now};
}
"""
if "getChartTimeBounds" not in html:
    html = html.replace("function fillTimeGaps", bounds_helper + "\nfunction fillTimeGaps")
    print("Added getChartTimeBounds helper")

# Update battery chart to use shared bounds
html = html.replace(
    "x: { type: 'time', time: { tooltipFormat: 'MMM d, h:mm a',\n"
    "                displayFormats: { hour: 'ha', day: 'MMM d' } },\n"
    "                ticks: { maxTicksLimit: 8, font: { size: 10 } } },",

    "x: { type: 'time', time: { tooltipFormat: 'MMM d, h:mm a',\n"
    "                displayFormats: { hour: 'ha', day: 'MMM d' } },\n"
    "                min: getChartTimeBounds(hours).min, max: getChartTimeBounds(hours).max,\n"
    "                ticks: { maxTicksLimit: 8, font: { size: 10 } } },"
)
print("Updated battery chart with shared time bounds")

# Update miniLine health charts - need to pass a hours param
# The health charts are called from renderHealthCharts which gets data for a fixed period
# Add min/max to miniLine's x axis
html = html.replace(
    "x: { type: 'time', time: { tooltipFormat: 'h:mm a',\n"
    "                displayFormats: { hour: 'ha', minute: 'h:mm a' } },\n"
    "                ticks: { font: { size: 9 }, maxTicksLimit: 6 } },",

    "x: { type: 'time', time: { tooltipFormat: 'h:mm a',\n"
    "                displayFormats: { hour: 'ha', minute: 'h:mm a' } },\n"
    "                min: getChartTimeBounds(24).min, max: getChartTimeBounds(24).max,\n"
    "                ticks: { font: { size: 9 }, maxTicksLimit: 6 } },"
)
print("Updated health charts with shared time bounds")

with open(path, "w") as f:
    f.write(html)
print("Done!")
