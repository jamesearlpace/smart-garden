// ═══════════════════════════════════════════════════════════════
// Smart Garden: 90-Day PNW Summer Simulation (Jun 1 – Aug 29)
// 
// Step 1: Generate realistic weather (independent of irrigation)
// Step 2: Run irrigation logic on top of it
// Step 3: Report stats and decisions
// 
// If the logic can't produce good results on realistic weather,
// the logic is wrong — not the weather.
// ═══════════════════════════════════════════════════════════════

// ─── Realistic PNW Summer Weather Generator ───
// Based on Duvall, WA climate normals:
//   June: highs 65-75, lows 48-55, ET₀ 0.12-0.18"/day, rain 1.5"
//   July: highs 72-82, lows 52-58, ET₀ 0.18-0.25"/day, rain 0.7"
//   August: highs 72-80, lows 52-56, ET₀ 0.16-0.22"/day, rain 0.9"
//   Heat waves: 3-5 days above 85°F, 1-2 per summer
//   Rain: 4-6 events in June, 1-3 in July, 2-4 in August

function generatePNWSummer() {
  var days = [];
  var rainEvents = [];
  
  // Seed for reproducibility
  var seed = 42;
  function rng() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
  
  for (var d = 0; d < 90; d++) {
    var month = d < 30 ? 0 : d < 61 ? 1 : 2; // Jun=0, Jul=1, Aug=2
    var dayInMonth = d < 30 ? d : d < 61 ? d - 30 : d - 61;
    
    // Base temperatures by month (gradually warming Jun→Jul, cooling Jul→Aug)
    var seasonalHigh = [68, 77, 75][month];
    var seasonalLow = [50, 54, 53][month];
    // Add daily variation (±5°F)
    var hi = seasonalHigh + (rng() - 0.5) * 10;
    var lo = seasonalLow + (rng() - 0.5) * 8;
    lo = Math.min(lo, hi - 12); // ensure reasonable spread
    
    // Heat wave injection: day 20-23 (late June) and day 50-53 (late July)
    if ((d >= 20 && d <= 23) || (d >= 50 && d <= 53)) {
      hi += 12 + rng() * 5; // push to 85-95°F
      lo += 5;
    }
    
    // Wind: mostly calm (3-6 mph), occasional windy days
    var maxWind = 3 + rng() * 4;
    if (rng() > 0.85) maxWind = 10 + rng() * 10; // 15% chance of windy (10-20 mph)
    
    // ET₀ multiplier: correlates with temperature and cloud cover
    var et0base = [0.80, 1.00, 0.95][month];
    var et0mult = et0base + (rng() - 0.4) * 0.3; // vary ±0.15
    if (hi > 85) et0mult *= 1.15; // hot days = more ET
    et0mult = Math.max(0.4, Math.min(1.4, et0mult));
    
    days.push({
      day: d, hi: Math.round(hi), lo: Math.round(lo),
      maxWind: Math.round(maxWind * 10) / 10,
      et0mult: Math.round(et0mult * 100) / 100,
      rainTomorrow: false // filled in below
    });
  }
  
  // ── Rain events ──
  // June: 4-5 events, 0.1-0.4" each
  var juneRains = 4 + Math.floor(rng() * 2);
  for (var r = 0; r < juneRains; r++) {
    var day = Math.floor(rng() * 28) + 1;
    rainEvents.push({ day: day, hr: 8 + Math.floor(rng() * 8), dur: 2 + Math.floor(rng() * 5), depth: 0.08 + rng() * 0.25 });
  }
  // July: 1-2 events, lighter
  var julyRains = 1 + Math.floor(rng() * 2);
  for (var r = 0; r < julyRains; r++) {
    var day = 30 + Math.floor(rng() * 28) + 1;
    rainEvents.push({ day: day, hr: 10 + Math.floor(rng() * 6), dur: 2 + Math.floor(rng() * 3), depth: 0.05 + rng() * 0.15 });
  }
  // August: 2-3 events
  var augRains = 2 + Math.floor(rng() * 2);
  for (var r = 0; r < augRains; r++) {
    var day = 61 + Math.floor(rng() * 27) + 1;
    rainEvents.push({ day: day, hr: 9 + Math.floor(rng() * 7), dur: 2 + Math.floor(rng() * 4), depth: 0.06 + rng() * 0.20 });
  }
  
  // Deduplicate same-day rain
  var seenDays = {};
  rainEvents = rainEvents.filter(function(r) {
    if (seenDays[r.day]) return false;
    seenDays[r.day] = true;
    return true;
  });
  
  // Set rainTomorrow flags
  rainEvents.forEach(function(r) {
    if (r.day > 0 && days[r.day - 1]) days[r.day - 1].rainTomorrow = true;
  });
  
  return { days: days, rainEvents: rainEvents };
}

