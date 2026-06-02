// Check which decision types fire across 2021-2025
// Run: node check-decisions.js

const https = require('https');

function fetchJSON(url) {
  return new Promise((resolve, reject) => {
    https.get(url, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch(e) { reject(e); }
      });
    }).on('error', reject);
  });
}

async function runYear(year) {
  const lat = 47.7382, lon = -121.9856;
  const url = `https://archive-api.open-meteo.com/v1/archive?latitude=${lat}&longitude=${lon}` +
    `&start_date=${year}-05-01&end_date=${year}-09-30` +
    `&daily=et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min,wind_speed_10m_max` +
    `&hourly=temperature_2m,wind_speed_10m,precipitation` +
    `&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&timezone=America/Los_Angeles`;
  
  const wx = await fetchJSON(url);
  const numDays = wx.daily.time.length;
  
  // Build rain events
  const rainEvents = [];
  for (let d = 0; d < numDays; d++) {
    let rStart = -1, rDur = 0, rDepth = 0;
    for (let hh = 0; hh < 24; hh++) {
      const precip = wx.hourly.precipitation[d*24+hh] || 0;
      if (precip > 0.005) { if (rStart < 0) rStart = hh; rDur++; rDepth += precip; }
      else if (rStart >= 0) {
        if (rDepth > 0.01) rainEvents.push({day:d, hr:rStart, dur:rDur*4, depth:rDepth});
        rStart=-1; rDur=0; rDepth=0;
      }
    }
    if (rStart >= 0 && rDepth > 0.01) rainEvents.push({day:d, hr:rStart, dur:rDur*4, depth:rDepth});
  }
  
  // Run simulation
  const KC = 0.90;
  const MAD_BASE = 50, WILT_BASE = 35;
  const rootSched = {3:4,4:4,5:5,6:6,7:8,8:8,9:6,10:5};
  const recoverSched = {3:12,4:12,5:15,6:18,7:20,8:20,9:15,10:12};
  const hardenMonths = {6:true,7:true,8:true};
  const precipRate = 1.5;
  
  let moisture = 70, armed = false, recovering = false, cycleTarget = 0;
  let cumulativeStressHrs = 0, lastWateredStep = -999;
  let decidedToday = false, skippedForRainDay = -1;
  let lastHardenDay = -21, inHardeningMode = false;
  const decisions = [];
  
  for (let di = 0; di < numDays; di++) {
    const hi = wx.daily.temperature_2m_max[di];
    const et0_in = wx.daily.et0_fao_evapotranspiration[di] || 0;
    const maxWind = wx.daily.wind_speed_10m_max[di] || 0;
    const month = parseInt(wx.daily.time[di].split('-')[1]);
    const rootDepth = rootSched[month] || 6;
    const seasonalRecover = recoverSched[month] || 20;
    const hiTomorrow = (di+1<numDays) ? wx.daily.temperature_2m_max[di+1] : hi;
    const rainTomorrow = (di+1<numDays && (wx.daily.precipitation_sum[di+1]||0) > 0.02);
    const prevRainTomorrow = (di>0 && (wx.daily.precipitation_sum[di]||0) > 0.02);
    
    let canHarden = !!(hardenMonths[month]);
    if (canHarden) {
      let avg5 = 0, cnt = 0;
      for (let fd = di; fd < Math.min(di+5, numDays); fd++) { avg5 += wx.daily.temperature_2m_max[fd]; cnt++; }
      if (cnt > 0 && avg5/cnt > 80) canHarden = false;
    }
    
    decidedToday = false;
    
    for (let step = 0; step < 96; step++) {
      const h = Math.floor(step/4), m = (step%4)*15;
      const hrIdx = di*24+h;
      const tempF = wx.hourly.temperature_2m[hrIdx] || (hi + (wx.daily.temperature_2m_min[di]||50))/2;
      
      const tempDelta = (tempF - 70) / 10;
      const madNow = Math.max(38, Math.min(62, MAD_BASE + tempDelta * 3));
      const wiltNow = Math.max(22, Math.min(madNow - 10, WILT_BASE + tempDelta * 2));
      
      // Drain
      let drain = 0;
      if (h >= 6 && h <= 20) {
        const phase = (h+m/60-6)/14*Math.PI;
        drain = Math.sin(phase) * (et0_in/rootDepth)*100*KC / (56*0.637);
      }
      moisture -= drain;
      
      // Rain
      let rain = 0;
      const stepInDay = h*4+Math.floor(m/15);
      for (const re of rainEvents) {
        if (di===re.day && stepInDay>=re.hr*4 && stepInDay<re.hr*4+re.dur) {
          const eff = re.depth < 0.1 ? 0.40 : re.depth < 0.3 ? 0.65 : 0.80;
          rain = (re.depth/re.dur)*100*eff;
        }
      }
      
      // Stress
      if (moisture < madNow && moisture >= wiltNow) cumulativeStressHrs += 0.25;
      if (moisture < wiltNow) cumulativeStressHrs += 0.5;
      
      // Arm
      const dailyDrain_pct = (et0_in/rootDepth)*100*KC;
      const armThreshold = madNow + dailyDrain_pct * 1.3;
      if (!armed && !recovering && moisture <= armThreshold) armed = true;
      
      // Pre-emptive
      if (!armed && !recovering && hiTomorrow > 85 && moisture < armThreshold+5 && h >= 18) {
        armed = true;
        if (!decidedToday) decisions.push({day:di, date:wx.daily.time[di], type:'arm-preemptive'});
      }
      
      // Water window
      let sprinkler = 0;
      if (armed && h>=4 && h<6 && !recovering && !decidedToday) {
        decidedToday = true;
        
        if (maxWind > 10) {
          decisions.push({day:di, date:wx.daily.time[di], type:'skip-wind', reason:'Wind '+Math.round(maxWind)+' mph'});
        } else {
          let rainExpected = false;
          if (rainTomorrow) rainExpected = true;
          if (prevRainTomorrow) rainExpected = true;
          if ((wx.daily.precipitation_sum[di]||0) > 0.05) rainExpected = true;
          for (const re of rainEvents) {
            if (re.day===di || re.day===di+1) rainExpected = true;
          }
          
          if (rainExpected && moisture > madNow - 3) {
            skippedForRainDay = di;
            decisions.push({day:di, date:wx.daily.time[di], type:'skip-rain', reason:'Moisture '+Math.round(moisture)+'%'});
          } else if (rainExpected && moisture <= madNow - 3) {
            recovering = true; cycleTarget = madNow + 14;
            decisions.push({day:di, date:wx.daily.time[di], type:'water-despite-rain', reason:Math.round(moisture)+'% too dry'});
          } else if (!rainExpected) {
            // Catch-up check
            let catchUp = false;
            if (skippedForRainDay >= 0 && di - skippedForRainDay <= 2) {
              let rainSince = 0;
              for (let rk = skippedForRainDay; rk <= di; rk++) rainSince += (wx.daily.precipitation_sum[rk]||0);
              if ((rainSince * 0.65 / rootDepth) * 100 < 3) {
                catchUp = true;
                decisions.push({day:di, date:wx.daily.time[di], type:'catch-up', reason:'Rain only '+rainSince.toFixed(2)+'"'});
              }
              skippedForRainDay = -1;
            }
            
            // Hardening
            if (!catchUp && canHarden && !inHardeningMode && (di-lastHardenDay)>=21 && moisture<=madNow+5 && moisture>wiltNow+8) {
              inHardeningMode = true;
              decisions.push({day:di, date:wx.daily.time[di], type:'skip-harden', reason:'Moisture '+Math.round(moisture)+'%'});
            } else if (inHardeningMode && moisture <= wiltNow + 5) {
              inHardeningMode = false; lastHardenDay = di;
              recovering = true; cycleTarget = Math.min(80, madNow+22);
              decisions.push({day:di, date:wx.daily.time[di], type:'water', reason:'END HARDENING '+Math.round(moisture)+'%'});
            } else if (inHardeningMode) {
              decisions.push({day:di, date:wx.daily.time[di], type:'skip-harden', reason:'Day '+(di-lastHardenDay+21)});
            } else if (!catchUp) {
              recovering = true;
              const avgHi3 = (hi+hiTomorrow+((di+2<numDays)?wx.daily.temperature_2m_max[di+2]:hi))/3;
              cycleTarget = Math.min(80, madNow + seasonalRecover + Math.max(0,(avgHi3-70))*0.04);
              decisions.push({day:di, date:wx.daily.time[di], type:'water', reason:Math.round(moisture)+'%→'+Math.round(cycleTarget)+'%'});
            }
          }
        }
      }
      
      // Emergency
      if (!recovering && moisture <= wiltNow + 2 && h >= 3) {
        recovering = true; cycleTarget = madNow + 15;
        decisions.push({day:di, date:wx.daily.time[di], type:'water-emergency', reason:Math.round(moisture)+'% near wilt'});
      }
      
      if (recovering) {
        if (moisture < cycleTarget) {
          sprinkler = (precipRate/4)*(100/rootDepth);
          if (moisture+sprinkler > cycleTarget) sprinkler = cycleTarget - moisture;
        }
        if (moisture+sprinkler >= cycleTarget || h >= 6) {
          recovering = false; armed = false;
          cumulativeStressHrs = 0; lastWateredStep = di*96+step;
        }
      }
      
      moisture = Math.min(100, Math.max(0, moisture + rain + sprinkler));
    }
  }
  
  return decisions;
}

