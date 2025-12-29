#!/bin/bash
# deploy.sh - Automated setup/teardown script for Sakadeploy
# To install/reinstall: sudo bash deploy.sh
# To uninstall:         sudo bash deploy.sh down
# Must be run with sudo.

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

# --- Teardown Function ---
function cleanup() {
    echo -e "\n${BLUE}>>> Checking for and cleaning up any previous installation...${NC}"
    SERVICE_FILE="/etc/systemd/system/cicd_interface.service"
    DEPLOY_DIR="/var/deploy"

    if systemctl is-active --quiet cicd_interface.service; then
        echo -e "${YELLOW}   Found running service. Stopping and disabling...${NC}"
        systemctl stop cicd_interface.service
        systemctl disable cicd_interface.service
    else
        echo -e "${WHITE}   No active service found. Skipping.${NC}"
    fi

    if [ -f "$SERVICE_FILE" ]; then
        echo -e "${YELLOW}   Removing old systemd service file...${NC}"
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
    fi

    if [ -d "$DEPLOY_DIR" ]; then
        echo -e "${YELLOW}   Wiping previous deployment directory '$DEPLOY_DIR'...${NC}"
        rm -rf "$DEPLOY_DIR"
    fi

    echo -e "${WHITE}   Resetting local configuration and state...${NC}"
    # Use git to revert config.py to its original state, ignoring errors if not a git repo
    git checkout HEAD -- config.py &> /dev/null || echo -e "${YELLOW}   Warning: Could not reset config.py via git. Proceeding anyway.${NC}"
    rm -rf certs
    rm -f system_stats.log
    echo -e "${GREEN}   Cleanup complete.${NC}"
}

# --- Main Logic: Handle 'down' argument ---
if [ "$1" == "down" ]; then
    echo -e "${RED}--- Tearing Down Sakadeploy Installation ---${NC}"
    cleanup
    echo -e "\n${GREEN}Sakadeploy has been successfully removed from the system.${NC}"
    exit 0
fi


# --- Full Installation Flow ---
echo -e "${CYAN}----------------------------------------------------${NC}"
echo -e "${CYAN}    Sakadeploy CICD Automated Setup Script    ${NC}"
echo -e "${CYAN}----------------------------------------------------${NC}"

# --- 0. Clean Up Previous Installation ---
cleanup

# --- 1. Install System Dependencies ---
echo -e "\n${BLUE}>>> 1. Checking and installing system dependencies...${NC}"
apt-get update -qq > /dev/null
apt-get install -y ca-certificates curl gnupg python3 python3-pip > /dev/null
echo -e "${GREEN}   System prerequisites installed.${NC}"

# Install Docker Engine
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}   Docker Engine not found. Installing Docker...${NC}"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq > /dev/null
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin > /dev/null
    echo -e "${GREEN}   Docker Engine and Docker Compose Plugin installed successfully.${NC}"
else
    echo -e "${GREEN}   Docker Engine is already installed.${NC}"
fi

if [ -n "$SUDO_USER" ]; then
    usermod -aG docker "$SUDO_USER"
    echo -e "${YELLOW}   User '$SUDO_USER' added to 'docker' group. You may need to log out and back in for this to take full effect.${NC}"
fi

# --- 2. Install Python Dependencies ---
echo -e "\n${BLUE}>>> 2. Installing Python dependencies...${NC}"
pip3 install --break-system-packages -r requirements.txt > /dev/null
echo -e "${GREEN}   Python dependencies installed.${NC}"

# --- 3. Create Deployment Directory ---
echo -e "\n${BLUE}>>> 3. Creating deployment directory...${NC}"
mkdir -p "$DEPLOY_DIR"
chown -R "$SUDO_USER:$SUDO_USER" "$DEPLOY_DIR"
echo -e "${GREEN}   Deployment directory '$DEPLOY_DIR' created.${NC}"