// ─── Irrigation Brain ───
function runIrrigation(weather, zone, params) {
  var days = weather.days;
  var rainEvents = weather.rainEvents;
  var numDays = days.length;
  
  var MAD_BASE = zone.madPct;
  var WILT_BASE = zone.wiltPct;
  var moisture = MAD_BASE + 20; // start healthy
  
  var armed = false, recovering = false, cycleTarget = 0;
  var cumulativeStressHrs = 0, lastWateredStep = -999;
  var stressSteps = 0, deepStressSteps = 0, totalSprPct = 0;
  var cycles = [], decisions = [];
  
  var STEP = 15; // minutes
  var stepsPerDay = 24 * 60 / STEP;
  
  for (var di = 0; di < numDays; di++) {
    var wx = days[di];
    var wxTomorrow = days[di + 1] || wx;
    
    for (var step = 0; step < stepsPerDay; step++) {
      var h = Math.floor(step * STEP / 60);
      var m = (step * STEP) % 60;
      var globalStep = di * stepsPerDay + step;
      
      // Temperature
      var tempPhase = (h + m / 60 - 5) / 24 * 2 * Math.PI;
      var tempF = (wx.hi + wx.lo) / 2 + (wx.hi - wx.lo) / 2 * Math.sin(tempPhase - Math.PI / 2);
      
      // Wind
      var windMph = wx.maxWind * Math.max(0, Math.sin((h + m/60 - 3) / 24 * 2 * Math.PI - Math.PI/2)) * 0.7 + wx.maxWind * 0.15;
      if (h >= 22 || h < 6) windMph = wx.maxWind * 0.1;
      
      // Dynamic thresholds
      var tempDelta = (tempF - 70) / 10;
      var madNow = Math.max(38, Math.min(62, MAD_BASE + tempDelta * 3));
      var wiltNow = Math.max(22, Math.min(madNow - 10, WILT_BASE + tempDelta * 2));
      
      // ── 1. ET₀ drain ──
      var drain = 0;
      if (h >= 6 && h <= 20) {
        var phase = (h + m / 60 - 6) / 14 * Math.PI;
        var tempBoost = 1 + Math.max(0, tempF - 72) * 0.01;
        var windBoost = 1 + Math.max(0, windMph - 5) * 0.005;
        drain = Math.sin(phase) * params.drainBase * zone.kc * (wx.et0mult || 1) * tempBoost * windBoost;
      }
      moisture -= drain;
      
      // ── 2. Rain ──
      var rain = 0;
      var stepInDay = h * 4 + Math.floor(m / 15);
      for (var ri = 0; ri < rainEvents.length; ri++) {
        var re = rainEvents[ri];
        if (di === re.day && stepInDay >= re.hr * 4 && stepInDay < re.hr * 4 + re.dur) {
          rain = (re.depth / re.dur) * 100;
        }
      }
      
      // ── Track stress ──
      if (moisture < madNow && moisture >= wiltNow) { stressSteps++; cumulativeStressHrs += 0.25; }
      if (moisture < wiltNow) { deepStressSteps++; cumulativeStressHrs += 0.5; }
      
      // ── 3. Sprinkler ──
      var sprinkler = 0;
      
      // Arm check
      var dailyDrain_est = params.drainBase * zone.kc * (wx.et0mult || 1) * 56 * 0.637;
      var armThreshold = madNow + dailyDrain_est * params.armMargin;
      if (!armed && !recovering && moisture <= armThreshold) armed = true;
      
      // Pre-emptive arm for heat
      if (!armed && !recovering && wxTomorrow.hi > 82 && moisture < armThreshold + 5 && h >= 18) {
        armed = true;
        decisions.push({ day: di, type: 'arm-preemptive', reason: 'Tomorrow ' + wxTomorrow.hi + '°F' });
      }
      
      // Water window
      if (armed && h >= 4 && h < 6 && !recovering) {
        // Wind check
        if (windMph > 10) {
          // skip
        } else {
          // Rain check
          var rainExpected = false;
          if (di > 0 && days[di - 1] && days[di - 1].rainTomorrow) rainExpected = true;
          for (var rci = 0; rci < rainEvents.length; rci++) {
            if (rainEvents[rci].day === di || rainEvents[rci].day === di + 1) rainExpected = true;
          }
          
          if (rainExpected && moisture > madNow - 3) {
            decisions.push({ day: di, type: 'skip-rain', reason: 'Moisture ' + moisture.toFixed(0) + '%' });
          } else if (!rainExpected) {
            // Stress delay check
            if (cumulativeStressHrs < params.stressDelayMax && moisture > madNow + params.stressDelayAboveMAD) {
              decisions.push({ day: di, type: 'skip-stress', reason: cumulativeStressHrs.toFixed(1) + 'h stress, soil ' + moisture.toFixed(0) + '%' });
            } else {
              // WATER
              recovering = true;
              var extraDepth = Math.max(0, (tempF - 65)) * params.recoverTempCoeff;
              cycleTarget = madNow + params.recoverAboveMAD + extraDepth;
              cycleTarget = Math.min(params.recoverMax, cycleTarget);
              decisions.push({ day: di, type: 'water', reason: moisture.toFixed(0) + '% → ' + cycleTarget.toFixed(0) + '%, ' + tempF.toFixed(0) + '°F' });
            }
          } else if (rainExpected && moisture <= madNow - 3) {
            recovering = true;
            cycleTarget = madNow + 14;
            decisions.push({ day: di, type: 'water-despite-rain', reason: 'Too dry at ' + moisture.toFixed(0) + '%' });
          }
        }
      }
      
      // Emergency
      if (!recovering && moisture <= wiltNow + 2 && h >= 3) {
        recovering = true;
        cycleTarget = madNow + 15;
        decisions.push({ day: di, type: 'EMERGENCY', reason: moisture.toFixed(0) + '% near wilt ' + wiltNow.toFixed(0) + '%' });
      }
      
      if (recovering) {
        if (moisture < cycleTarget) {
          sprinkler = (zone.precipRate / 4) * (100 / zone.rootDepthIn);
          if (moisture + sprinkler > cycleTarget) sprinkler = cycleTarget - moisture;
        }
        if (moisture + sprinkler >= cycleTarget || h >= 6) {
          recovering = false; armed = false;
          cumulativeStressHrs = 0; lastWateredStep = globalStep;
          cycles.push(globalStep);
        }
      }
      
      totalSprPct += sprinkler;
      moisture = Math.min(100, Math.max(0, moisture + rain + sprinkler));
    }
  }
  
  // Stats
  var cycleDays = 0;
  if (cycles.length > 1) {
    var tot = 0;
    for (var c = 1; c < cycles.length; c++) tot += (cycles[c] - cycles[c-1]) * 15 / 60 / 24;
    cycleDays = tot / (cycles.length - 1);
  }
  var stressHrs = stressSteps * 0.25;
  var deepStressHrs = deepStressSteps * 0.25;
  var stressPerCycle = cycles.length > 0 ? stressHrs / cycles.length : 0;
  var depthPerCycle = cycles.length > 0 ? totalSprPct / 100 * zone.rootDepthIn / cycles.length : 0;
  
  return {
    cycles: cycles.length,
    cycleDays: cycleDays.toFixed(1),
    stressPerCycle: stressPerCycle.toFixed(1),
    deepStressHrs: deepStressHrs.toFixed(1),
    depthPerCycle: depthPerCycle.toFixed(2),
    totalStressHrs: stressHrs.toFixed(1),
    decisions: decisions,
    finalMoisture: moisture.toFixed(1)
  };
}

