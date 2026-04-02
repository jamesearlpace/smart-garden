#!/bin/bash
# Deploy Smart Garden server components to Acer home server
# Run from Windows: ssh jamesearlpace@192.168.0.109 "bash ~/smart-garden/server/deploy.sh"

set -e

INSTALL_DIR="$HOME/smart-garden/server"
echo "=== Smart Garden Server Deploy ==="
echo "Install dir: $INSTALL_DIR"

# Copy service files
echo "Installing systemd services..."
sudo cp "$INSTALL_DIR/smart-garden-collector.service" /etc/systemd/system/
sudo cp "$INSTALL_DIR/smart-garden-api.service" /etc/systemd/system/
sudo cp "$INSTALL_DIR/smart-garden-scheduler.service" /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable smart-garden-collector.service
sudo systemctl enable smart-garden-api.service
sudo systemctl enable smart-garden-scheduler.service

# Start (or restart)
sudo systemctl restart smart-garden-collector.service
sudo systemctl restart smart-garden-api.service
sudo systemctl restart smart-garden-scheduler.service

echo ""
echo "=== Status ==="
sudo systemctl status smart-garden-collector.service --no-pager -l
echo ""
sudo systemctl status smart-garden-api.service --no-pager -l
echo ""
sudo systemctl status smart-garden-scheduler.service --no-pager -l
echo ""
echo "Collector:  polling ESP32 every 60s → SQLite"
echo "Query API:  http://192.168.0.109:5150"
echo "Scheduler:  evaluating zones every 30s"
echo "Done!"
