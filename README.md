# SakaDeploy CI/CD Management Interface

**Repository:** https://github.com/shad0wghost/sakadeploy

## Project Overview

SakaDeploy is a lightweight, self-hosted web application that provides a powerful, user-friendly interface for managing your entire Docker environment and deploying Docker Compose-based projects from private GitHub repositories. It is designed to eliminate the need for repeated SSH access and command-line interaction, allowing you to control your server's Docker containers and project deployments from a secure web UI.

The dashboard is split into two main concepts: **System-Wide Controls** for managing all containers and images on the server, and **Project-Specific Controls** for deploying and managing individual applications from Git.

### Key Features:

*   **System-Wide Container Management:**
    *   View all Docker containers on the system (running or stopped).
    *   Perform actions on any container: `Start`, `Stop`, `Restart`, `Logs`, and `Delete`.
    *   Highlighting for containers that belong to the currently selected deployment project.
*   **Project Deployment from GitHub:**
    *   Securely connects to your GitHub account using a Personal Access Token (PAT).
    *   Intelligently caches your repository list for a fast and responsive UI.
    *   Provides project-specific controls: `Redeploy (Pull & Build)`, `Git Pull`, `Start/Stop Project`, `Prune Project`, and `Build (No Cache)`.
    *   Force-rebuild individual containers within a project.
*   **Global System Controls:**
    *   `Prune All Containers`: A powerful, one-click action to stop and remove every container on the system.
    *   `Prune All Images`: Reclaim disk space by removing all unused Docker images.
    *   `Delete Local Repo`: Remove a project's cloned repository from the server.
*   **Live Monitoring & Feedback:**
    *   Real-time dashboard with live-updating graphs for **CPU Usage**, **RAM Usage**, and **Network I/O** (Mbps).
    *   Live progress bar for **Disk Usage**.
    *   A live terminal output for all Git and Docker operations, showing you every step of the process.
*   **Secure & Robust:**
    *   Password-protected web interface.
    *   Automated deployment script (`deploy.sh`) for easy installation, re-installation, and uninstallation.
    *   Hardened against command injection vulnerabilities.
    *   Runs as a persistent `systemd` service.

## The Dashboard Explained

![SakaDeploy Dashboard](https://i.imgur.com/your-screenshot-url.png) <!-- Replace with a real screenshot URL -->

1.  **System Monitoring:** At the top, you get a live overview of your server's health.
2.  **System-Wide Container Management:** This is your main Docker control panel. It lists *every* container on the host machine. Containers belonging to the project you've selected in the top-right dropdown are highlighted in blue. You can manage any container from here, regardless of which project it belongs to.
3.  **Project Deployment Controls:** These actions are *specific to the repository you have selected*. For example, clicking "Stop Project" will only stop the containers defined in that project's `docker-compose.yml`.
4.  **Global System Controls:** These are powerful, destructive actions that affect the entire Docker environment on your server, such as removing all containers or images.
5.  **Live Output:** All actions you trigger will stream their full, unabbreviated terminal output here in real-time.

## Getting Started (Deployment)

This project is designed for Debian/Ubuntu-based Linux servers.

### Prerequisites:

*   A Linux VPS (e.g., Ubuntu, Debian).
*   A GitHub Personal Access Token (PAT) with `repo` scope.

### Deployment Steps:

1.  **Clone the Repository:** SSH into your remote server and clone the SakaDeploy repository.

    ```bash
    git clone https://github.com/shad0wghost/sakadeploy.git
    cd sakadeploy
    ```

2.  **Run the Deployment Script:** Execute the `deploy.sh` script with `sudo`. This script is idempotent, meaning you can re-run it at any time to perform a "factory reset" and start a fresh installation.

    ```bash
    sudo bash deploy.sh
    ```

    The script will guide you through the setup, including validating your GitHub PAT and creating an admin password. It automates everything: dependency installation, SSL certificate generation, and systemd service setup.

3.  **Access the Web Interface:** After the script completes, it will display the URL to access your SakaDeploy instance (e.g., `https://<YOUR_SERVER_IP>:8123`).

## Usage

*   **Initial Login:** Use the admin password you set during deployment. You will be prompted to select a repository.
*   **Selecting a Project:** The dropdown caches your repositories. If you've added a new repo to GitHub, click the "Refresh List" button to fetch it. Selecting a project will highlight its containers in the management table below and enable the "Project Deployment Controls".
*   **First Deployment:** For a new project, click the green **"Redeploy (Pull & Build)"** button. This will clone the repository to `/var/deploy/<project_name>` and start the services defined in its `docker-compose.yml`.
*   **Updating a Project:** To deploy an update you've pushed to Git, simply click **"Redeploy (Pull & Build)"** again. This will pull the latest code and intelligently restart only the necessary containers.

## Troubleshooting

*   **Service fails to start:** The application is likely crashing due to a Python error. Check the detailed application logs, not just journalctl:
    ```bash
    tail -f /root/sakadeploy/sakadeploy.log
    ```
*   **"Bad Credentials" error:** Your GitHub PAT is invalid, has expired, or (if you're using a GitHub Organization) has not been authorized for SSO. Generate a new token and re-run `sudo bash deploy.sh`.
*   **CSS/Styles are broken:** Perform a hard refresh in your browser (Ctrl+Shift+R or Cmd+Shift+R) to clear its cache.

## Managing the Service

*   **Uninstall SakaDeploy:**
    ```bash
    sudo bash /path/to/sakadeploy/deploy.sh down
    ```
*   **Manual Service Control:**
    *   Restart: `sudo systemctl restart cicd_interface.service`
    *   Stop: `sudo systemctl stop cicd_interface.service`
    *   View Status: `systemctl status cicd_interface.service`

---
*This README has been updated to reflect the final feature set of the SakaDeploy application.*