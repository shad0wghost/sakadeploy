#!/usr/bin/env python3
# deploy.py
import os
import getpass
import subprocess
import sys
import time
from github import Github, BadCredentialsException
from generate_certs import generate_self_signed_cert
from pathlib import Path

def check_for_sudo():
    """Checks if the script is run with sudo privileges."""
    if os.geteuid() != 0:
        print("Error: This script needs to be run with sudo privileges to set up the system service.")
        print("Please run again using: sudo python3 deploy.py")
        sys.exit(1)

def prompt_for_github_pat():
    """Prompts the user for their GitHub PAT and validates it."""
    while True:
        pat = getpass.getpass("Enter your GitHub Personal Access Token: ")
        if not pat:
            print("PAT cannot be empty.")
            continue
        try:
            g = Github(pat)
            user = g.get_user()
            print(f"Successfully authenticated as GitHub user: {user.login}")
            return pat
        except BadCredentialsException:
            print("Invalid GitHub PAT. Please try again.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return None

def prompt_for_admin_password():
    """Prompts the user to create and confirm an admin password."""
    while True:
        password = getpass.getpass("Enter a new admin password for the web interface: ")
        if not password:
            print("Password cannot be empty.")
            continue
        confirm_password = getpass.getpass("Confirm the admin password: ")
        if password == confirm_password:
            return password
        else:
            print("Passwords do not match. Please try again.")

def update_config_file(pat, password):
    """Updates the config.py file with the provided PAT and password."""
    config_path = 'config.py'
    try:
        # Use existing config content as a base
        with open(config_path, 'r') as f:
            lines = f.readlines()

        with open(config_path, 'w') as f:
            for line in lines:
                if line.strip().startswith('GITHUB_PAT'):
                    f.write(f'GITHUB_PAT = "{pat}"\n')
                elif line.strip().startswith('ADMIN_PASSWORD'):
                    f.write(f'ADMIN_PASSWORD = "{password}"\n')
                else:
                    f.write(line)
        print(f"Successfully updated {config_path}")
        return True
    except Exception as e:
        print(f"An error occurred while updating the config file: {e}")
        return False

def run_command(command, check=True):
    """Runs a shell command and prints its output."""
    print(f"Running command: {' '.join(command)}")
    process = subprocess.run(command, capture_output=True, text=True)
    if process.stdout:
        print(process.stdout)
    if process.stderr:
        print(process.stderr, file=sys.stderr)
    if check and process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command)
    return process

def create_systemd_service_file():
    """Creates the systemd service file content."""
    project_dir = os.path.abspath(os.path.dirname(__file__))
    venv_python_path = os.path.join(project_dir, '.venv', 'bin', 'python3')
    
    service_content = f"""
[Unit]
Description=CICD Management Interface
After=network.target

[Service]
User={getpass.getuser()}
Group={getpass.getuser()}
WorkingDirectory={project_dir}
ExecStart={venv_python_path} {os.path.join(project_dir, 'app.py')}
Restart=always

[Install]
WantedBy=multi-user.target
"""
    service_file_path = "/etc/systemd/system/cicd_interface.service"
    print(f"Creating systemd service file at {service_file_path}...")
    try:
        with open(service_file_path, "w") as f:
            f.write(service_content)
        print("Service file created successfully.")
    except Exception as e:
        print(f"Error creating service file: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    print("--- CICD Management Interface Setup ---")
    
    # This part of the script is for Linux with systemd.
    if sys.platform != "linux":
        print("Warning: System service setup is designed for Linux with systemd.")
    
    # 1. Get and validate GitHub PAT
    github_pat = prompt_for_github_pat()
    if not github_pat:
        print("Setup failed. Could not validate GitHub PAT.")
        return

    # 2. Get and confirm admin password
    admin_password = prompt_for_admin_password()

    # 3. Update config.py
    if not update_config_file(github_pat, admin_password):
        print("Setup failed. Could not update config file.")
        return

    # 4. Generate SSL certificates
    certs_path = Path("certs")
    try:
        generate_self_signed_cert(certs_path)
        print(f"Self-signed SSL certificate and key generated in {certs_path.absolute()}")
    except Exception as e:
        print(f"An error occurred during certificate generation: {e}")
        print("Setup failed.")
        return

    # 5. Check for sudo before proceeding to system-level changes
    check_for_sudo()

    try:
        # 6. Create virtual environment
        print("\n--- Setting up Python Virtual Environment ---")
        run_command(["python3", "-m", "venv", ".venv"])

        # 7. Install dependencies into the virtual environment
        print("\n--- Installing Dependencies ---")
        pip_executable = os.path.join(".venv", "bin", "pip")
        run_command([pip_executable, "install", "-r", "requirements.txt"])

        # 8. Set up systemd service
        print("\n--- Setting up Systemd Service ---")
        create_systemd_service_file()
        run_command(["systemctl", "daemon-reload"])
        run_command(["systemctl", "enable", "cicd_interface.service"])
        run_command(["systemctl", "start", "cicd_interface.service"])
        
        print("\n--- Verifying Service Status ---")
        print("Waiting a moment for the service to initialize...")
        time.sleep(5) # Give the service a few seconds to start
        run_command(["systemctl", "status", "cicd_interface.service"], check=False)

        print("\n--- Setup Complete! ---")
        print("The CICD Management Interface is now running as a system service.")
        print("You can access it at https://<your_server_ip>:8123")
        print("\nTo view logs, run: journalctl -u cicd_interface.service -f")
        print("To stop the service, run: sudo systemctl stop cicd_interface.service")

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"\nAn error occurred during automated setup: {e}", file=sys.stderr)
        print("Please check the error messages above and try to resolve the issue.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
