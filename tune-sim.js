// Standalone simulation runner — tune parameters without browser round trips
// Usage: node tune-sim.js

var zone = { precipRate: 1.5, kc: 0.80, madPct: 50, wiltPct: 35, rootDepthIn: 6 };
var days = 30;

function mkRng(seed) {
  return function() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
}

// Same scenario as HTML
var scenario30 = [
  { hi: 62, lo: 44, maxWind: 5,  rainTomorrow: false, et0mult: 0.70 },
  { hi: 65, lo: 46, maxWind: 4,  rainTomorrow: true,  et0mult: 0.75 },
  { hi: 58, lo: 48, maxWind: 6,  rainTomorrow: false, et0mult: 0.55 },
  { hi: 64, lo: 45, maxWind: 4,  rainTomorrow: false, et0mult: 0.72 },
  { hi: 66, lo: 47, maxWind: 3,  rainTomorrow: false, et0mult: 0.78 },
  { hi: 60, lo: 49, maxWind: 7,  rainTomorrow: true,  et0mult: 0.60 },
  { hi: 56, lo: 47, maxWind: 8,  rainTomorrow: false, et0mult: 0.50 },
  { hi: 70, lo: 50, maxWind: 4,  rainTomorrow: false, et0mult: 0.88 },
  { hi: 72, lo: 52, maxWind: 5,  rainTomorrow: false, et0mult: 0.92 },
  { hi: 74, lo: 53, maxWind: 14, rainTomorrow: false, et0mult: 0.95 },
  { hi: 75, lo: 54, maxWind: 4,  rainTomorrow: false, et0mult: 1.00 },
  { hi: 73, lo: 52, maxWind: 5,  rainTomorrow: false, et0mult: 0.95 },
  { hi: 76, lo: 55, maxWind: 4,  rainTomorrow: false, et0mult: 1.02 },
  { hi: 71, lo: 51, maxWind: 6,  rainTomorrow: false, et0mult: 0.90 },
  { hi: 78, lo: 56, maxWind: 3,  rainTomorrow: false, et0mult: 1.05 },
  { hi: 84, lo: 60, maxWind: 4,  rainTomorrow: false, et0mult: 1.20 },
  { hi: 88, lo: 63, maxWind: 5,  rainTomorrow: false, et0mult: 1.30 },
  { hi: 86, lo: 62, maxWind: 3,  rainTomorrow: true,  et0mult: 1.25 },
  { hi: 72, lo: 56, maxWind: 6,  rainTomorrow: false, et0mult: 0.80 },
  { hi: 68, lo: 50, maxWind: 4,  rainTomorrow: false, et0mult: 0.75 },
  { hi: 70, lo: 48, maxWind: 5,  rainTomorrow: false, et0mult: 0.82 },
  { hi: 64, lo: 50, maxWind: 12, rainTomorrow: false, et0mult: 0.68 },
  { hi: 66, lo: 48, maxWind: 15, rainTomorrow: false, et0mult: 0.72 },
  { hi: 68, lo: 49, maxWind: 8,  rainTomorrow: true,  et0mult: 0.78 },
  { hi: 60, lo: 48, maxWind: 6,  rainTomorrow: false, et0mult: 0.55 },
  { hi: 70, lo: 50, maxWind: 4,  rainTomorrow: false, et0mult: 0.85 },
  { hi: 74, lo: 52, maxWind: 5,  rainTomorrow: false, et0mult: 0.95 },
  { hi: 76, lo: 54, maxWind: 4,  rainTomorrow: false, et0mult: 1.00 },
  { hi: 72, lo: 51, maxWind: 4,  rainTomorrow: false, et0mult: 0.90 },
  { hi: 74, lo: 53, maxWind: 5,  rainTomorrow: false, et0mult: 0.95 },
  { hi: 76, lo: 55, maxWind: 4,  rainTomorrow: false, et0mult: 1.00 },
  { hi: 73, lo: 52, maxWind: 4,  rainTomorrow: false, et0mult: 0.92 },
];

var rainEvents = [
  { day: 2,  hr: 10, dur: 5, depth: 0.20 },
  { day: 6,  hr: 13, dur: 3, depth: 0.10 },
  { day: 18, hr: 9,  dur: 6, depth: 0.25 },
  { day: 24, hr: 11, dur: 4, depth: 0.12 },
];

