#!/usr/bin/env bash
# install-service.sh — Install OxyPC Inventory as a systemd service
# Usage: sudo ./services/install-service.sh
# Requires: systemd, running on Linux, must be run as root

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="${SCRIPT_DIR}/oxypc-inventory.service"
DEST="/etc/systemd/system/oxypc-inventory.service"
SERVICE_NAME="oxypc-inventory"

echo "=== OxyPC Inventory — Service Installer ==="

# Guard: must be root
if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: Run as root:  sudo $0"
    exit 1
fi

# Guard: service file must exist
if [[ ! -f "$SERVICE_FILE" ]]; then
    echo "ERROR: Service file not found: $SERVICE_FILE"
    exit 1
fi

# Install
echo "Installing ${SERVICE_FILE} → ${DEST}"
cp "$SERVICE_FILE" "$DEST"
chmod 644 "$DEST"

# Reload and enable
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "Service installed and enabled for auto-start on boot."
echo ""
echo "Commands:"
echo "  Start:   sudo systemctl start  $SERVICE_NAME"
echo "  Stop:    sudo systemctl stop   $SERVICE_NAME"
echo "  Restart: sudo systemctl restart $SERVICE_NAME"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "IMPORTANT: Edit $DEST to set the correct User/Group and WorkingDirectory"
echo "           before starting the service for the first time."
