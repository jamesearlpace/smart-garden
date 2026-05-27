"""Fix chart time axes to show gaps during outages.

Changes:
1. Add chartjs-adapter-date-fns CDN script
2. Update loadBatteryChart to use time scale + spanGaps:false + null gaps
3. Update miniLine (health charts) same way
4. Add gap-filling logic: insert null points when gap > 10min
"""
path = "/home/jamesearlpace/smart-garden-server/templates/index.html"
with open(path) as f:
    html = f.read()

# 1. Add date adapter after chart.js CDN
if "chartjs-adapter" not in html:
    html = html.replace(
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>',
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js"></script>'
    )
    print("Added chartjs-adapter-date-fns")

# 2. Add gap-fill helper function (insert nulls in data gaps)
gap_helper = """
// Insert null data points in gaps > threshold to break the line
function fillTimeGaps(timestamps, values, gapMinutes) {
  gapMinutes = gapMinutes || 15;
  var out = [];
  for (var i = 0; i < timestamps.length; i++) {
    if (i > 0) {
      var prev = new Date(timestamps[i-1]).getTime();
      var cur = new Date(timestamps[i]).getTime();
      if ((cur - prev) > gapMinutes * 60000) {
        // Insert null point 1 minute after last good point
        out.push({x: new Date(prev + 60000), y: null});
      }
    }
    out.push({x: new Date(timestamps[i]), y: values[i]});
  }
  return out;
}
"""
if "fillTimeGaps" not in html:
    # Insert before loadBatteryChart
    html = html.replace("function loadBatteryChart", gap_helper + "\nfunction loadBatteryChart")
    print("Added fillTimeGaps helper")

# 3. Replace loadBatteryChart with time-scale version
old_battery_fn = """function loadBatteryChart(canvasId, url, hours) {
  fetch(url).then(function(r){return r.json();}).then(function(data) {
    var hasData = data.some(function(r){ return r.battery_v != null; });
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    if (!hasData) {
      canvas.style.display = 'none';
      var ph = canvas.parentElement;
      if (!ph.querySelector('.no-data-msg')) {
        var d = document.createElement('div');
        d.className = 'no-data-msg';
        d.style.cssText = 'text-align:center;color:var(--text3);font-size:.8rem;padding:40px 0';
        d.innerHTML = '<div style="font-size:1.5rem;margin-bottom:4px">\U0001f50b</div>No battery data yet \u2014 ESP32 reporting null.<br>Needs ADC wiring to battery divider.';
        ph.appendChild(d);
      }
      return;
    }
    canvas.style.display = '';
    var labels = data.map(function(r){
      var d2 = new Date(r.ts);
      if (hours <= 24) return d2.toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'});
      return (d2.getMonth()+1)+'/'+d2.getDate()+' '+d2.toLocaleTimeString('en-US',{hour:'numeric'});
    });
    var volts = data.map(function(r){ return r.battery_v; });
    if (_ddCharts[canvasId]) _ddCharts[canvasId].destroy();
    _ddCharts[canvasId] = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels: labels, datasets: [{
        label: 'Battery (V)', data: volts, borderColor: '#22c55e', backgroundColor: '#22c55e15',
        borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3
      }]},
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { display: true, ticks: { maxTicksLimit: 8, font: { size: 10 } } },
                  y: { title: { display: true, text: 'Volts' } } }
      }
    });
  });
}"""

new_battery_fn = """function loadBatteryChart(canvasId, url, hours) {
  fetch(url).then(function(r){return r.json();}).then(function(data) {
    var hasData = data.some(function(r){ return r.battery_v != null; });
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    if (!hasData) {
      canvas.style.display = 'none';
      var ph = canvas.parentElement;
      if (!ph.querySelector('.no-data-msg')) {
        var d = document.createElement('div');
        d.className = 'no-data-msg';
        d.style.cssText = 'text-align:center;color:var(--text3);font-size:.8rem;padding:40px 0';
        d.innerHTML = '<div style="font-size:1.5rem;margin-bottom:4px">\U0001f50b</div>No battery data yet.';
        ph.appendChild(d);
      }
      return;
    }
    canvas.style.display = '';
    var timestamps = data.map(function(r){ return r.ts; });
    var volts = data.map(function(r){ return r.battery_v; });
    var pts = fillTimeGaps(timestamps, volts, 15);
    if (_ddCharts[canvasId]) _ddCharts[canvasId].destroy();
    _ddCharts[canvasId] = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [{
        label: 'Battery (V)', data: pts, borderColor: '#22c55e', backgroundColor: '#22c55e15',
        borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3, spanGaps: false
      }]},
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { type: 'time', time: { tooltipFormat: 'MMM d, h:mm a',
                displayFormats: { hour: 'ha', day: 'MMM d' } },
                ticks: { maxTicksLimit: 8, font: { size: 10 } } },
          y: { title: { display: true, text: 'Volts' } }
        }
      }
    });
  });
}"""

if old_battery_fn in html:
    html = html.replace(old_battery_fn, new_battery_fn)
    print("Updated loadBatteryChart to time scale with gap detection")
else:
    print("WARNING: Could not find loadBatteryChart to replace - may need manual fix")

# 4. Update miniLine health charts
old_miniline = """  function miniLine(canvasId, name, values, color, unit) {
    var ctx = document.getElementById(canvasId);
    if (!ctx) return;
    HEALTH_CHARTS[name] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{ data: values, borderColor: color, backgroundColor: color + '20',
          borderWidth: 2, pointRadius: 2, tension: 0.3, fill: true }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { font: { size: 9 }, maxTicksLimit: 6 } },
          y: { ticks: { font: { size: 9 } }, title: { display: true, text: unit, font: { size: 9 } } }
        }
      }
    });
  }"""

new_miniline = """  function miniLine(canvasId, name, values, color, unit) {
    var ctx = document.getElementById(canvasId);
    if (!ctx) return;
    var timestamps = data.map(function(h){ return h.ts; });
    var pts = fillTimeGaps(timestamps, values, 15);
    HEALTH_CHARTS[name] = new Chart(ctx, {
      type: 'line',
      data: {
        datasets: [{ data: pts, borderColor: color, backgroundColor: color + '20',
          borderWidth: 2, pointRadius: 2, tension: 0.3, fill: true, spanGaps: false }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { type: 'time', time: { tooltipFormat: 'h:mm a',
                displayFormats: { hour: 'ha', minute: 'h:mm a' } },
                ticks: { font: { size: 9 }, maxTicksLimit: 6 } },
          y: { ticks: { font: { size: 9 } }, title: { display: true, text: unit, font: { size: 9 } } }
        }
      }
    });
  }"""

if old_miniline in html:
    html = html.replace(old_miniline, new_miniline)
    print("Updated miniLine to time scale with gap detection")
else:
    print("WARNING: Could not find miniLine to replace - may need manual fix")

with open(path, "w") as f:
    f.write(html)
print("Done!")
