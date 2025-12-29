import os
import subprocess
import threading
import time
import json
import shutil
import logging
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from github import Github, GithubException
import config

# --- Setup Logging ---
logging.basicConfig(
    filename='sakadeploy.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.urandom(24)

@app.before_request
def log_request_info():
    app.logger.debug(f"Request: {request.method} {request.path} from {request.remote_addr}")

# --- Constants ---
REPO_CACHE_FILE = 'repo_cache.json'

# --- Authentication & Login ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['password'] == config.ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('select_repo'))
        else:
            flash('Invalid password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

def login_required(f):
    def wrap(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# --- GitHub & Project Selection ---
@app.route('/select_repo', methods=['GET', 'POST'])
@login_required
def select_repo():
    if os.path.exists(REPO_CACHE_FILE):
        flash("Using cached repository list. Click 'Refresh List' to fetch updates.", 'info')
        with open(REPO_CACHE_FILE, 'r') as f:
            cache = json.load(f)
        cached_repos = cache['repos']
    else:
        flash("Fetching fresh repository list from GitHub...", 'info')
        g = Github(config.GITHUB_PAT)
        try:
            user = g.get_user()
            fetched_repos = []
            for repo in user.get_repos():
                try:
                    repo.get_contents('/')
                    fetched_repos.append({'name': repo.name, 'full_name': repo.full_name})
                except GithubException as e:
                    if e.status == 404 and "This repository is empty" in e.data.get("message", ""):
                        continue
                    else:
                        flash(f"Error checking repo {repo.name}: {e.data.get('message', str(e))}", 'error')
                        logging.error(f"GitHub API error on repo {repo.name}: {e}")
            with open(REPO_CACHE_FILE, 'w') as f:
                json.dump({'repos': fetched_repos}, f)
            cached_repos = fetched_repos
        except Exception as e:
            flash(f"Error fetching repository list: {e}", 'error')
            logging.error("Failed to fetch repository list.", exc_info=True)
            cached_repos = []
            
    if request.method == 'POST':
        session['selected_repo'] = request.form['repo_name']
        session['repo_full_name'] = next((r['full_name'] for r in cached_repos if r['name'] == session['selected_repo']), None)
        flash(f"Selected repository: {session['selected_repo']}")
        return redirect(url_for('cicd_dashboard'))
        
    return render_template('select_repo.html', repos=cached_repos, selected_repo=session.get('selected_repo'))

@app.route('/refresh_repos', methods=['POST'])
@login_required
def refresh_repos():
    if os.path.exists(REPO_CACHE_FILE):
        os.remove(REPO_CACHE_FILE)
        flash("Repository cache cleared.", 'success')
    return redirect(url_for('select_repo'))

# --- Main Dashboard ---
@app.route('/')
@app.route('/cicd')
@login_required
def cicd_dashboard():
    if not session.get('selected_repo'):
        return redirect(url_for('select_repo'))
    return render_template('cicd_dashboard.html', selected_repo=session['selected_repo'])

# --- API Endpoints ---
@app.route('/api/containers', methods=['GET'])
@login_required
def api_containers():
    repo_name = session.get('selected_repo')
    if not repo_name:
        return jsonify({'error': 'No repository selected'}), 400
    deploy_path = os.path.join('/var/deploy', repo_name)
    compose_file = os.path.join(deploy_path, 'docker-compose.yml')
    if not os.path.exists(compose_file):
        return jsonify([])
    try:
        cmd = ['docker', 'compose', '-f', compose_file, 'ps', '-a', '--format', 'json']
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=deploy_path)
        if result.returncode != 0:
            logging.error(f"Docker compose ps failed: {result.stderr}")
            return jsonify({'error': 'Failed to get container status', 'details': result.stderr}), 500
        containers = []
        raw_output_lines = result.stdout.strip().split('\n')
        for line in raw_output_lines:
            if line:
                try:
                    c = json.loads(line)
                    containers.append({
                        'Service': c.get('Service'),
                        'Name': c.get('Name'),
                        'ID': c.get('ID'),
                        'Image': c.get('Image'),
                        'Command': c.get('Command'),
                        'State': c.get('State'),
                        'Status': c.get('Status'), # Detailed status like 'Up 5 seconds'
                        'Ports': c.get('Ports', '') # Port mappings
                    })
                except json.JSONDecodeError:
                    logging.warning(f"Could not decode JSON line from docker compose ps: {line}")
        return jsonify(containers)
    except Exception as e:
        logging.error("Error in /api/containers:", exc_info=True)
        return jsonify({"error": "Failed to load container data."} ), 500

def stream_process(command, cwd):
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd, bufsize=1)
        for line in iter(process.stdout.readline, ''):
            yield f"data: {line}\n\n"
        process.wait()
    except Exception as e:
        logging.error(f"Error streaming process for command '{' '.join(command)}'", exc_info=True)
        yield f"data: PYTHON ERROR: Check sakadeploy.log for details.\n\n"

def action_streamer(action_generator):
    def generate():
        try:
            yield from action_generator()
        except Exception as e:
            logging.error("Unhandled error in action stream:", exc_info=True)
            yield f"data: --- PYTHON TRACEBACK ---\n\n"
            yield f"data: An unhandled error occurred. See sakadeploy.log for details.\n\n"
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/container_action/<service_name>/<action>', methods=['GET'])
@login_required
def api_container_action(service_name, action):
    repo_name = session.get('selected_repo')
    deploy_path = os.path.join('/var/deploy', repo_name)
    compose_file = os.path.join(deploy_path, 'docker-compose.yml')
    
    def generator():
        if action == 'rm -f':
            # Stop first, then remove
            yield f"data: --- Stopping container {service_name} ---\n\n"
            yield from stream_process(['docker', 'compose', '-f', compose_file, 'stop', service_name], cwd=deploy_path)
            yield f"data: --- Removing container {service_name} ---\n\n"
            yield from stream_process(['docker', 'compose', '-f', compose_file, 'rm', '-f', service_name], cwd=deploy_path)
            yield f"data: --- Container {service_name} removed ---\n\n"
        else:
            # For other actions, proceed as before
            if action not in ['start', 'stop', 'restart']:
                yield f"data: Error: Invalid action '{action}' for container {service_name}.\n\n"
                return
            cmd = ['docker', 'compose', '-f', compose_file] + action.split() + [service_name]
            yield f"data: --- Running 'docker compose {action} {service_name}' ---\n\n"
            yield from stream_process(cmd, cwd=deploy_path)
            yield f"data: --- Action '{action}' on '{service_name}' complete ---\n\n"
    
    return action_streamer(generator)

@app.route('/run_git_action/<action>', methods=['GET'])
@login_required
def run_git_action(action):
    repo_name = session.get('selected_repo')
    repo_full_name = session.get('repo_full_name')
    deploy_path = os.path.join('/var/deploy', repo_name)
    def generator():
        if action == 'pull':
            yield "data: --- Checking local repository ---\n\n"
            if not os.path.exists(os.path.join(deploy_path, '.git')):
                yield f"data: No local repository found. Cloning instead of pulling...\n\n"
                if not repo_full_name:
                    yield "data: Error: Repo full name not in session. Cannot clone.\n\n"
                    return
                git_url = f"https://{config.GITHUB_PAT}@github.com/{repo_full_name}.git"
                os.makedirs(deploy_path, exist_ok=True)
                yield from stream_process(['git', 'clone', git_url, '.'], cwd=deploy_path)
                yield "data: \n--- Repository contents after clone: ---\n\n"
                yield from stream_process(['ls', '-aF'], cwd=deploy_path)
            else:
                yield "data: --- Pulling latest changes from repository ---\n\n"
                yield from stream_process(['git', 'pull'], cwd=deploy_path)
                yield "data: \n--- Repository contents after pull: ---\n\n"
                yield from stream_process(['ls', '-aF'], cwd=deploy_path)
            yield "data: \n--- Git operation complete ---\n\n"
        elif action == 'delete_repo':
            yield f"data: --- Deleting local repository at {deploy_path} ---\n\n"
            if os.path.exists(deploy_path):
                shutil.rmtree(deploy_path)
                yield f"data: Successfully deleted {deploy_path}.\n\n"
            else:
                yield "data: Directory does not exist.\n\n"
            yield "data: \n--- Deletion complete ---\n\n"
    return action_streamer(generator)

@app.route('/run_docker_action/<action>', methods=['GET'])
@login_required
def run_docker_action(action):
    repo_name = session.get('selected_repo')
    repo_full_name = session.get('repo_full_name')
    deploy_path = os.path.join('/var/deploy', repo_name)
    service = request.args.get('service', '')
    def generator():
        if not repo_full_name:
            yield "data: Error: Repo full name not in session.\n\n"
            return
        git_url = f"https://{config.GITHUB_PAT}@github.com/{repo_full_name}.git"
        os.makedirs(deploy_path, exist_ok=True)
        if action == 'redeploy':
            yield "data: --- Starting Full Redeployment ---\n\n"
            if not os.path.exists(os.path.join(deploy_path, '.git')):
                yield f"data: Step 1: Cloning repository...\n\n"
                yield from stream_process(['git', 'clone', git_url, '.'], cwd=deploy_path)
            else:
                yield "data: Step 1: Pulling latest changes...\n\n"
                yield from stream_process(['git', 'pull'], cwd=deploy_path)
            yield "data: \n--- Step 2: Building and starting containers ---\n\n"
            yield from stream_process(['docker', 'compose', '-f', 'docker-compose.yml', 'up', '--build', '-d'], cwd=deploy_path)
            yield "data: \n--- Redeployment complete ---\n\n"
        elif action == 'logs':
            yield f"data: --- Streaming logs for {'all services' if not service else service} ---\n\n"
            cmd = ['docker', 'compose', '-f', 'docker-compose.yml', 'logs', '--follow', '--tail=100']
            if service:
                cmd.append(service)
            yield from stream_process(cmd, cwd=deploy_path)
        else:
             cmd_map = {'stop': ['stop'], 'prune': ['down', '--remove-orphans'], 'build_no_cache': ['build', '--no-cache']}
             if action not in cmd_map:
                 yield "data: Error: Unknown command.\n\n"
                 return
             yield f"data: --- Running 'docker-compose {action}' ---\n\n"
             yield from stream_process(['docker', 'compose', '-f', 'docker-compose.yml'] + cmd_map[action], cwd=deploy_path)
             yield f"data: \n--- Command '{action}' complete ---\n\n"
    return action_streamer(lambda: generator())

if __name__ == '__main__':
    logging.info("Starting Sakadeploy application.")
    try:
        app.run(host='0.0.0.0', port=8123, debug=False, ssl_context=('certs/cert.pem', 'certs/key.pem'))
    except FileNotFoundError:
        logging.warning("SSL certificate/key not found. Running in debug mode without SSL.")
        app.run(host='0.0.0.0', port=8123, debug=True)
    except Exception as e:
        logging.critical("Application failed to start.", exc_info=True)
