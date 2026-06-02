// ═══════════════════════════════════════════════════════════════
// Smart Garden: REAL WEATHER test — Duvall WA 2025 May-Sep
// Pulls actual historical data from Open-Meteo, runs tier-5 logic
// ═══════════════════════════════════════════════════════════════

const https = require('https');

function fetchJSON(url) {
  return new Promise((resolve, reject) => {
    https.get(url, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch(e) { reject(new Error('JSON parse failed: ' + data.substring(0, 200))); }
      });
    }).on('error', reject);
  });
}

async function main() {
  // ── 1. Fetch real weather ──
  console.log("Fetching Duvall WA 2025 weather (May 1 – Sep 30)...");
  
  const lat = 47.7382, lon = -121.9856; // Duvall WA
  const url = `https://archive-api.open-meteo.com/v1/archive?` +
    `latitude=${lat}&longitude=${lon}` +
    `&start_date=2025-05-01&end_date=2025-09-30` +
    `&daily=et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min,wind_speed_10m_max` +
    `&hourly=temperature_2m,wind_speed_10m,precipitation` +
    `&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch` +
    `&timezone=America/Los_Angeles`;
  
  const wx = await fetchJSON(url);
  
  if (!wx.daily || !wx.hourly) {
    console.error("API error:", JSON.stringify(wx).substring(0, 500));
    return;
  }
  
  const numDays = wx.daily.time.length;
  console.log(`Got ${numDays} days of data (${wx.daily.time[0]} to ${wx.daily.time[numDays-1]})`);
  
  // ── Weather summary ──
  console.log("\n═══ Weather Summary ═══");
  const months = ['May','Jun','Jul','Aug','Sep'];
  for (let mi = 0; mi < 5; mi++) {
    const mStart = [0, 31, 61, 92, 123][mi];
    const mEnd = [30, 60, 91, 122, 152][mi];
    let hiMax = -999, hiMin = 999, et0Total = 0, rainTotal = 0, rainDays = 0;
    for (let d = mStart; d <= Math.min(mEnd, numDays-1); d++) {
      const hi = wx.daily.temperature_2m_max[d];
      if (hi > hiMax) hiMax = hi;
      if (hi < hiMin) hiMin = hi;
      et0Total += wx.daily.et0_fao_evapotranspiration[d] || 0;
      const rain = wx.daily.precipitation_sum[d] || 0;
      rainTotal += rain;
      if (rain > 0.01) rainDays++;
    }
    console.log(`  ${months[mi]}: highs ${Math.round(hiMin)}-${Math.round(hiMax)}°F, ET₀ ${et0Total.toFixed(2)}", rain ${rainTotal.toFixed(2)}" (${rainDays} days)`);
  }
  
  // Count heat events
  let heatDays = 0, windDays = 0;
  for (let d = 0; d < numDays; d++) {
    if (wx.daily.temperature_2m_max[d] > 85) heatDays++;
    if (wx.daily.wind_speed_10m_max[d] > 10) windDays++;
  }
  console.log(`  Heat days (>85°F): ${heatDays}`);
  console.log(`  Windy days (>10 mph): ${windDays}`);
  
  // ── 2. Build daily weather array ──
  const dailyWeather = [];
  for (let d = 0; d < numDays; d++) {
    const et0_mm = wx.daily.et0_fao_evapotranspiration[d] || 0;
    // Convert ET₀ from inches to a multiplier relative to 0.15"/day baseline
    const et0mult = (et0_mm / 0.15);
    
    dailyWeather.push({
      date: wx.daily.time[d],
      hi: wx.daily.temperature_2m_max[d],
      lo: wx.daily.temperature_2m_min[d],
      maxWind: wx.daily.wind_speed_10m_max[d],
      et0_in: et0_mm,
      et0mult: Math.max(0.3, Math.min(2.0, et0mult)),
      rainTotal: wx.daily.precipitation_sum[d] || 0,
      rainTomorrow: (d + 1 < numDays && (wx.daily.precipitation_sum[d+1] || 0) > 0.02)
    });
  }
  
  // Build rain events from hourly data
  const rainEvents = [];
  for (let d = 0; d < numDays; d++) {
    // Check hourly precip for this day
    const dayStart = d * 24;
    let rainStart = -1, rainDur = 0, rainDepth = 0;
    for (let h = 0; h < 24; h++) {
      const idx = dayStart + h;
      const precip = wx.hourly.precipitation[idx] || 0;
      if (precip > 0.005) {
        if (rainStart < 0) rainStart = h;
        rainDur++;
        rainDepth += precip;
      } else if (rainStart >= 0) {
        // End of rain event
        if (rainDepth > 0.02) {
          rainEvents.push({ day: d, hr: rainStart, dur: rainDur * 4, depth: rainDepth }); // dur in 15-min steps
        }
        rainStart = -1; rainDur = 0; rainDepth = 0;
      }
    }
    // Close any open event
    if (rainStart >= 0 && rainDepth > 0.02) {
      rainEvents.push({ day: d, hr: rainStart, dur: rainDur * 4, depth: rainDepth });
    }
  }
  console.log(`\nRain events extracted: ${rainEvents.length}`);
  
  // ── 3. Tier 5 Irrigation Brain ──
  function runTier5(params) {
    const zone = { precipRate: 1.5, kc_schedule: params.kcSchedule, madPct: 50, wiltPct: 35, rootDepthIn: 6 };
    let moisture = 70; // start healthy
    let armed = false, recovering = false, cycleTarget = 0;
    let cumulativeStressHrs = 0, lastWateredDay = -99;
    let stressSteps = 0, deepStressSteps = 0, totalSprPct = 0;
    let cycles = [], decisions = [];
    let decidedThisWindow = false;
    
    for (let di = 0; di < numDays; di++) {
      const wx = dailyWeather[di];
      const wxTomorrow = dailyWeather[di + 1] || wx;
      
      // ── Seasonal Kc ──
      const month = parseInt(wx.date.split('-')[1]);
      const kc = zone.kc_schedule[month] || 0.80;
      
      decidedThisWindow = false; // reset per day
      
      for (let step = 0; step < 96; step++) { // 96 steps per day (15 min)
        const h = Math.floor(step / 4);
        const m = (step % 4) * 15;
        
        // Temp from hourly data
        const hrIdx = di * 24 + h;
        const tempF = wx.hourly ? (wx.hourly.temperature_2m[hrIdx] || wx.hi) : wx.hi;
        
        // Wind from hourly
        const windMph = wx.hourly ? (wx.hourly.wind_speed_10m[hrIdx] || wx.maxWind * 0.5) : wx.maxWind * 0.5;
        
        // Dynamic thresholds
        const tempDelta = (tempF - 70) / 10;
        let madNow = Math.max(38, Math.min(62, zone.madPct + tempDelta * 3));
        let wiltNow = Math.max(22, Math.min(madNow - 10, zone.wiltPct + tempDelta * 2));
        
        // ── ET₀ drain (use actual daily ET₀, prorated by hour) ──
        let drain = 0;
        if (h >= 6 && h <= 20) {
          const phase = (h + m / 60 - 6) / 14 * Math.PI;
          // Prorate actual daily ET₀ across the bell curve
          // Total area under sin from 0 to π = 2, so each step = sin(phase) / (total_steps × 2/π)
          const dailyET_pct = (wx.et0_in / zone.rootDepthIn) * 100 * kc; // daily ET as % of root zone
          drain = Math.sin(phase) * dailyET_pct / (56 * 0.637); // 56 daytime steps, 2/π normalization
        }
        moisture -= drain;
        
        // ── Rain (from real hourly data) ──
        let rain = 0;
        for (let ri = 0; ri < rainEvents.length; ri++) {
          const re = rainEvents[ri];
          const stepInDay = h * 4 + Math.floor(m / 15);
          if (di === re.day && stepInDay >= re.hr * 4 && stepInDay < re.hr * 4 + re.dur) {
            rain = (re.depth / re.dur) * 100; // spread across duration
          }
        }
        // Effective rain (75% reaches roots)
        rain *= 0.75;
        
        // ── Track stress ──
        if (moisture < madNow && moisture >= wiltNow) { stressSteps++; cumulativeStressHrs += 0.25; }
        if (moisture < wiltNow) { deepStressSteps++; cumulativeStressHrs += 0.5; }
        
        // ── Sprinkler decisions ──
        let sprinkler = 0;
        
        // Arm check (using actual ET₀)
        const dailyDrain_pct = (wx.et0_in / zone.rootDepthIn) * 100 * kc;
        const armThreshold = madNow + dailyDrain_pct * params.armMargin;
        if (!armed && !recovering && moisture <= armThreshold) armed = true;
        
        // Pre-emptive for heat
        if (!armed && !recovering && wxTomorrow.hi > 85 && moisture < armThreshold + 5 && h >= 18) {
          armed = true;
          if (!decidedThisWindow) {
            decisions.push({ day: di, date: wx.date, type: 'arm-preemptive', reason: `Tomorrow ${Math.round(wxTomorrow.hi)}°F — pre-watering` });
          }
        }
        
        // Water window: 4-6 AM
        if (armed && h >= 4 && h < 6 && !recovering && !decidedThisWindow) {
          decidedThisWindow = true; // only one decision per window
          
          // Wind check
          if (windMph > 10) {
            decisions.push({ day: di, date: wx.date, type: 'skip-wind', reason: `Wind ${Math.round(windMph)} mph` });
          }
          // Rain check
          else {
            let rainExpected = false;
            if (wx.rainTomorrow) rainExpected = true;
            if (di > 0 && dailyWeather[di-1].rainTomorrow) rainExpected = true;
            // Also check today's actual rain
            if (wx.rainTotal > 0.05) rainExpected = true;
            
            if (rainExpected && moisture > madNow - 3) {
              decisions.push({ day: di, date: wx.date, type: 'skip-rain', reason: `Rain ${rainExpected ? 'expected' : ''}, moisture ${Math.round(moisture)}%` });
            }
            else if (rainExpected && moisture <= madNow - 3) {
              recovering = true;
              cycleTarget = madNow + 14;
              decisions.push({ day: di, date: wx.date, type: 'water-despite-rain', reason: `Too dry ${Math.round(moisture)}% to wait for rain` });
            }
            // Stress delay
            else if (!rainExpected && cumulativeStressHrs < params.stressDelayMax && moisture > madNow + params.stressDelayAbove) {
              decisions.push({ day: di, date: wx.date, type: 'skip-stress', reason: `${cumulativeStressHrs.toFixed(1)}h stress, soil ${Math.round(moisture)}%` });
            }
            // WATER
            else if (!rainExpected) {
              recovering = true;
              // Depth adapts: hot week = deeper, cool = shallower
              const avgHi3day = (wx.hi + (wxTomorrow.hi || wx.hi) + (dailyWeather[di+2]||wx).hi) / 3;
              let recoverExtra = Math.max(0, (avgHi3day - 70)) * params.recoverHeatCoeff;
              cycleTarget = Math.min(params.recoverMax, madNow + params.recoverBase + recoverExtra);
              decisions.push({ day: di, date: wx.date, type: 'water', 
                reason: `${Math.round(moisture)}% → ${Math.round(cycleTarget)}%, ${Math.round(tempF)}°F, Kc=${kc}` });
            }
          }
        }
        
        // Emergency
        if (!recovering && moisture <= wiltNow + 2 && h >= 3) {
          recovering = true;
          cycleTarget = madNow + 15;
          decisions.push({ day: di, date: wx.date, type: 'EMERGENCY', reason: `${Math.round(moisture)}% near wilt ${Math.round(wiltNow)}%` });
        }
        
        if (recovering) {
          if (moisture < cycleTarget) {
            sprinkler = (zone.precipRate / 4) * (100 / zone.rootDepthIn);
            if (moisture + sprinkler > cycleTarget) sprinkler = cycleTarget - moisture;
          }
          if (moisture + sprinkler >= cycleTarget || h >= 6) {
            recovering = false; armed = false;
            cumulativeStressHrs = 0; lastWateredDay = di;
            cycles.push(di);
          }
        }
        
        totalSprPct += sprinkler;
        moisture = Math.min(100, Math.max(0, moisture + rain + sprinkler));
      }
    }
    
    // Stats
    let cycleDays = 0;
    if (cycles.length > 1) {
      let tot = 0;
      for (let c = 1; c < cycles.length; c++) tot += cycles[c] - cycles[c-1];
      cycleDays = tot / (cycles.length - 1);
    }
    const stressHrs = stressSteps * 0.25;
    const deepStressHrs = deepStressSteps * 0.25;
    
    // Per-month stats
    const monthlyStats = {};
    for (let d = 0; d < numDays; d++) {
      const m = dailyWeather[d].date.substring(0, 7);
      if (!monthlyStats[m]) monthlyStats[m] = { waterDays: 0, skipRain: 0, skipWind: 0, skipStress: 0 };
    }
    decisions.forEach(dec => {
      const m = dec.date.substring(0, 7);
      if (!monthlyStats[m]) monthlyStats[m] = { waterDays: 0, skipRain: 0, skipWind: 0, skipStress: 0 };
      if (dec.type === 'water') monthlyStats[m].waterDays++;
      if (dec.type === 'skip-rain') monthlyStats[m].skipRain++;
      if (dec.type === 'skip-wind') monthlyStats[m].skipWind++;
      if (dec.type === 'skip-stress') monthlyStats[m].skipStress++;
    });
    
    return {
      cycles: cycles.length,
      cycleDays: cycleDays.toFixed(1),
      stressPerCycle: cycles.length > 0 ? (stressHrs / cycles.length).toFixed(1) : '0',
      deepStressHrs: deepStressHrs.toFixed(1),
      depthPerCycle: cycles.length > 0 ? (totalSprPct / 100 * 6 / cycles.length).toFixed(2) : '0',
      totalStressHrs: stressHrs.toFixed(1),
      totalWaterInches: (totalSprPct / 100 * 6).toFixed(1),
      decisions, monthlyStats,
      emergencies: decisions.filter(d => d.type === 'EMERGENCY').length
    };
  }
  
  // ── 4. Parameter sweep with seasonal Kc ──
  console.log("\n═══ Tier 5 Parameter Sweep ═══");
  console.log("Target: cycle 2-4d, stress/cyc 2-8h, deep 0h, depth 0.5-0.75\"");
  console.log("─".repeat(80));
  
  // Seasonal Kc schedule (month number → Kc)
  const kcFlat = { 5: 0.80, 6: 0.80, 7: 0.80, 8: 0.80, 9: 0.80 };
  const kcSeasonal = { 5: 0.55, 6: 0.75, 7: 0.85, 8: 0.85, 9: 0.65 };
  
  const sweepParams = [
    { armMargin: 1.3, recoverBase: 18, recoverHeatCoeff: 0.04, recoverMax: 78, stressDelayMax: 0, stressDelayAbove: 5, kcSchedule: kcFlat, label: "flat-Kc r+18 a1.3" },
    { armMargin: 1.3, recoverBase: 20, recoverHeatCoeff: 0.04, recoverMax: 80, stressDelayMax: 0, stressDelayAbove: 5, kcSchedule: kcFlat, label: "flat-Kc r+20 a1.3" },
    { armMargin: 1.5, recoverBase: 20, recoverHeatCoeff: 0.04, recoverMax: 80, stressDelayMax: 0, stressDelayAbove: 5, kcSchedule: kcFlat, label: "flat-Kc r+20 a1.5" },
    { armMargin: 1.3, recoverBase: 18, recoverHeatCoeff: 0.04, recoverMax: 78, stressDelayMax: 0, stressDelayAbove: 5, kcSchedule: kcSeasonal, label: "season-Kc r+18 a1.3" },
    { armMargin: 1.3, recoverBase: 20, recoverHeatCoeff: 0.04, recoverMax: 80, stressDelayMax: 0, stressDelayAbove: 5, kcSchedule: kcSeasonal, label: "season-Kc r+20 a1.3" },
    { armMargin: 1.5, recoverBase: 20, recoverHeatCoeff: 0.04, recoverMax: 80, stressDelayMax: 0, stressDelayAbove: 5, kcSchedule: kcSeasonal, label: "season-Kc r+20 a1.5" },
    { armMargin: 1.3, recoverBase: 20, recoverHeatCoeff: 0.08, recoverMax: 82, stressDelayMax: 0, stressDelayAbove: 5, kcSchedule: kcSeasonal, label: "season-Kc r+20 a1.3 heatadapt" },
    { armMargin: 1.5, recoverBase: 18, recoverHeatCoeff: 0.08, recoverMax: 80, stressDelayMax: 1, stressDelayAbove: 5, kcSchedule: kcSeasonal, label: "season-Kc r+18 a1.5 stress1h" },
  ];
  
  sweepParams.forEach(p => {
    const r = runTier5(p);
    const cd = parseFloat(r.cycleDays), sp = parseFloat(r.stressPerCycle);
    const dp = parseFloat(r.depthPerCycle), dh = parseFloat(r.deepStressHrs);
    const ok = cd >= 2 && cd <= 4 && sp >= 2 && sp <= 8 && dh == 0 && dp >= 0.5 && dp <= 0.75;
    console.log(
      `${ok ? '✅' : '  '} ${p.label.padEnd(36)} cyc:${r.cycleDays.padStart(4)}d str:${r.stressPerCycle.padStart(5)}h deep:${r.deepStressHrs.padStart(5)}h dep:${r.depthPerCycle.padStart(5)}" n=${String(r.cycles).padStart(2)} water:${r.totalWaterInches}" em=${r.emergencies}`
    );
  });
  
  // ── 5. Detailed report for best ──
  console.log("\n═══ Detailed Report: season-Kc r+20 a1.3 ═══");
  const best = runTier5(sweepParams[4]); // season-Kc r+20 a1.3
  
  console.log("\nMonthly breakdown:");
  Object.entries(best.monthlyStats).forEach(([m, s]) => {
    console.log(`  ${m}: watered ${s.waterDays}x, rain-skip ${s.skipRain}x, wind-skip ${s.skipWind}x, stress-delay ${s.skipStress}x`);
  });
  
  console.log(`\nTotal: ${best.cycles} waterings, ${best.totalWaterInches}" applied, ${best.emergencies} emergencies`);
  
  // Decision types
  const typeCounts = {};
  best.decisions.forEach(d => typeCounts[d.type] = (typeCounts[d.type]||0) + 1);
  console.log("Decision types:", JSON.stringify(typeCounts));
  
  // Print all decisions
  console.log("\nAll decisions:");
  best.decisions.forEach(d => {
    const icons = { water:'💧', 'skip-rain':'🌧️', 'skip-wind':'💨', 'skip-stress':'🌱', 'arm-preemptive':'🌡️', 'water-despite-rain':'⚠️', EMERGENCY:'🚨' };
    console.log(`  ${icons[d.type]||'📋'} ${d.date} [${d.type.padEnd(20)}] ${d.reason}`);
  });
}

main().catch(console.error);
