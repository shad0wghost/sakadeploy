import os
import subprocess
import threading
import time
import json
import shutil
import logging
import psutil
from collections import deque
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
STATS_FILE = 'system_stats.log'
MAX_STATS_LINES = 1000
STATS_INTERVAL_SECONDS = 2

# --- System Stats Background Thread ---
stats_thread = None
stop_stats_thread = threading.Event()
last_net_io = psutil.net_io_counters()

def collect_system_stats():
    global last_net_io
    while not stop_stats_thread.is_set():
        try:
            time.sleep(STATS_INTERVAL_SECONDS)
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            timestamp = int(time.time())
            current_net_io = psutil.net_io_counters()
            bytes_sent = current_net_io.bytes_sent - last_net_io.bytes_sent
            bytes_recv = current_net_io.bytes_recv - last_net_io.bytes_recv
            last_net_io = current_net_io
            mbps_sent = (bytes_sent * 8) / (STATS_INTERVAL_SECONDS * 1024 * 1024)
            mbps_recv = (bytes_recv * 8) / (STATS_INTERVAL_SECONDS * 1024 * 1024)
            
            line = json.dumps({
                'ts': timestamp, 'cpu': cpu, 'ram': ram, 'disk': disk,
                'net_sent': round(mbps_sent, 2), 'net_recv': round(mbps_recv, 2)
            })
            
            lines = deque(maxlen=MAX_STATS_LINES - 1)
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, 'r') as f:
                    lines.extend(f.readlines())
            lines.append(line + '\n')
            with open(STATS_FILE, 'w') as f:
                f.writelines(lines)
        except Exception as e:
            logging.error("Error in stats collection thread:", exc_info=True)
            time.sleep(STATS_INTERVAL_SECONDS)

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
    return render_template('cicd_dashboard.html', selected_repo=session.get('selected_repo'))

# --- API Endpoints ---
@app.route('/api/system_stats')
@login_required
def api_system_stats():
    try:
        if not os.path.exists(STATS_FILE):
            return jsonify([])
        with open(STATS_FILE, 'r') as f:
            data = [json.loads(line) for line in f if line.strip()]
        return jsonify(data)
    except Exception as e:
        logging.error("Error in /api/system_stats:", exc_info=True)
        return jsonify({"error": "Failed to load system stats."} ), 500
        
@app.route('/api/containers')
@login_required
def api_containers():
    selected_project = session.get('selected_repo')
    try:
        cmd = ['docker', 'ps', '-a', '--format', '{{json .}}']
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logging.error(f"Docker ps failed: {result.stderr}")
            return jsonify({'error': 'Failed to get container status', 'details': result.stderr}), 500
        
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    container_data = json.loads(line)
                    # FIX: Manually parse the labels string
                    labels_str = container_data.get('Labels', '')
                    project_label = ''
                    service_label = ''
                    for label in labels_str.split(','):
                        if 'com.docker.compose.project=' in label:
                            project_label = label.split('=')[-1]
                        if 'com.docker.compose.service=' in label:
                            service_label = label.split('=')[-1]

                    container_data['is_project_container'] = (selected_project is not None and project_label.lower() == selected_project.lower())
                    container_data['compose_service'] = service_label # Add the service name to the data
                    containers.append(container_data)
                except json.JSONDecodeError:
                    logging.warning(f"Could not decode JSON line from docker ps: {line}")
        return jsonify(containers)
    except Exception as e:
        logging.error("Error in /api/containers:", exc_info=True)
        return jsonify({"error": "Failed to load container data."} ), 500

def stream_process(command, cwd=None):
    logging.debug(f"Streaming command: {' '.join(command)}")
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd, bufsize=1)
        for line in iter(process.stdout.readline, ''):
            logging.debug(f"Streamed line: {line.strip()}")
            yield f"data: {line}\n\n"
        process.wait()
    except Exception as e:
        logging.error(f"Error streaming process", exc_info=True)
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

@app.route('/api/container_action/<container_id>/<action>', methods=['GET'])
@login_required
def api_container_action(container_id, action):
    service_name = request.args.get('service_name')
    repo_name = session.get('selected_repo')

    def generator():
        if action == 'rebuild':
            if not repo_name or not service_name:
                yield "data: Error: A project and service must be selected to rebuild.\n\n"
                return
            deploy_path = os.path.join('/var/deploy', repo_name)
            compose_file = os.path.join(deploy_path, 'docker-compose.yml')
            yield f"data: --- Step 1: Rebuilding service '{service_name}' with no cache ---\n\n"
            yield from stream_process(['docker', 'compose', '-f', compose_file, 'build', '--no-cache', service_name], cwd=deploy_path)
            yield f"data: \n--- Step 2: Re-creating and starting service '{service_name}' ---\n\n"
            yield from stream_process(['docker', 'compose', '-f', compose_file, 'up', '-d', '--force-recreate', service_name], cwd=deploy_path)
            yield f"data: \n--- Rebuild of '{service_name}' complete ---\n\n"
        elif action == 'rm':
            yield f"data: --- Stopping container {container_id[:12]} ---\n\n"
            yield from stream_process(['docker', 'stop', container_id])
            yield f"data: --- Removing container {container_id[:12]} ---\n\n"
            yield from stream_process(['docker', 'rm', container_id])
            yield f"data: --- Container {container_id[:12]} removed ---\n\n"
        elif action == 'logs':
            yield f"data: --- Streaming logs for {container_id[:12]} ---\n\n"
            yield from stream_process(['docker', 'logs', '--follow', '--tail', '100', container_id])
        elif action in ['start', 'stop', 'restart']:
            cmd = ['docker', action, container_id]
            yield f"data: --- Running 'docker {action} {container_id[:12]}' ---\n\n"
            yield from stream_process(cmd)
            yield f"data: --- Action '{action}' on '{container_id[:12]}' complete ---\n\n"
        else:
            yield f"data: Error: Invalid action '{action}'.\n\n"
    return action_streamer(generator)

