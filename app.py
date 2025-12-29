import os
import subprocess
import threading
import time
import json
import psutil
from collections import deque
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from github import Github, GithubException
import config

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Constants ---
STATS_FILE = 'system_stats.log'
MAX_STATS_LINES = 5000
REPO_CACHE_FILE = 'repo_cache.json'
REPO_CACHE_EXPIRY_SECONDS = 900  # 15 minutes

# --- System Stats Collection ---
stats_thread = None
stop_stats_thread = threading.Event()

def collect_system_stats():
    """A background thread to collect and store system stats."""
    # ... (rest of the function is unchanged)
    while not stop_stats_thread.is_set():
        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            timestamp = int(time.time())
            line = json.dumps({'ts': timestamp, 'cpu': cpu, 'ram': ram, 'disk': disk})
            
            if os.path.exists(STATS_FILE):
                with open(STATS_FILE, 'r') as f:
                    lines = deque(f, maxlen=MAX_STATS_LINES -1)
            else:
                lines = deque(maxlen=MAX_STATS_LINES -1)
            lines.append(line + '\n')
            
            with open(STATS_FILE, 'w') as f:
                f.writelines(lines)
        except Exception as e:
            print(f"Error in stats collection thread: {e}")
        time.sleep(5)

# --- Authentication & Login ---
# ... (this section is unchanged)
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

# --- GitHub & Project Selection (with Caching) ---
@app.route('/select_repo', methods=['GET', 'POST'])
@login_required
def select_repo():
    # --- Caching Logic ---
    if os.path.exists(REPO_CACHE_FILE):
        with open(REPO_CACHE_FILE, 'r') as f:
            cache = json.load(f)
        age = time.time() - cache['timestamp']
        if age < REPO_CACHE_EXPIRY_SECONDS:
            minutes_left = int((REPO_CACHE_EXPIRY_SECONDS - age) / 60)
            flash(f"Using cached repository list. It will refresh automatically in {minutes_left} minutes.", 'info')
            # The cached data is already in the correct format
            cached_repos = cache['repos']
            
            if request.method == 'POST':
                session['selected_repo'] = request.form['repo_name']
                session['repo_full_name'] = next((r['full_name'] for r in cached_repos if r['name'] == session['selected_repo']), None)
                flash(f"Selected repository: {session['selected_repo']}")
                return redirect(url_for('cicd_dashboard'))
                
            return render_template('select_repo.html', repos=cached_repos, selected_repo=session.get('selected_repo'))

    # --- Cache Miss or Expired: Fetch from GitHub ---
    flash("Fetching fresh repository list from GitHub...", 'info')
    g = Github(config.GITHUB_PAT)
    try:
        user = g.get_user()
        fetched_repos = []
        for repo in user.get_repos():
            try:
                repo.get_contents('/') # Check if repo is empty
                # Store a simple dict, not the complex PyGithub object
                fetched_repos.append({'name': repo.name, 'full_name': repo.full_name})
            except GithubException as e:
                if e.status == 404 and "This repository is empty" in e.data.get("message", ""):
                    continue
                else:
                    flash(f"Error checking repository {repo.name}: {e.data.get('message', str(e))}", 'error')
        
        # Save to cache
        with open(REPO_CACHE_FILE, 'w') as f:
            json.dump({'timestamp': int(time.time()), 'repos': fetched_repos}, f)
        
        repos = fetched_repos
    except Exception as e:
        flash(f"Error fetching repository list: {e}", 'error')
        repos = []
        
    if request.method == 'POST':
        session['selected_repo'] = request.form['repo_name']
        session['repo_full_name'] = next((r['full_name'] for r in repos if r['name'] == session['selected_repo']), None)
        flash(f"Selected repository: {session['selected_repo']}")
        return redirect(url_for('cicd_dashboard'))
        
    return render_template('select_repo.html', repos=repos, selected_repo=session.get('selected_repo'))

@app.route('/refresh_repos', methods=['POST'])
@login_required
def refresh_repos():
    """Endpoint to clear the repository cache."""
    if os.path.exists(REPO_CACHE_FILE):
        os.remove(REPO_CACHE_FILE)
        flash("Repository cache cleared.", 'success')
    return redirect(url_for('select_repo'))

# --- Main Dashboard & APIs (mostly unchanged) ---
# ... (The rest of app.py remains the same as before)
@app.route('/')
@app.route('/cicd')
@login_required
def cicd_dashboard():
    if not session.get('selected_repo'):
        return redirect(url_for('select_repo'))
    return render_template('cicd_dashboard.html', selected_repo=session['selected_repo'])

# ... (API endpoints are unchanged)
@app.route('/api/system_stats')
@login_required
def api_system_stats():
    if not os.path.exists(STATS_FILE):
        return jsonify([])
    with open(STATS_FILE, 'r') as f:
        data = [json.loads(line) for line in f]
    return jsonify(data)

