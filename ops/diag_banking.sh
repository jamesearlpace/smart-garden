#!/bin/bash
cd ~/smart-garden-server
D=/etc/systemd/system/smart-garden-server.service.d
echo '=== collection / banking drop-in ==='
cat $D/collection.conf 2>/dev/null || echo '(no collection.conf)'
echo '--- BANK env in effect ---'
systemctl show smart-garden-server -p Environment | tr ' ' '\n' | grep -i -E 'BANK|LOCAL_BANK|COLLECT' || echo '(no BANK env)'
echo
echo '=== zzz-openai-local-first.conf (the throttle) ==='
cat $D/zzz-openai-local-first.conf 2>/dev/null
echo
echo '=== banked stat from live status ==='
echo 'password123' | sudo -S bash tools/authcurl.sh GET '/api/cam/status' 2>/dev/null | sed -n '2p' | ./.venv/bin/python -c "import sys,json;d=json.load(sys.stdin);o=d.get('ocr',{});print('banked:',o.get('banked'));print('oracle:',json.dumps(d.get('oracle',{})))" 2>&1
echo
echo '=== training bank size on disk ==='
ls ~/meter-training/*.jpg 2>/dev/null | wc -l
echo 'sidecars:'; ls ~/meter-training/*.json 2>/dev/null | wc -l
echo
echo '=== cnn_daily recent (reader split + oracle calls) ==='
sqlite3 smart-garden.db "SELECT date, frames, cnn_used, cnn_fellback, oracle_calls, evals, cnn_correct, model_version FROM cnn_daily ORDER BY date DESC LIMIT 7;" 2>&1
echo
echo '=== nightly retrain timer on tower ==='
ssh jack@192.168.0.120 "systemctl status meter-cnn-retrain.timer --no-pager 2>&1 | head -6; echo '--- last retrain status ---'; cat ~/meter-cnn/retrain_status.json 2>/dev/null | python3 -m json.tool 2>/dev/null | head -20; echo '--- VERSION ---'; cat ~/meter-cnn/VERSION 2>/dev/null" 2>&1