// ════════════════════════════════════════
// TUNABLE PARAMETERS — change these
// ════════════════════════════════════════
var DRAIN_BASE = 0.22;       // ET base rate
var ARM_DAYS_AHEAD = 1.0;    // arm this many days before MAD crossing
var ARM_MARGIN = 1.1;        // safety margin on arm threshold
var RECOVER_ABOVE_MAD = 20;  // recover to MAD + this
var RECOVER_TEMP_COEFF = 0.04;
var RECOVER_MAX = 80;
var STRESS_DELAY_MAX = 1;    // max hrs before stopping delay
var STRESS_DELAY_ABOVE_MAD = 5; // only delay if above MAD + this

function simulate() {
  var rng = mkRng(0 * 7919 + days * 31);
  var MAD_BASE = zone.madPct;
  var WILT_BASE = zone.wiltPct;
  var moisture = MAD_BASE + 18;
  var dailyWeather = scenario30.slice(0, days + 1);
  
  var armed = false, recovering = false, cycleTarget = 0;
  var cumulativeStressHrs = 0, lastWateredStep = -999;
  var stressSteps = 0, deepStressSteps = 0, waterEvents = 0;
  var decisions = [];
  var dailyDrainLog = [];
  var totalSprPct = 0;
  var cycles = [];
  
  var now = new Date();
  var start = new Date(now); start.setHours(0,0,0,0);
  start = new Date(start.getTime() - days * 86400000);
  var STEP = 15 * 60000;
  var prevDayDrain = 0, currentDayIdx = -1;
  
  for (var t = start.getTime(); t <= now.getTime(); t += STEP) {
    var d = new Date(t);
    var h = d.getHours(), m = d.getMinutes();
    var di = Math.floor((t - start.getTime()) / 86400000);
    var stepIdx = Math.floor((t - start.getTime()) / STEP);
    
    if (di !== currentDayIdx) {
      if (currentDayIdx >= 0) dailyDrainLog.push({ day: currentDayIdx, drain: prevDayDrain.toFixed(2) });
      prevDayDrain = 0;
      currentDayIdx = di;
    }
    
    var wx = dailyWeather[di] || dailyWeather[dailyWeather.length - 1];
    var tempPhase = (h + m / 60 - 5) / 24 * 2 * Math.PI;
    var tempF = (wx.hi + wx.lo) / 2 + (wx.hi - wx.lo) / 2 * Math.sin(tempPhase - Math.PI / 2);
    var windPhase = (h + m / 60 - 3) / 24 * 2 * Math.PI;
    var windMph = wx.maxWind * Math.max(0, Math.sin(windPhase - Math.PI / 2)) * 0.7 + wx.maxWind * 0.15;
    if (h >= 22 || h < 6) windMph = wx.maxWind * 0.1;
    
    var tempDelta = (tempF - 70) / 10;
    var madNow = Math.max(38, Math.min(62, MAD_BASE + tempDelta * 3));
    var wiltNow = Math.max(22, Math.min(madNow - 10, WILT_BASE + tempDelta * 2));
    
    // Drain
    var drain = 0;
    if (h >= 6 && h <= 20) {
      var phase = (h + m / 60 - 6) / 14 * Math.PI;
      var tempBoost = 1 + Math.max(0, tempF - 72) * 0.01;
      var windBoost = 1 + Math.max(0, windMph - 5) * 0.005;
      drain = Math.sin(phase) * DRAIN_BASE * zone.kc * (wx.et0mult || 1) * tempBoost * windBoost;
    }
    moisture -= drain;
    prevDayDrain += drain;
    
    // Rain
    var rain = 0;
    var stepInDay = h * 4 + Math.floor(m / 15);
    for (var ri = 0; ri < rainEvents.length; ri++) {
      var re = rainEvents[ri];
      if (di === re.day && stepInDay >= re.hr * 4 && stepInDay < re.hr * 4 + re.dur) {
        rain = (re.depth / re.dur) * 100;
      }
    }
    
    // Track stress
    if (moisture < madNow && moisture >= wiltNow) { stressSteps++; cumulativeStressHrs += 0.25; }
    if (moisture < wiltNow) { deepStressSteps++; cumulativeStressHrs += 0.5; }
    
    // Sprinkler
    var sprinkler = 0;
    var dailyDrain_est = DRAIN_BASE * zone.kc * (wx.et0mult || 1) * 56 * 0.637;
    var armThreshold = madNow + dailyDrain_est * ARM_MARGIN;
    var shouldArm = !armed && !recovering && moisture <= armThreshold;
    if (shouldArm) armed = true;
    
    if (armed && h >= 4 && h < 6 && !recovering) {
      // Simplified: skip wind/rain checks for tuning, just water
      var rainExpected = false;
      if (di > 0 && dailyWeather[di - 1] && dailyWeather[di - 1].rainTomorrow) rainExpected = true;
      for (var rci = 0; rci < rainEvents.length; rci++) {
        if (rainEvents[rci].day === di || rainEvents[rci].day === di + 1) rainExpected = true;
      }
      
      if (windMph > 10) {
        // skip
      } else if (rainExpected && moisture > madNow - 3) {
        // skip for rain
      } else if (!rainExpected && cumulativeStressHrs < STRESS_DELAY_MAX && moisture > madNow + STRESS_DELAY_ABOVE_MAD) {
        // delay for stress
      } else if (!rainExpected) {
        recovering = true;
        var extraDepth = Math.max(0, (tempF - 65)) * RECOVER_TEMP_COEFF;
        cycleTarget = madNow + RECOVER_ABOVE_MAD + extraDepth + rng() * 2;
        cycleTarget = Math.min(RECOVER_MAX, cycleTarget);
        waterEvents++;
      }
    }
    
    if (recovering) {
      if (moisture < cycleTarget) {
        sprinkler = (zone.precipRate / 4) * (100 / zone.rootDepthIn);
        if (moisture + sprinkler > cycleTarget) sprinkler = cycleTarget - moisture;
      }
      if (moisture + sprinkler >= cycleTarget || h >= 6) {
        recovering = false; armed = false;
        cumulativeStressHrs = 0; lastWateredStep = stepIdx;
        cycles.push(stepIdx);
      }
    }
    
    totalSprPct += sprinkler;
    moisture = Math.min(100, Math.max(0, moisture + rain + sprinkler));
  }
  
  // Compute stats
  var cycleDays = 0;
  if (cycles.length > 1) {
    var tot = 0;
    for (var c = 1; c < cycles.length; c++) tot += (cycles[c] - cycles[c-1]) * 15 / 60 / 24;
    cycleDays = tot / (cycles.length - 1);
  }
  var stressHrs = stressSteps * 0.25;
  var deepStressHrs = deepStressSteps * 0.25;
  var stressPerCycle = cycles.length > 0 ? stressHrs / cycles.length : 0;
  var depthPerCycle = cycles.length > 0 ? totalSprPct / 100 * 6 / cycles.length : 0;
  
  return {
    cycles: cycles.length,
    cycleDays: cycleDays.toFixed(1),
    stressPerCycle: stressPerCycle.toFixed(1),
    deepStressHrs: deepStressHrs.toFixed(1),
    depthPerCycle: depthPerCycle.toFixed(2),
    totalStressHrs: stressHrs.toFixed(1),
    finalMoisture: moisture.toFixed(1)
  };
}