# --- 4. Configure Application ---
echo -e "\n${BLUE}>>> 4. Configuring the application...${NC}"
CONFIG_FILE="config.py"
# Prompt for GitHub PAT
while true; do
    echo -e "\n${YELLOW}   Please enter your GitHub Personal Access Token (PAT). This token requires 'repo' scope.${NC}"
    read -sp "   GitHub PAT: " GITHUB_PAT
    echo
    if [[ -z "$GITHUB_PAT" ]]; then
        echo -e "${RED}   PAT cannot be empty. Please try again.${NC}"
        continue
    fi

    echo -e "${WHITE}   Validating GitHub PAT via API call...${NC}"
    # Use curl to test the token. -s is for silent, -o /dev/null discards body, -w "%{\http_code}" gets status code.
    HTTP_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: token $GITHUB_PAT" https://api.github.com/user)

    if [ "$HTTP_STATUS" -eq 200 ]; then
        echo -e "${GREEN}   Success! GitHub PAT is valid and authenticated correctly.${NC}"
        break
    else
        echo -e "${RED}   Validation Failed! GitHub API responded with HTTP Status: $HTTP_STATUS${NC}"
        if [ "$HTTP_STATUS" -eq 401 ]; then
            echo -e "${RED}   This is a 'Bad Credentials' error. Please check your token for typos, expiration, or incorrect scopes.${NC}"
            echo -e "${YELLOW}   Note: If using SSO, ensure the token is authorized for your organization.${NC}"
        else
            echo -e "${RED}   Please check your network connection and the PAT itself.${NC}"
        fi
        echo -e "${YELLOW}   Please try again.${NC}"
    fi
done
while true; do
    read -sp "   Create an admin password for the web UI: " ADMIN_PASSWORD; echo
    read -sp "   Confirm the admin password: " ADMIN_PASSWORD_CONFIRM; echo
    if [[ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]]; then echo -e "${RED}   Passwords do not match.${NC}"; continue; fi
    if [[ -z "$ADMIN_PASSWORD" ]]; then echo -e "${RED}   Password cannot be empty.${NC}"; continue; fi
    echo -e "${GREEN}   Admin password set.${NC}"; break
done
sed -i "s/GITHUB_PAT = .*/GITHUB_PAT = \"$GITHUB_PAT\"/" "$CONFIG_FILE"
sed -i "s/ADMIN_PASSWORD = .*/ADMIN_PASSWORD = \"$ADMIN_PASSWORD\"/" "$CONFIG_FILE"
echo -e "${GREEN}   Configuration file '$CONFIG_FILE' updated.${NC}"

# --- 5. Generate SSL Certificate ---
echo -e "\n${BLUE}>>> 5. Generating self-signed SSL certificate...${NC}"
python3 generate_certs.py
echo -e "${GREEN}   Self-signed SSL certificate and key generated.${NC}"

# --- 6. Set up Systemd Service ---
echo -e "\n${BLUE}>>> 6. Setting up systemd service...${NC}"
PROJECT_DIR=$(pwd)
SERVICE_USER=${SUDO_USER:-root}
cat > "$SERVICE_FILE" << EOL
[Unit]
Description=Sakadeploy CICD Interface
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
systemctl daemon-reload
systemctl enable cicd_interface.service > /dev/null
systemctl start cicd_interface.service
echo -e "${GREEN}   Systemd service 'cicd_interface' created, enabled, and started.${NC}"

# --- Final Status ---
echo -e "\n${CYAN}----------------------------------------------------${NC}"
echo -e "${GREEN}        Deployment Complete! Sakadeploy is Live!        ${NC}"
echo -e "${CYAN}----------------------------------------------------${NC}"
sleep 3
systemctl status cicd_interface.service --no-pager || echo -e "${RED}Error retrieving service status.${NC}"
IP_ADDRESS=$(curl -s ifconfig.me)
echo -e "\n${GREEN}>>> Access the web interface at: ${NC}${YELLOW}https://${IP_ADDRESS}:8123${NC}"
echo -e "${WHITE}>>> To view live logs, run: ${NC}${CYAN}journalctl -u cicd_interface.service -f${NC}"

exit 0