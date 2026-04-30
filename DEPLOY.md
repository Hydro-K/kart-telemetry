# Deploying to Raspberry Pi

## Prerequisites
- Raspberry Pi 4 (4GB recommended) with Raspberry Pi OS Bookworm 64-bit
- SD card (≥16GB)
- Internet connection during setup (to pull the Ollama model)

---

## Step 1 — Copy the app to the Pi

From your Windows laptop, copy the entire `kart-telemetry` folder to the Pi:

```bash
# Option A: USB drive
#   Copy kart-telemetry/ to USB, then on the Pi:
cp -r /media/pi/USB/kart-telemetry /home/pi/kart-telemetry

# Option B: SCP over local network
scp -r kart-telemetry pi@<pi-ip>:/home/pi/kart-telemetry

# Option C: Git (if you push to GitHub)
# On the Pi:
git clone https://github.com/YOUR_USERNAME/kart-telemetry.git /home/pi/kart-telemetry
```

---

## Step 2 — Run setup (one time, requires internet)

SSH into the Pi and run:

```bash
cd /home/pi/kart-telemetry
sudo bash setup_pi.sh
```

This will (~10-15 minutes):
1. Install system packages (hostapd, dnsmasq, Python, etc.)
2. Create Python venv + install dependencies
3. Initialize the SQLite database (Kart #6 and Kart #70 pre-seeded)
4. Install and start Ollama, pull `phi3:mini` (~2.3GB download)
5. Configure the WiFi hotspot (SSID: `KartTelemetry`, password: `PurdueKart25`)
6. Set up iptables redirect port 80 → 5000
7. Install the systemd service (auto-starts on boot)

---

## Step 3 — Reboot

```bash
sudo reboot
```

After reboot, the Pi will:
- Broadcast the `KartTelemetry` WiFi network
- Automatically start the dashboard on port 5000
- Automatically start Ollama for AI features

---

## Step 4 — Connect and use

1. On any phone, tablet, or laptop → connect to WiFi: **KartTelemetry** / **PurdueKart25**
2. Open browser → go to **http://192.168.4.1**
3. Create a session, select Kart #6 or Kart #70
4. Upload AiM recordings (ZIP or XRK) and choose the driver (Jayden / Kolten / James)

---

## Troubleshooting

```bash
# Check app status
sudo systemctl status kart-telemetry

# View live app logs
sudo journalctl -u kart-telemetry -f

# Check Ollama status
sudo systemctl status ollama

# Restart app after code changes
sudo systemctl restart kart-telemetry

# Re-pull Ollama model if needed
ollama pull phi3:mini
```

---

## Importing data on the Pi (bulk import)

If you have AiM CSV folders on a USB drive:

```bash
cd /home/pi/kart-telemetry
source venv/bin/activate

# Import a folder of recordings into a new session
python bulk_import.py \
  --session-name "April 26 Practice" \
  --kart 1 \
  --driver Jayden \
  --folder /media/pi/USB/recordings/

# List all sessions
python bulk_import.py --list
```

---

## Updating the app

```bash
cd /home/pi/kart-telemetry
# Copy new files (or git pull)
git pull  # if using git

# Restart service
sudo systemctl restart kart-telemetry
```

The SQLite database in `data/telemetry.db` is preserved across updates — no data loss.

---

## Network info

| Setting | Value |
|---|---|
| WiFi SSID | KartTelemetry |
| WiFi Password | PurdueKart25 |
| Pi IP | 192.168.4.1 |
| Dashboard URL | http://192.168.4.1 |
| DHCP range | 192.168.4.2 – 192.168.4.20 |
| Max simultaneous clients | 19 |
