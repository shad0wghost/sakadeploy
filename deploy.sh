#!/bin/bash
# deploy.sh - Automated setup script for the CICD Management Interface
# Must be run with sudo: sudo bash deploy.sh

# --- ANSI Color Codes ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[0;37m'
NC='\033[0m' # No Color

# --- Safety First: Exit on any error ---
set -e

# --- Check for root privileges ---
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: This script must be run as root. Please use sudo.${NC}"
  exit 1
fi

echo -e "${CYAN}----------------------------------------------------${NC}"
echo -e "${CYAN}  Sakadeploy CICD Automated Setup Script  ${NC}"
echo -e "${CYAN}----------------------------------------------------${NC}"

# --- 1. Install System Dependencies (Docker, Docker Compose, Python) ---
echo -e "\n${BLUE}>>> 1. Checking and installing system dependencies...${NC}"
echo -e "${YELLOW}   (This may take a few moments, please be patient)${NC}"

echo -e "${WHITE}   Updating package lists...${NC}"
apt-get update -qq > /dev/null # Suppress output for update, too verbose
echo -e "${GREEN}   Package lists updated.${NC}"

echo -e "${WHITE}   Installing common prerequisites (ca-certificates, curl, gnupg, python3, pip)...${NC}"
apt-get install -y ca-certificates curl gnupg python3 python3-pip > /dev/null
echo -e "${GREEN}   Prerequisites installed.${NC}"

# Check and install Docker Engine
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}   Docker Engine not found. Installing Docker...${NC}"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq > /dev/null
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin > /dev/null
    echo -e "${GREEN}   Docker Engine and Docker Compose Plugin installed successfully.${NC}"
else
    echo -e "${GREEN}   Docker Engine is already installed.${NC}"
fi

# Add the user who ran sudo to the docker group to manage docker without sudo
if [ -n "$SUDO_USER" ]; then
    echo -e "${WHITE}   Adding user '$SUDO_USER' to the 'docker' group...${NC}"
    usermod -aG docker "$SUDO_USER"
    echo -e "${YELLOW}   User '$SUDO_USER' added to the 'docker' group. Please note: you may need to log out and back in (or reboot) for this change to take full effect.${NC}"
fi


# --- 2. Install Python Dependencies ---
echo -e "\n${BLUE}>>> 2. Installing Python dependencies...${NC}"
echo -e "${YELLOW}   (Using --break-system-packages as requested. Be aware of potential system conflicts.)${NC}"
pip3 install --break-system-packages -r requirements.txt > /dev/null
echo -e "${GREEN}   Python dependencies installed (Flask, PyGithub, cryptography, psutil).${NC}"


# --- 3. Create Deployment Directory ---
echo -e "\n${BLUE}>>> 3. Creating deployment directory for projects...${NC}"
DEPLOY_DIR="/var/deploy"
mkdir -p "$DEPLOY_DIR"
chown -R "$SUDO_USER:$SUDO_USER" "$DEPLOY_DIR"
echo -e "${GREEN}   Deployment directory '$DEPLOY_DIR' created and ownership set to '$SUDO_USER'.${NC}"


# --- 4. Configure Application ---
echo -e "\n${BLUE}>>> 4. Configuring the application (config.py)...${NC}"
CONFIG_FILE="config.py"

# Prompt for GitHub PAT
while true; do
    echo -e "${YELLOW}   Please enter your GitHub Personal Access Token (PAT). This token requires repo scope.${NC}"
    read -sp "   GitHub PAT: " GITHUB_PAT
    echo
    if [[ -z "$GITHUB_PAT" ]]; then
        echo -e "${RED}   PAT cannot be empty. Please try again.${NC}"
    else
        echo -e "${WHITE}   Validating GitHub PAT...${NC}"
        if curl -s -H "Authorization: token $GITHUB_PAT" https://api.github.com/user | grep -q "login"; then
            echo -e "${GREEN}   GitHub PAT is valid. Proceeding.${NC}"
            break
        else
            echo -e "${RED}   Invalid GitHub PAT. Please check your token and try again.${NC}"
        fi
    fi