async function main() {
  const allTypes = {};
  const yearSummaries = [];
  
  for (const year of [2021, 2022, 2023, 2024, 2025]) {
    process.stdout.write(`Fetching ${year}...`);
    const decs = await runYear(year);
    const counts = {};
    decs.forEach(d => counts[d.type] = (counts[d.type]||0) + 1);
    Object.keys(counts).forEach(t => allTypes[t] = (allTypes[t]||0) + counts[t]);
    
    console.log(` ${decs.length} decisions: ${JSON.stringify(counts)}`);
    yearSummaries.push({year, counts, total: decs.length});
  }
  
  console.log('\n═══ Decision Types Across All Years ═══');
  const expected = ['water', 'skip-rain', 'skip-wind', 'arm-preemptive', 
                     'water-despite-rain', 'skip-harden', 'water-emergency', 'catch-up'];
  expected.forEach(t => {
    const count = allTypes[t] || 0;
    console.log(`  ${count > 0 ? '✅' : '❌'} ${t.padEnd(22)} ${String(count).padStart(4)} times`);
  });
  
  console.log('\n═══ Year-by-Year ═══');
  yearSummaries.forEach(s => {
    console.log(`  ${s.year}: ${s.total} decisions`);
    expected.forEach(t => {
      if (s.counts[t]) console.log(`    ${t}: ${s.counts[t]}`);
    });
  });
}

main().catch(console.error);