// ═══════════════════════════════════════════════════
// RUN
// ═══════════════════════════════════════════════════
var weather = generatePNWSummer();
var zone = { precipRate: 1.5, kc: 0.80, madPct: 50, wiltPct: 35, rootDepthIn: 6 };

// Print weather summary
console.log("═══ 90-Day PNW Weather Summary (Jun 1 – Aug 29) ═══");
console.log("Rain events: " + weather.rainEvents.length);
weather.rainEvents.forEach(function(r) {
  var month = r.day < 30 ? 'Jun' : r.day < 61 ? 'Jul' : 'Aug';
  var dom = r.day < 30 ? r.day + 1 : r.day < 61 ? r.day - 29 : r.day - 60;
  console.log("  " + month + " " + dom + ": " + r.depth.toFixed(2) + '" over ' + (r.dur * 15) + ' min');
});
console.log("\nTemp range by month:");
[0, 30, 61].forEach(function(start, mi) {
  var end = [29, 60, 89][mi];
  var hiMax = 0, hiMin = 200, loMin = 200;
  for (var d = start; d <= end; d++) { 
    if (weather.days[d].hi > hiMax) hiMax = weather.days[d].hi;
    if (weather.days[d].hi < hiMin) hiMin = weather.days[d].hi;
    if (weather.days[d].lo < loMin) loMin = weather.days[d].lo;
  }
  console.log("  " + ['June','July','Aug'][mi] + ": highs " + hiMin + "-" + hiMax + "°F, lows " + loMin + "°F+");
});

