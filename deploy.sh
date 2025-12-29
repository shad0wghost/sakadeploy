#!/bin/bash
# deploy.sh - Automated setup script for the CICD Management Interface
# Must be run with sudo: sudo bash deploy.sh

# --- Safety First: Exit on any error ---
set -e

# --- Check for root privileges ---
if [ "$EUID" -ne 0 ]; then
  echo "Error: This script must be run as root. Please use sudo."
  exit 1
fi

echo "--- CICD Management Interface Automated Setup ---"

# --- 1. Install System Dependencies (Docker, Docker Compose, Python) ---
echo -e "\n--- Checking and installing system dependencies... ---"

# Update package lists
apt-get update

# Install prerequisites
apt-get install -y ca-certificates curl gnupg python3 python3-pip

# Check and install Docker Engine
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    echo "Docker installed successfully."
else
    echo "Docker is already installed."
fi

# Add the user who ran sudo to the docker group to manage docker without sudo
if [ -n "$SUDO_USER" ]; then
    usermod -aG docker "$SUDO_USER"
    echo "Added user '$SUDO_USER' to the docker group. You may need to log out and back in for this to take effect."
fi


# --- 2. Install Python Dependencies ---
echo -e "\n--- Installing Python dependencies... ---"
# Note: Installing system-wide can be risky, but following the user's request.
pip3 install --break-system-packages -r requirements.txt
echo "Python dependencies installed."


# --- 3. Create Deployment Directory ---
echo -e "\n--- Creating deployment directory... ---"
DEPLOY_DIR="/var/deploy"
mkdir -p "$DEPLOY_DIR"
chown -R "$SUDO_USER:$SUDO_USER" "$DEPLOY_DIR"
echo "Deployment directory '$DEPLOY_DIR' created and permissions set."


# --- 4. Configure Application ---
echo -e "\n--- Configuring the application... ---"
CONFIG_FILE="config.py"

# Prompt for GitHub PAT
while true; do
    read -sp "Enter your GitHub Personal Access Token: " GITHUB_PAT
    echo
    if [[ -z "$GITHUB_PAT" ]]; then
        echo "PAT cannot be empty."
    else
        # Validate PAT by checking API access
        if curl -s -H "Authorization: token $GITHUB_PAT" https://api.github.com/user | grep -q "login"; then
            echo "GitHub PAT is valid."
            break
        else
            echo "Invalid GitHub PAT. Please try again."
        fi
    fi
done

# Prompt for Admin Password
while true; do
    read -sp "Create an admin password for the web UI: " ADMIN_PASSWORD
    echo
    read -sp "Confirm the admin password: " ADMIN_PASSWORD_CONFIRM
    echo
    if [[ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]]; then
        echo "Passwords do not match. Please try again."
    elif [[ -z "$ADMIN_PASSWORD" ]]; then
        echo "Password cannot be empty."
    else
        echo "Admin password set."
        break
    fi
done

# Update config.py using sed
sed -i "s/GITHUB_PAT = .*/GITHUB_PAT = \"$GITHUB_PAT\"/" "$CONFIG_FILE"
sed -i "s/ADMIN_PASSWORD = .*/ADMIN_PASSWORD = \"$ADMIN_PASSWORD\"/" "$CONFIG_FILE"
echo "Configuration file '$CONFIG_FILE' updated."


# --- 4. Generate SSL Certificate ---
echo -e "\n--- Generating self-signed SSL certificate... ---"
python3 generate_certs.py


# --- 5. Set up Systemd Service ---
echo -e "\n--- Setting up systemd service... ---"
SERVICE_FILE="/etc/systemd/system/cicd_interface.service"
PROJECT_DIR=$(pwd)
# Default to the user who ran sudo, or root if sudo user is not set
SERVICE_USER=${SUDO_USER:-root}

echo "Creating systemd service file at $SERVICE_FILE"
cat > "$SERVICE_FILE" << EOL
[Unit]
Description=CICD Management Interface
After=network.target

[Service]
User=$SERVICE_USER
Group=$(id -gn "$SERVICE_USER")
WorkingDirectory=$PROJECT_DIR
ExecStart=/usr/bin/python3 $PROJECT_DIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

# Reload, enable, and start the service
systemctl daemon-reload
systemctl enable cicd_interface.service
systemctl start cicd_interface.service
echo "Systemd service 'cicd_interface' created, enabled, and started."


# --- Final Status ---
echo -e "\n--- Deployment Complete! ---"
echo "The CICD Management Interface is now running as a system service."
echo "Waiting a few seconds to check the service status..."
sleep 5

# Display service status
systemctl status cicd_interface.service --no-pager

echo -e "\n>>> You can access the web interface at: https://$(curl -s ifconfig.me):8123"
echo ">>> To view live logs, run: journalctl -u cicd_interface.service -f"
echo ">>> To stop the service, run: sudo systemctl stop cicd_interface.service"

exit 0
