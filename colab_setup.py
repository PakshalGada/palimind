"""
PaliMind — Google Colab Setup Script
=====================================
Use this script if you don't have a local GPU.
It installs Ollama on a Colab runtime, pulls all required models,
and exposes the Ollama server publicly via LocalTunnel so PaliMind
can connect remotely.

Instructions:
  1. Open a new Google Colab notebook (GPU runtime recommended).
  2. Copy-paste this entire script into a cell and run it.
  3. Copy the localtunnel URL printed at the bottom.
  4. In PaliMind, set `ollama_base_url` to that URL in your config.json.
"""

import subprocess
import time
import os

os.system("sudo apt-get install -y zstd")
# 2. Install Ollama natively
os.system("curl -fsSL https://ollama.com/install.sh | sh")

# 3. Configure Ollama to allow public connections
os.environ["OLLAMA_HOST"] = "0.0.0.0"
os.environ["OLLAMA_ORIGINS"] = "*"

print("Starting the Ollama background process...")
# Start server with the new environment variables
subprocess.Popen(["ollama", "serve"], env=os.environ)
time.sleep(5)

# 3. Pull required models
os.system("ollama pull gemma2")
os.system("ollama pull gemma4:e2b")
os.system("ollama pull nomic-embed-text")
os.system("ollama pull llava")
os.system("ollama pull moondream")
# 4. Install LocalTunnel
os.system("npm install -g localtunnel")

print("STARTING TUNNEL! Your URL will appear below:")
# 5. Start the tunnel
os.system("npx localtunnel --port 11434")

