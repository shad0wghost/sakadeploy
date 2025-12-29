# Sakadeploy

**Repository:** https://github.com/shad0wghost/sakadeploy

## Project Overview

The Sakadeploy is a lightweight, self-hosted web application designed to simplify the continuous integration and continuous deployment (CICD) of Docker Compose-based projects on your remote server. It provides a secure, web-based control panel to manage your private GitHub repositories, deploy updates, monitor Docker container health, and view system resource utilization, all without needing direct SSH access or command-line interaction after initial setup.

### Key Features:

*   **Secure Access:** Password-protected web interface accessible via HTTPS (with a self-signed certificate).
*   **GitHub Integration:** Connects to your private GitHub repositories using a Personal Access Token (PAT).
*   **Repository Discovery:** Automatically lists GitHub repositories containing a `docker-compose.yml` file, identifying them as deployable projects.
*   **Centralized Deployment:** Clones and manages selected projects in a dedicated `/var/deploy/<project_name>` directory on your server.
*   **Docker Compose Control:** Intuitive buttons for common Docker Compose operations:
    *   `Redeploy`: Pulls latest code, rebuilds, and restarts services.
    *   `Stop All`: Stops all services for the selected project.
    *   `Prune (Down)`: Stops and removes containers, networks, and volumes for the selected project.
    *   `Build (No Cache)`: Rebuilds services without using Docker's build cache.
*   **Container-Specific Actions:** View individual containers, their status, and perform actions like `Start`, `Stop`, `Restart`, `Delete`, and `Logs` for each one.
*   **Live Terminal Output:** Real-time streaming of all Docker Compose command outputs directly to the web interface for quick debugging.
*   **System Resource Monitoring:** Live graphs for CPU, RAM, and Disk usage, providing a rolling window of recent historical data (stored in a text file, no database required).
*   **Persistent Service:** Deploys as a systemd service, ensuring the interface starts automatically on server boot.

## Getting Started (Deployment)

This project is designed to be deployed on a Linux server (tested on Debian/Ubuntu-based systems). The `deploy.sh` script automates the entire setup process.

### Prerequisites:

*   A fresh Linux VPS (e.g., Ubuntu, Debian).
*   Basic understanding of `sudo` and SSH.
*   A GitHub Personal Access Token (PAT) with `repo` scope for accessing your private repositories. 

### Deployment Steps:

1.  **Clone the Repository:** SSH into your remote server and clone this repository.

    ```bash
    git clone https://github.com/shad0wghost/sakadeploy.git
    cd sakadeploy
    ```

2.  **Run the Deployment Script:** Execute the `deploy.sh` script with `sudo`.

    ```bash
    sudo bash deploy.sh
    ```

    The script will:
    *   Update package lists and install necessary system dependencies (Docker, Docker Compose, Python3, pip3).
    *   Prompt you for your GitHub PAT and validate it.
    *   Prompt you to set a strong admin password for the web interface.
    *   Update the `config.py` file with your provided credentials.
    *   Generate a self-signed SSL certificate in the `certs/` directory.
    *   Create the `/var/deploy` directory for project management.
    *   Set up and start the `cicd_interface.service` as a systemd service, ensuring it runs persistently and starts on boot.

3.  **Access the Web Interface:** After the script completes, it will display the URL to access your Sakadeploy.

    ```
    >>> You can access the web interface at: https://<YOUR_SERVER_IP>:8123
    ```

    Open this URL in your web browser. You will likely see a certificate warning because it's a self-signed certificate. You can safely proceed past this warning for a development/internal setup.

4.  **Login:** Use the admin password you set during the `deploy.sh` script execution.

## Usage

Once logged in, you will be directed to the repository selection page:

1.  **Select Repository:** Choose a GitHub repository from the dropdown. Only repositories containing a `docker-compose.yml` file will be listed.
2.  **CICD Dashboard:** After selecting a repository, you'll see the main dashboard.
    *   **System Monitoring:** View live CPU, RAM, and Disk usage graphs.
    *   **Container Management:** See a list of your Docker containers for the selected project, their status, and buttons to `Start`, `Stop`, `Restart`, `Delete`, or view `Logs` for individual containers.
    *   **Deployment Controls:** Use the main buttons (`Redeploy`, `Stop All`, etc.) to perform global actions on your selected Docker Compose project.
    *   **Live Output:** All command outputs will stream in real-time to the console at the bottom of the page.

## `cicd-test` Project (Example)

Included in this repository is a sample project called `cicd-test` designed to demonstrate the capabilities of the interface. This project consists of two Docker containers:

*   **`fileserver` (Nginx):** A simple Nginx container that hosts an `index.html` file.
*   **`webserver` (Apache):** An Apache web server container that, on startup, fetches the `index.html` from the `fileserver` and then serves it on port 80.

You can use this project to test the deployment and management features of your Sakadeploy. Simply push the `cicd-test` directory to a GitHub repository, and your interface should discover and allow you to deploy it.

## Troubleshooting

*   **Service not starting:** Check the systemd journal for errors:
    ```bash
    journalctl -u cicd_interface.service -f
    ```
*   **Docker commands failing:** Ensure the user running the service (`$SUDO_USER` from `deploy.sh`) has permissions to run Docker commands. You might need to log out and back in after deployment for `docker` group changes to take effect.
*   **GitHub API errors:** Double-check your GitHub PAT and its scopes.
*   **SSL certificate warnings:** These are expected with self-signed certificates. Proceed past the warning in your browser.

## Development

To manage the service manually:

*   Stop: `sudo systemctl stop cicd_interface.service`
*   Start: `sudo systemctl start cicd_interface.service`
*   Restart: `sudo systemctl restart cicd_interface.service`
*   Disable (prevent auto-start): `sudo systemctl disable cicd_interface.service`
*   View Status: `systemctl status cicd_interface.service`