// Parameter sweep
console.log("\n═══ Parameter Sweep ═══");
console.log("Target: cycle 2-4d, stress/cyc 2-8h, deep 0h, depth 0.5-0.75\"");
console.log("─────────────────────────────────────────────────────────────");

var paramSets = [
  { drainBase: 0.18, armMargin: 1.3, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 1, stressDelayAboveMAD: 5, label: "current (d18 r+20 a1.3)" },
  { drainBase: 0.18, armMargin: 1.5, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 1, stressDelayAboveMAD: 5, label: "d18 r+20 a1.5" },
  { drainBase: 0.18, armMargin: 2.0, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 1, stressDelayAboveMAD: 5, label: "d18 r+20 a2.0" },
  { drainBase: 0.20, armMargin: 1.3, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 1, stressDelayAboveMAD: 5, label: "d20 r+20 a1.3" },
  { drainBase: 0.20, armMargin: 1.5, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 1, stressDelayAboveMAD: 5, label: "d20 r+20 a1.5" },
  { drainBase: 0.20, armMargin: 2.0, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 1, stressDelayAboveMAD: 5, label: "d20 r+20 a2.0" },
  { drainBase: 0.22, armMargin: 1.3, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 1, stressDelayAboveMAD: 5, label: "d22 r+20 a1.3" },
  { drainBase: 0.22, armMargin: 1.5, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 1, stressDelayAboveMAD: 5, label: "d22 r+20 a1.5" },
  { drainBase: 0.22, armMargin: 2.0, recoverAboveMAD: 20, recoverTempCoeff: 0.04, recoverMax: 80, stressDelayMax: 0, stressDelayAboveMAD: 5, label: "d22 r+20 a2.0 nodelay" },
  { drainBase: 0.20, armMargin: 1.5, recoverAboveMAD: 22, recoverTempCoeff: 0.04, recoverMax: 82, stressDelayMax: 0, stressDelayAboveMAD: 5, label: "d20 r+22 a1.5 nodelay" },
  { drainBase: 0.20, armMargin: 1.5, recoverAboveMAD: 18, recoverTempCoeff: 0.04, recoverMax: 78, stressDelayMax: 0, stressDelayAboveMAD: 5, label: "d20 r+18 a1.5 nodelay" },
  { drainBase: 0.20, armMargin: 1.3, recoverAboveMAD: 18, recoverTempCoeff: 0.04, recoverMax: 78, stressDelayMax: 0, stressDelayAboveMAD: 5, label: "d20 r+18 a1.3 nodelay" },
];

paramSets.forEach(function(p) {
  var r = runIrrigation(weather, zone, p);
  var cd = parseFloat(r.cycleDays), sp = parseFloat(r.stressPerCycle);
  var dp = parseFloat(r.depthPerCycle), dh = parseFloat(r.deepStressHrs);
  var ok = cd >= 2 && cd <= 4 && sp >= 2 && sp <= 8 && dh == 0 && dp >= 0.5 && dp <= 0.75;
  console.log(
    (ok ? "✅" : "  ") + " " + p.label.padEnd(32) +
    " cyc:" + r.cycleDays.padStart(4) + "d" +
    " str:" + r.stressPerCycle.padStart(5) + "h" +
    " deep:" + r.deepStressHrs.padStart(5) + "h" +
    " dep:" + r.depthPerCycle.padStart(5) + '"' +
    " n=" + String(r.cycles).padStart(2) +
    " em=" + r.decisions.filter(function(d){return d.type==='EMERGENCY'}).length
  );
});

// Print decisions for best result
console.log("\n═══ Decision Log (current params) ═══");
var best = runIrrigation(weather, zone, paramSets[0]);
var typeCounts = {};
best.decisions.forEach(function(d) { typeCounts[d.type] = (typeCounts[d.type] || 0) + 1; });
console.log("Decision summary:", JSON.stringify(typeCounts));
console.log("\nAll decisions:");
best.decisions.forEach(function(d) {
  var month = d.day < 30 ? 'Jun' : d.day < 61 ? 'Jul' : 'Aug';
  var dom = d.day < 30 ? d.day + 1 : d.day < 61 ? d.day - 29 : d.day - 60;
  var icon = {water:'💧', 'skip-rain':'🌧️', 'skip-stress':'🌱', 'arm-preemptive':'🌡️', 'water-despite-rain':'⚠️', EMERGENCY:'🚨'}[d.type] || '📋';
  console.log("  " + icon + " " + month + " " + String(dom).padStart(2) + " [" + d.type.padEnd(20) + "] " + d.reason);
});