// ════════════════════════════════════════
// Run parameter sweep
// ════════════════════════════════════════
console.log("Target: cycle 2-4d, stress/cycle 1-4h, deep 0h, depth 0.5-0.75\"");
console.log("═══════════════════════════════════════════════════════════════");

var combos = [
  { drain: 0.18, recov: 20, arm: 1.3, label: "d18 r+20 a1.3 ★" },
  { drain: 0.20, recov: 18, arm: 1.3, label: "d20 r+18 a1.3" },
  { drain: 0.20, recov: 20, arm: 1.3, label: "d20 r+20 a1.3" },
  { drain: 0.22, recov: 20, arm: 1.1, label: "d22 r+20 a1.1 (current)" },
];

combos.forEach(function(c) {
  DRAIN_BASE = c.drain;
  RECOVER_ABOVE_MAD = c.recov;
  ARM_MARGIN = c.arm;
  var r = simulate();
  var ok = parseFloat(r.cycleDays) >= 2 && parseFloat(r.cycleDays) <= 4
        && parseFloat(r.stressPerCycle) >= 1 && parseFloat(r.stressPerCycle) <= 4
        && parseFloat(r.deepStressHrs) == 0
        && parseFloat(r.depthPerCycle) >= 0.5 && parseFloat(r.depthPerCycle) <= 0.75;
  console.log(
    (ok ? "✅" : "  ") + " " + c.label.padEnd(30) +
    " cycle:" + r.cycleDays + "d" +
    " stress:" + r.stressPerCycle + "h/cyc" +
    " deep:" + r.deepStressHrs + "h" +
    " depth:" + r.depthPerCycle + "\"" +
    " n=" + r.cycles
  );
});