done

# Prompt for Admin Password
while true; do
    echo -e "\n${YELLOW}   Please create a strong admin password for the web UI login.${NC}"
    read -sp "   Admin Password: " ADMIN_PASSWORD
    echo
    read -sp "   Confirm Admin Password: " ADMIN_PASSWORD_CONFIRM
    echo
    if [[ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]]; then
        echo -e "${RED}   Passwords do not match. Please try again.${NC}"
    elif [[ -z "$ADMIN_PASSWORD" ]]; then
        echo -e "${RED}   Password cannot be empty. Please try again.${NC}"
    else
        echo -e "${GREEN}   Admin password set successfully.${NC}"
        break
    fi
done

# Update config.py using sed
# Ensure the current directory is where config.py resides before sed command
CURRENT_SCRIPT_DIR="$(dirname "$0")"
pushd "$CURRENT_SCRIPT_DIR" > /dev/null
sed -i "s/GITHUB_PAT = .*/GITHUB_PAT = \"$GITHUB_PAT\"/" "$CONFIG_FILE"
sed -i "s/ADMIN_PASSWORD = .*/ADMIN_PASSWORD = \"$ADMIN_PASSWORD\"/" "$CONFIG_FILE"
popd > /dev/null
echo -e "${GREEN}   Configuration file '$CONFIG_FILE' updated with PAT and Admin Password.${NC}"


# --- 5. Generate SSL Certificate ---
echo -e "\n${BLUE}>>> 5. Generating self-signed SSL certificate...${NC}"
python3 generate_certs.py
echo -e "${GREEN}   Self-signed SSL certificate (cert.pem) and key (key.pem) generated in the 'certs/' directory.${NC}"


# --- 6. Set up Systemd Service ---
echo -e "\n${BLUE}>>> 6. Setting up systemd service for persistent application running...${NC}"
SERVICE_FILE="/etc/systemd/system/cicd_interface.service"
PROJECT_DIR=$(pwd)
SERVICE_USER=${SUDO_USER:-root} # Default to the user who ran sudo, or root if sudo user is not set

echo -e "${WHITE}   Creating systemd service file at '$SERVICE_FILE'...${NC}"
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
echo -e "${GREEN}   Service file created successfully.${NC}"

echo -e "${WHITE}   Reloading systemd daemon, enabling and starting 'cicd_interface' service...${NC}"
systemctl daemon-reload
systemctl enable cicd_interface.service > /dev/null
systemctl start cicd_interface.service
echo -e "${GREEN}   Systemd service 'cicd_interface' created, enabled, and started.${NC}"


# --- Final Status ---
echo -e "\n${CYAN}----------------------------------------------------${NC}"
echo -e "${GREEN}        Deployment Complete! CICD Interface is Live!        ${NC}"
echo -e "${CYAN}----------------------------------------------------${NC}"

echo -e "${WHITE}The CICD Management Interface is now running as a system service.${NC}"
echo -e "${WHITE}Waiting a few seconds for the service to fully initialize...${NC}"
sleep 5

# Display service status
echo -e "${CYAN}\n--- Current Service Status ---${NC}"
systemctl status cicd_interface.service --no-pager || echo -e "${RED}Error: Could not retrieve service status. Check 'journalctl -u cicd_interface.service -f'.${NC}"

IP_ADDRESS=$(curl -s ifconfig.me)
echo -e "\n${GREEN}>>> You can access the web interface at: ${NC}${YELLOW}https://${IP_ADDRESS}:8123${NC}"
echo -e "${WHITE}>>> To view live application logs, run: ${NC}${CYAN}journalctl -u cicd_interface.service -f${NC}"
echo -e "${WHITE}>>> To stop the service, run: ${NC}${CYAN}sudo systemctl stop cicd_interface.service${NC}"
echo -e "${WHITE}>>> To restart the service, run: ${NC}${CYAN}sudo systemctl restart cicd_interface.service${NC}"

exit 0