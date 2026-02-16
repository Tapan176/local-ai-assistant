"""
TAPAN_AI Portable Web Server
Cross-platform Flask-based UI that works from external storage
Works on: Windows, Linux, macOS, Android (via Termux), any device with Python
"""
import sys
import os
import json
import webbrowser
import threading
from pathlib import Path
from datetime import datetime

# Fix encoding
if sys.platform == 'win32':
  os.system('chcp 65001 >nul 2>&1')

# Add project root
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))

# Flask imports (with graceful error)
try:
  from flask import Flask, render_template_string, request, jsonify, send_from_directory
  HAS_FLASK = True
except ImportError:
  HAS_FLASK = False
  print("❌ Flask not installed. Run: pip install flask")

from src.agent.orchestrator import Orchestrator

# ============== HTML TEMPLATE (Embedded for portability) ==============
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TAPAN_AI - Personal Assistant</title>
  <style>
    :root {
      --bg-primary: #0f0f23;
      --bg-secondary: #1a1a3e;
      --bg-chat: #12122a;
      --accent: #e94560;
      --accent-hover: #ff6b8a;
      --text-primary: #eaeaea;
      --text-secondary: #888;
      --user-msg: #1e3a5f;
      --bot-msg: #2d1f3d;
      --success: #4caf50;
      --border-radius: 12px;
    }

    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
      color: var(--text-primary);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    .container {
      max-width: 800px;
      margin: 0 auto;
      padding: 20px;
      flex: 1;
      display: flex;
      flex-direction: column;
      height: 100vh;
    }

    header {
      text-align: center;
      padding: 20px 0;
    }

    header h1 {
      font-size: 2rem;
      background: linear-gradient(90deg, var(--accent), #ff9a8b);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }

    header p {
      color: var(--text-secondary);
      margin-top: 5px;
    }

    .chat-container {
      flex: 1;
      background: var(--bg-chat);
      border-radius: var(--border-radius);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
    }

    .messages {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 15px;
    }

    .message {
      max-width: 85%;
      padding: 12px 16px;
      border-radius: var(--border-radius);
      line-height: 1.5;
      animation: fadeIn 0.3s ease;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .message.user {
      background: var(--user-msg);
      align-self: flex-end;
      border-bottom-right-radius: 4px;
    }

    .message.bot {
      background: var(--bot-msg);
      align-self: flex-start;
      border-bottom-left-radius: 4px;
    }

    .message .sender {
      font-size: 0.75rem;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }

    .message .content {
      white-space: pre-wrap;
      word-break: break-word;
    }

    .message .time {
      font-size: 0.7rem;
      color: var(--text-secondary);
      text-align: right;
      margin-top: 5px;
    }

    .input-area {
      padding: 15px;
      background: rgba(0, 0, 0, 0.2);
      display: flex;
      gap: 10px;
    }

    .input-area input {
      flex: 1;
      padding: 14px 20px;
      border: none;
      border-radius: 25px;
      background: var(--bg-secondary);
      color: var(--text-primary);
      font-size: 1rem;
      outline: none;
      transition: box-shadow 0.3s;
    }

    .input-area input:focus {
      box-shadow: 0 0 0 2px var(--accent);
    }

    .input-area input::placeholder {
      color: var(--text-secondary);
    }

    .btn {
      padding: 14px 20px;
      border: none;
      border-radius: 25px;
      background: var(--accent);
      color: white;
      font-size: 1rem;
      cursor: pointer;
      transition: all 0.3s;
    }

    .btn:hover {
      background: var(--accent-hover);
      transform: scale(1.05);
    }

    .btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .btn-voice {
      background: var(--bg-secondary);
      font-size: 1.2rem;
    }

    .btn-voice.active {
      background: var(--accent);
      animation: pulse 1.5s infinite;
    }

    @keyframes pulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(233, 69, 96, 0.4); }
      50% { box-shadow: 0 0 0 10px rgba(233, 69, 96, 0); }
    }

    .status-bar {
      text-align: center;
      padding: 10px;
      font-size: 0.8rem;
      color: var(--text-secondary);
    }

    .typing-indicator {
      display: flex;
      gap: 4px;
      padding: 10px;
    }

    .typing-indicator span {
      width: 8px;
      height: 8px;
      background: var(--text-secondary);
      border-radius: 50%;
      animation: typing 1.4s infinite;
    }

    .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
    .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

    @keyframes typing {
      0%, 60%, 100% { transform: translateY(0); }
      30% { transform: translateY(-10px); }
    }

    .quick-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 10px 15px;
      border-top: 1px solid rgba(255,255,255,0.1);
    }

    .quick-btn {
      padding: 6px 12px;
      font-size: 0.8rem;
      background: rgba(255,255,255,0.1);
      border: none;
      border-radius: 15px;
      color: var(--text-secondary);
      cursor: pointer;
      transition: all 0.2s;
    }

    .quick-btn:hover {
      background: var(--accent);
      color: white;
    }

    /* Mobile responsive */
    @media (max-width: 600px) {
      .container {
        padding: 10px;
      }

      header h1 {
        font-size: 1.5rem;
      }

      .message {
        max-width: 90%;
      }

      .quick-actions {
        display: none;
      }
    }

    /* Scrollbar */
    .messages::-webkit-scrollbar {
      width: 6px;
    }

    .messages::-webkit-scrollbar-track {
      background: transparent;
    }

    .messages::-webkit-scrollbar-thumb {
      background: var(--text-secondary);
      border-radius: 3px;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🤖 TAPAN_AI</h1>
      <p>Your Personal AI Assistant | Portable Edition</p>
    </header>

    <div class="chat-container">
      <div class="messages" id="messages">
        <!-- Messages will be inserted here -->
      </div>

      <div class="quick-actions">
        <button class="quick-btn" onclick="sendQuick('show balance')">💰 Balance</button>
        <button class="quick-btn" onclick="sendQuick('list reminders')">⏰ Reminders</button>
        <button class="quick-btn" onclick="sendQuick('show accounts')">📊 Accounts</button>
        <button class="quick-btn" onclick="sendQuick('help')">❓ Help</button>
      </div>

      <div class="input-area">
        <button class="btn btn-voice" id="voiceBtn" onclick="toggleVoice()" title="Voice Input">🎤</button>
        <input type="text" id="userInput" placeholder="Type a message... (or use voice)" 
             onkeypress="if(event.key==='Enter') sendMessage()">
        <button class="btn" onclick="sendMessage()" id="sendBtn">Send ➤</button>
      </div>
    </div>

    <div class="status-bar" id="status">
      Ready | Device: <span id="deviceInfo"></span>
    </div>
  </div>

  <script>
    // Initialize
    document.addEventListener('DOMContentLoaded', () => {
      addBotMessage("Hello! Main TAPAN hoon, tumhara personal AI assistant. 👋\\n\\nKaise madad kar sakta hoon?");
      document.getElementById('deviceInfo').textContent = navigator.platform;
      document.getElementById('userInput').focus();
    });

    // Send message
    async function sendMessage() {
      const input = document.getElementById('userInput');
      const text = input.value.trim();

      if (!text) return;

      input.value = '';
      addUserMessage(text);

      // Show typing
      const typingId = showTyping();

      try {
        const response = await fetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });

        const data = await response.json();
        removeTyping(typingId);

        if (data.success) {
          addBotMessage(data.response);
        } else {
          addBotMessage("❌ " + (data.error || "Something went wrong"));
        }
      } catch (error) {
        removeTyping(typingId);
        addBotMessage("❌ Connection error: " + error.message);
      }
    }

    // Quick action
    function sendQuick(text) {
      document.getElementById('userInput').value = text;
      sendMessage();
    }

    // Add messages
    function addUserMessage(text) {
      addMessage(text, 'user', 'You');
    }

    function addBotMessage(text) {
      addMessage(text, 'bot', 'TAPAN');
    }

    function addMessage(text, type, sender) {
      const messages = document.getElementById('messages');
      const now = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

      const div = document.createElement('div');
      div.className = 'message ' + type;
      div.innerHTML = `
        <div class="sender">${sender}</div>
        <div class="content">${escapeHtml(text)}</div>
        <div class="time">${now}</div>
      `;

      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }

    // Typing indicator
    function showTyping() {
      const messages = document.getElementById('messages');
      const id = 'typing-' + Date.now();

      const div = document.createElement('div');
      div.id = id;
      div.className = 'message bot';
      div.innerHTML = `
        <div class="typing-indicator">
          <span></span><span></span><span></span>
        </div>
      `;

      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
      return id;
    }

    function removeTyping(id) {
      const el = document.getElementById(id);
      if (el) el.remove();
    }

    // Voice input (Web Speech API)
    let recognition = null;
    let isListening = false;

    function toggleVoice() {
      if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        alert('Voice input not supported in this browser. Try Chrome or Edge.');
        return;
      }

      const btn = document.getElementById('voiceBtn');

      if (isListening) {
        recognition.stop();
        isListening = false;
        btn.classList.remove('active');
        btn.textContent = '🎤';
        return;
      }

      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      recognition = new SpeechRecognition();
      recognition.lang = 'en-IN';  // English-India for Hinglish
      recognition.interimResults = false;

      recognition.onstart = () => {
        isListening = true;
        btn.classList.add('active');
        btn.textContent = '🔴';
        document.getElementById('status').textContent = '🎤 Listening...';
      };

      recognition.onresult = (event) => {
        const text = event.results[0][0].transcript;
        document.getElementById('userInput').value = text;
        document.getElementById('status').textContent = 'Ready';
      };

      recognition.onerror = (event) => {
        console.error('Speech error:', event.error);
        document.getElementById('status').textContent = 'Voice error: ' + event.error;
      };

      recognition.onend = () => {
        isListening = false;
        btn.classList.remove('active');
        btn.textContent = '🎤';
      };

      recognition.start();
    }

    // Escape HTML
    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
  </script>