@app.route('/run_git_action/<action>', methods=['GET'])
@login_required
def run_git_action(action):
    repo_name = session.get('selected_repo')
    if not repo_name:
        return Response("data: Error: No repository selected. Please select one first.\n\n", mimetype='text/event-stream')
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
            yield f"data: \n--- Deletion complete ---\n\n"
    return action_streamer(generator)

@app.route('/run_docker_action/<action>', methods=['GET'])
@login_required
def run_docker_action(action):
    repo_name = session.get('selected_repo')
    if not repo_name and action not in ['prune_images', 'prune_containers']:
         return Response("data: Error: No repository selected. Please select one first.\n\n", mimetype='text/event-stream')
    repo_full_name = session.get('repo_full_name')
    deploy_path = os.path.join('/var/deploy', repo_name)
    def generator():
        if repo_name:
            os.makedirs(deploy_path, exist_ok=True)
            
        if action == 'redeploy':
            if not repo_full_name:
                yield "data: Error: Repo full name not in session.\n\n"
                return
            git_url = f"https://{config.GITHUB_PAT}@github.com/{repo_full_name}.git"
            yield "data: --- Starting Full Redeployment ---\n\n"
            if not os.path.exists(os.path.join(deploy_path, '.git')):
                yield f"data: Step 1: Cloning repository...\n\n"
                yield from stream_process(['git', 'clone', git_url, '.'], cwd=deploy_path)
            else:
                yield f"data: Step 1: Pulling latest changes...\n\n"
                yield from stream_process(['git', 'pull'], cwd=deploy_path)
            yield "data: \n--- Step 2: Building and starting containers ---\n\n"
            yield from stream_process(['docker', 'compose', '-f', os.path.join(deploy_path, 'docker-compose.yml'), 'up', '--build', '-d', '--force-recreate'], cwd=deploy_path)
            yield "data: \n--- Redeployment complete ---\n\n"
        elif action == 'logs':
            if not repo_name:
                yield "data: Error: No project selected for docker-compose logs.\n\n"
                return
            yield f"data: --- Streaming logs for project {repo_name} ---\n\n"
            cmd = ['docker', 'compose', '-f', os.path.join(deploy_path, 'docker-compose.yml'), 'logs', '--follow', '--tail=100']
            yield from stream_process(cmd, cwd=deploy_path)
        else:
             cmd_map = {
                'start': ['start'],
                'stop': ['stop'],
                'prune': ['down', '--remove-orphans'],
                'build_no_cache': ['build', '--no-cache'],
                'prune_images': ['image', 'prune', '-a', '-f'],
                'prune_containers': ['container', 'prune', '-f']
             }
             if action not in cmd_map:
                 yield "data: Error: Unknown command.\n\n"
                 return
             
             if action == 'prune_images' or action == 'prune_containers':
                 full_cmd = ['docker'] + cmd_map[action]
                 yield f"data: --- Running global command: '{' '.join(full_cmd)}' ---\n\n"
                 if action == 'prune_containers':
                     yield "data: --- Stopping all running containers first ---\n\n"
                     yield from stream_process(['docker', 'stop', '$(docker ps -q)'], cwd='/')
                 yield from stream_process(full_cmd)
             else:
                 # Project-specific docker-compose commands
                 full_cmd = ['docker', 'compose', '-f', os.path.join(deploy_path, 'docker-compose.yml')] + cmd_map[action]
                 yield f"data: --- Running 'docker-compose {action}' ---\n\n"
                 yield from stream_process(full_cmd, cwd=deploy_path)
             yield f"data: \n--- Command '{action}' complete ---\n\n"
    return action_streamer(generator)

if __name__ == '__main__':
    logging.info("Starting Sakadeploy application with System Monitoring.")
    stats_thread = threading.Thread(target=collect_system_stats)
    stats_thread.daemon = True
    stats_thread.start()
    
    try:
        app.run(host='0.0.0.0', port=8123, debug=False, ssl_context=('certs/cert.pem', 'certs/key.pem'))
    except FileNotFoundError:
        logging.warning("SSL certificate/key not found. Running in debug mode without SSL.")
        app.run(host='0.0.0.0', port=8123, debug=True)
    except Exception as e:
        logging.critical("Application failed to start.", exc_info=True)
    finally:
        stop_stats_thread.set()
        if stats_thread:
            stats_thread.join()
