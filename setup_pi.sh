#!/bin/bash
# ============================================================
# Purdue EV Grand Prix — Kart Telemetry Pi Setup Script
# Run once on a fresh Raspberry Pi OS (Bookworm, 64-bit)
# Usage: sudo bash setup_pi.sh
# ============================================================
set -e

APP_DIR="/home/pi/kart-telemetry"
SSID="KartTelemetry"
WIFI_PASS="PurdueKart25"
PI_IP="192.168.4.1"

echo "======================================================"
echo " Kart Telemetry — Raspberry Pi Setup"
echo "======================================================"

# ── 1. System packages ──────────────────────────────────────
echo "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y python3-pip python3-venv hostapd dnsmasq \
    sqlite3 iptables-persistent git curl

# ── 2. Python virtual environment ───────────────────────────
echo "[2/8] Creating Python venv and installing dependencies..."
cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
# libxrk is optional — enables native .xrk file uploads.
# It requires pyarrow which must be built from source on Pi.
# libarrow-dev was installed above to make this possible.
echo "  Attempting to install libxrk (XRK file support)..."
pip install --quiet libxrk \
  && echo "  libxrk installed — .xrk uploads enabled." \
  || echo "  Warning: libxrk unavailable — .xrk upload disabled. Use CSV ZIP exports instead."
deactivate

# Create data directory with correct ownership
mkdir -p "$APP_DIR/data" "$APP_DIR/uploads"
chown -R pi:pi "$APP_DIR"

# ── 3. Initialize database ──────────────────────────────────
echo "[3/8] Initializing database..."
cd "$APP_DIR"
sudo -u pi venv/bin/python -c "from database.db import init_db; init_db(); print('  DB ready')"

# ── 4. Install Ollama ────────────────────────────────────────
echo "[4/8] Installing Ollama..."
curl -fsSL https://ollama.ai/install.sh | sh
systemctl enable ollama
systemctl start ollama
echo "Waiting for Ollama to start..."
sleep 8
# Pull the model (requires internet — run this before the event!)
if systemctl is-active --quiet ollama; then
    ollama pull phi3:mini && echo "  phi3:mini ready." || echo "  Warning: Could not pull phi3:mini. Run 'ollama pull phi3:mini' manually while connected to internet."
else
    echo "  Warning: Ollama not running. Start it manually then run: ollama pull phi3:mini"
fi
echo "  Optional faster alternative: ollama pull llama3.2:1b"

# ── 5. Configure WiFi hotspot ────────────────────────────────
echo "[5/8] Configuring WiFi access point (wlan0)..."

# hostapd config
cat > /etc/hostapd/hostapd.conf << EOF
interface=wlan0
driver=nl80211
ssid=$SSID
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$WIFI_PASS
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' > /etc/default/hostapd

# dnsmasq config: DHCP + wildcard DNS → Pi
cat > /etc/dnsmasq.conf << EOF
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
address=/#/$PI_IP
EOF

# Static IP for wlan0 (skip if already set)
if ! grep -q "interface wlan0" /etc/dhcpcd.conf; then
  cat >> /etc/dhcpcd.conf << EOF

interface wlan0
static ip_address=$PI_IP/24
nohook wpa_supplicant
EOF
fi

# ── 6. iptables — redirect 80/443 → 5000 ───────────────────
echo "[6/8] Setting up port redirect 80 → 5000..."
iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 5000 2>/dev/null || true
iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 5000 2>/dev/null || true
netfilter-persistent save

# ── 7. Enable services ───────────────────────────────────────
echo "[7/8] Enabling services..."
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

# ── 8. Install app service ───────────────────────────────────
echo "[8/8] Installing kart-telemetry systemd service..."
cp "$APP_DIR/kart-telemetry.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable kart-telemetry

echo ""
echo "======================================================"
echo " SETUP COMPLETE — Reboot the Pi to activate everything."
echo ""
echo " WiFi Network : $SSID"
echo " Password     : $WIFI_PASS"
echo " URL          : http://$PI_IP"
echo "         (or) http://kart.local  (if mDNS works)"
echo ""
echo " Karts pre-configured: Kart #6 (teal) · Kart #70 (orange)"
echo " Drivers: Jayden, Kolten, James"
echo ""
echo " IMPORTANT: Pull the Ollama model before the event"
echo " while the Pi has internet access:"
echo "   ollama pull phi3:mini"
echo ""
echo " After reboot, check status:"
echo "   sudo systemctl status kart-telemetry"
echo "   sudo systemctl status ollama"
echo "======================================================"
