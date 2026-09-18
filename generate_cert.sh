#!/usr/bin/env bash
# Generates a self-signed cert/key for serving the Gradio app over https://
# Run this once from the project folder, then just run `python app.py`.
#
# Usage:
#   ./generate_cert.sh              # auto-detects your LAN IP
#   ./generate_cert.sh 192.168.1.5  # or pass it explicitly if detection is wrong

set -e

IP="${1:-$(hostname -I 2>/dev/null | awk '{print $1}')}"

if [ -z "$IP" ]; then
    echo "Could not auto-detect a LAN IP. Re-run with it explicitly:"
    echo "  ./generate_cert.sh 192.168.1.5"
    exit 1
fi

echo "Generating self-signed cert for IP: $IP"

openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
    -keyout key.pem -out cert.pem \
    -subj "/CN=$IP" \
    -addext "subjectAltName=IP:$IP,IP:127.0.0.1,DNS:localhost"

echo ""
echo "Done. cert.pem and key.pem created."
echo "Run 'python app.py' and open:  https://$IP:7860"
echo "On the phone, tap through the 'connection not private' warning once"
echo "(Advanced -> Proceed) -- this is expected for a self-signed cert."
