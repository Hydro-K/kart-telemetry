import os
from flask import Flask, render_template, jsonify
from database.db import init_db
from api.sessions import sessions_bp
from api.upload import upload_bp
from api.karts import karts_bp
from api.analysis import analysis_bp
from api.replay import replay_bp
from api.ai import ai_bp
import config


def create_app():
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_UPLOAD_MB * 1024 * 1024
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    os.makedirs(config.DATA_DIR, exist_ok=True)

    with app.app_context():
        init_db()

    app.register_blueprint(sessions_bp, url_prefix='/api')
    app.register_blueprint(upload_bp, url_prefix='/api')
    app.register_blueprint(karts_bp, url_prefix='/api')
    app.register_blueprint(analysis_bp, url_prefix='/api')
    app.register_blueprint(replay_bp, url_prefix='/api')
    app.register_blueprint(ai_bp, url_prefix='/api')

    # Page routes
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/dashboard/<int:session_id>')
    def dashboard(session_id):
        return render_template('dashboard.html', session_id=session_id)

    @app.route('/replay/<int:session_id>')
    def replay(session_id):
        return render_template('replay.html', session_id=session_id)

    @app.route('/compare')
    def kart_compare():
        return render_template('kart_compare.html')

    @app.route('/lap-compare/<int:session_id>')
    def lap_compare(session_id):
        return render_template('lap_compare.html', session_id=session_id)

    @app.route('/ai/<int:session_id>')
    def ai_assistant(session_id):
        return render_template('ai_assistant.html', session_id=session_id)

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({'error': f'File too large. Max size is {config.MAX_UPLOAD_MB} MB'}), 413

    @app.errorhandler(404)
    def not_found(e):
        return render_template('index.html'), 404

    return app


if __name__ == '__main__':
    import platform
    app = create_app()
    # Disable the stat-based file reloader on Windows — it scans every loaded
    # Python module path and crashes if any referenced drive (e.g. B:\) is absent.
    # use_reloader=False still prints tracebacks; just restart manually after edits.
    use_reloader = platform.system() != 'Windows'
    app.run(host='0.0.0.0', port=5000, debug=True,
            threaded=True, use_reloader=use_reloader)