@app.route('/api/containers')
@login_required
def api_containers():
    repo_name = session.get('selected_repo')
    if not repo_name:
        return jsonify({'error': 'No repository selected'}), 400
        
    deploy_path = os.path.join('/var/deploy', repo_name)
    compose_file = os.path.join(deploy_path, 'docker-compose.yml')

    if not os.path.exists(compose_file):
        return jsonify([]) # No compose file, no containers to show
        
    cmd = ['docker', 'compose', '-f', compose_file, 'ps', '--format', 'json']
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=deploy_path)
    
    if result.returncode != 0:
        return jsonify({'error': 'Failed to get container status', 'details': result.stderr}), 500
        
    try:
        containers = [json.loads(line) for line in result.stdout.strip().split('\n') if line]
    except json.JSONDecodeError:
        try:
            containers = [json.loads(result.stdout)]
        except json.JSONDecodeError:
             return jsonify({'error': 'Failed to parse docker-compose output', 'details': result.stdout}), 500

    return jsonify(containers)

@app.route('/api/container_action/<service_name>/<action>', methods=['POST'])
@login_required
def api_container_action(service_name, action):
    repo_name = session.get('selected_repo')
    deploy_path = os.path.join('/var/deploy', repo_name)
    compose_file = os.path.join(deploy_path, 'docker-compose.yml')
    
    if action not in ['start', 'stop', 'restart', 'rm -f']:
        return jsonify({'status': 'error', 'message': 'Invalid action'}), 400

    cmd = ['docker', 'compose', '-f', compose_file] + action.split() + [service_name]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=deploy_path)
    
    def generate():
        for line in iter(process.stdout.readline, ''):
            yield f"data: {line}\n\n"
        process.wait()
        yield f"data: --- Action '{action}' on '{service_name}' complete---\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route('/run_action/<action>', methods=['POST'])
@login_required
def run_action(action):
    repo_name = session.get('selected_repo')
    repo_full_name = session.get('repo_full_name')
    deploy_path = os.path.join('/var/deploy', repo_name)
    
    if not repo_full_name:
        return Response("data: Error: Repository full name not found in session.\n\n", mimetype='text/event-stream')

    git_url = f"https://{config.GITHUB_PAT}@{repo_full_name.split('/')[0]}.github.com/{repo_full_name}.git"
    service = request.args.get('service', '')
    
    def stream_process(command):
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=deploy_path, bufsize=1)
        for line in iter(process.stdout.readline, ''):
            yield f"data: {line}\n\n"
        process.wait()
        
def generate():
        os.makedirs(deploy_path, exist_ok=True)
        # ... (rest of the function is unchanged)
        if action == 'deploy':
            yield "data: --- Starting Deployment---\n\n"
            if not os.path.exists(os.path.join(deploy_path, '.git')):
                yield f"data: No existing repository found. Cloning into {deploy_path}...\n\n"
                yield from stream_process(['git', 'clone', git_url, '.'])
            else:
                yield "data: Existing repository found. Fetching latest changes...\n\n"
                yield from stream_process(['git', 'pull'])
            
            yield "data: \n--- Building and starting containers---\n\n"
            yield from stream_process(['docker', 'compose', '-f', 'docker-compose.yml', 'up', '--build', '-d'])
            yield "data: \n--- Deployment complete---\n\n"
        elif action == 'logs':
            yield f"data: --- Streaming logs for {{'all services' if not service else service}}---\n\n"
            cmd = ['docker', 'compose', '-f', 'docker-compose.yml', 'logs', '--follow', '--tail=100']
            if service:
                cmd.append(service)
            yield from stream_process(cmd)
        else:
             cmd_map = {
                'stop': ['stop'],
                'prune': ['down', '--remove-orphans'],
                'build_no_cache': ['build', '--no-cache'],
             }
             if action not in cmd_map:
                 yield "data: Error: Unknown command.\n\n"
                 return
             yield f"data: --- Running 'docker-compose {action}'---\n\n"
             yield from stream_process(['docker', 'compose', '-f', 'docker-compose.yml'] + cmd_map[action])
             yield f"data: \n--- Command '{action}' complete---\n\n"

    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    stats_thread = threading.Thread(target=collect_system_stats)
    stats_thread.daemon = True
    stats_thread.start()
    
    cert_path = 'certs/cert.pem'
    key_path = 'certs/key.pem'
    
    try:
        app.run(host='0.0.0.0', port=8123, debug=False, ssl_context=(cert_path, key_path))
    except FileNotFoundError:
        print("WARNING: SSL certificate/key not found. Run generate_certs.py or deploy.sh first.")
        app.run(host='0.0.0.0', port=8123, debug=True)
    finally:
        stop_stats_thread.set()
        if stats_thread:
            stats_thread.join()