</body>
</html>
"""

# ============== FLASK APP ==============

def create_app(data_dir: Path = None):
  """Create Flask application"""
  if not HAS_FLASK:
    return None

  app = Flask(__name__)

  # Initialize agent
  data_dir = data_dir or project_root / "data"
  agent = Orchestrator(data_dir)

  @app.route('/')
  def index():
    """Serve main page"""
    return render_template_string(HTML_TEMPLATE)

  @app.route('/chat', methods=['POST'])
  def chat():
    """Handle chat messages"""
    try:
      data = request.get_json()
      message = data.get('message', '').strip()

      if not message:
        return jsonify({'success': False, 'error': 'Empty message'})

      # Process message
      response = agent.process(message)

      return jsonify({
        'success': True,
        'response': response
      })
    except Exception as e:
      return jsonify({
        'success': False,
        'error': str(e)
      })

  @app.route('/status')
  def status():
    """Get system status"""
    return jsonify({
      'status': 'running',
      'tools': len(agent.tools),
      'tool_names': list(agent.tools.keys())
    })

  @app.route('/health')
  def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})

  return app


def run_server(host='0.0.0.0', port=5000, open_browser=True):
  """Run the web server"""
  if not HAS_FLASK:
    print("❌ Flask not installed. Run: pip install flask")
    print("   Or use CLI mode: python start_agent.py")
    return

  app = create_app()

  print("=" * 50)
  print("   TAPAN_AI - Portable Web Interface")
  print("=" * 50)
  print(f"\n🌐 Server running at: http://localhost:{port}")
  print(f"📱 Network access: http://0.0.0.0:{port}")
  print("\n💡 Tips:")
  print("   - Open in any browser on any device")
  print("   - Works on: Windows, Linux, Mac, Android, iOS")
  print("   - Press Ctrl+C to stop\n")

  # Open browser on desktop
  if open_browser and sys.platform in ['win32', 'darwin', 'linux']:
    def open_delayed():
      import time
      time.sleep(1)
      webbrowser.open(f'http://localhost:{port}')
    threading.Thread(target=open_delayed, daemon=True).start()

  # Run server
  try:
    app.run(host=host, port=port, debug=False, threaded=True)
  except KeyboardInterrupt:
    print("\n👋 Server stopped. Bye!")


if __name__ == '__main__':
  import argparse

  parser = argparse.ArgumentParser(description='TAPAN_AI Web Server')
  parser.add_argument('--host', default='0.0.0.0', help='Host to bind (default: 0.0.0.0)')
  parser.add_argument('--port', type=int, default=5000, help='Port (default: 5000)')
  parser.add_argument('--no-browser', action='store_true', help='Don\'t open browser')

  args = parser.parse_args()
  run_server(host=args.host, port=args.port, open_browser=not args.no_browser)
