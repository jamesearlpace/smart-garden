#!/bin/bash
cd ~/smart-garden-server
echo '=== ledger committed at each 30-min overnight point (post-clamp, what is baked in) ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method FROM meter_reading WHERE ts BETWEEN '2026-07-08T22:30:00' AND '2026-07-09T08:00:00' AND strftime('%M:%S',ts) BETWEEN '00:00' AND '00:20' ORDER BY ts;"
echo
echo '=== the two suspicious .963 spike reads: are they baked as committed? ==='
sqlite3 meter_ledger.db "SELECT ts, committed_cf, method FROM meter_reading WHERE committed_cf BETWEEN '95449.0' AND '95450.5' AND ts < '2026-07-09T09:00:00' ORDER BY ts LIMIT 8;"
echo
echo '=== corroborated overnight anchors (values seen in 2+ consecutive reads) ==='
echo 'Real solid points: 22:30=95433.87, 00:00-02:00 flat=95442.22, 07:56=95445.96'
echo 'True overnight climb 22:30->07:56 = 95445.96 - 95433.87 = 12.09 cf = 90.4 gal'
echo 'Dryrun reported 124 gal -> ~34 gal is phantom from the .963 misread spikes'
