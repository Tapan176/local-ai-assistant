"""
TAPAN_AI Simple Chat UI with Voice Support
A minimal Tkinter-based chat interface with STT/TTS toggle
"""
import sys
import os
import threading
from pathlib import Path
from datetime import datetime

# Fix Windows encoding
if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')

# Add project root
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
    HAS_TK = True
except ImportError:
    HAS_TK = False
    print("❌ Tkinter not available. Install it or use CLI mode.")

from src.agent.orchestrator import Orchestrator
from src.io.voice import VoiceInterface


class TapanChatUI:
    """Simple chat interface for TAPAN_AI"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("TAPAN_AI - Personal Assistant")
        self.root.geometry("600x700")
        self.root.minsize(400, 500)
        
        # Initialize backend
        self.data_dir = project_root / "data"
        self.agent = Orchestrator(self.data_dir)
        
        # Voice
        self.voice = VoiceInterface()
        self.voice_input_enabled = False
        self.voice_output_enabled = False
        
        # Colors
        self.bg_color = "#1a1a2e"
        self.chat_bg = "#16213e"
        self.user_msg_color = "#0f3460"
        self.bot_msg_color = "#1a1a40"
        self.accent_color = "#e94560"
        self.text_color = "#eaeaea"
        
        self.setup_ui()
        self.show_welcome()
    
    def setup_ui(self):
        """Setup UI components"""
        self.root.configure(bg=self.bg_color)
        
        # Main frame
        main_frame = tk.Frame(self.root, bg=self.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title
        title = tk.Label(
            main_frame, 
            text="🤖 TAPAN_AI", 
            font=("Segoe UI", 18, "bold"),
            bg=self.bg_color,
            fg=self.accent_color
        )
        title.pack(pady=(0, 10))
        
        # Chat area
        chat_frame = tk.Frame(main_frame, bg=self.chat_bg)
        chat_frame.pack(fill=tk.BOTH, expand=True)
        
        self.chat_area = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            font=("Consolas", 11),
            bg=self.chat_bg,
            fg=self.text_color,
            insertbackground=self.text_color,
            relief=tk.FLAT,
            padx=10,
            pady=10,
            state=tk.DISABLED
        )
        self.chat_area.pack(fill=tk.BOTH, expand=True)
        
        # Configure tags for different message types
        self.chat_area.tag_configure("user", foreground="#4fc3f7", font=("Consolas", 11, "bold"))
        self.chat_area.tag_configure("bot", foreground="#81c784", font=("Consolas", 11))
        self.chat_area.tag_configure("system", foreground="#ffb74d", font=("Consolas", 10, "italic"))
        self.chat_area.tag_configure("error", foreground="#ef5350")
        
        # Input frame
        input_frame = tk.Frame(main_frame, bg=self.bg_color)
        input_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Voice buttons
        btn_frame = tk.Frame(input_frame, bg=self.bg_color)
        btn_frame.pack(side=tk.LEFT, padx=(0, 5))
        
        self.mic_btn = tk.Button(
            btn_frame,
            text="🎤",
            font=("Segoe UI", 14),
            bg=self.bot_msg_color,
            fg=self.text_color,
            relief=tk.FLAT,
            width=2,
            command=self.toggle_voice_input
        )
        self.mic_btn.pack(side=tk.LEFT, padx=2)
        
        self.speaker_btn = tk.Button(
            btn_frame,
            text="🔇",
            font=("Segoe UI", 14),
            bg=self.bot_msg_color,
            fg=self.text_color,
            relief=tk.FLAT,
            width=2,
            command=self.toggle_voice_output
        )
        self.speaker_btn.pack(side=tk.LEFT, padx=2)
        
        # Text input
        self.input_entry = tk.Entry(
            input_frame,
            font=("Consolas", 12),
            bg=self.user_msg_color,
            fg=self.text_color,
            insertbackground=self.text_color,
            relief=tk.FLAT
        )
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)
        self.input_entry.bind("<Return>", self.send_message)
        self.input_entry.focus()
        
        # Send button
        self.send_btn = tk.Button(
            input_frame,
            text="➤",
            font=("Segoe UI", 14),
            bg=self.accent_color,
            fg="white",
            relief=tk.FLAT,
            width=3,
            command=self.send_message
        )
        self.send_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready | Voice: Off | TTS: Off")
        status_bar = tk.Label(
            main_frame,
            textvariable=self.status_var,
            font=("Consolas", 9),
            bg=self.bg_color,
            fg="#888"
        )
        status_bar.pack(pady=(5, 0))
    
    def show_welcome(self):
        """Show welcome message"""
        profile = self.agent.profile.to_dict()
        name = profile.get("name", "")
        
        if name:
            welcome = f"Welcome back, {name}! 👋\nKaise ho? Kuch help chahiye?"
        else:
            welcome = "Hello! I'm TAPAN, your personal AI assistant. 🤖\nTell me your name to get started!"
        
        self.add_message("TAPAN", welcome, "bot")
        self.add_message("System", f"Tools loaded: {len(self.agent.tools)} | Type 'help' for commands", "system")
    
    def add_message(self, sender: str, message: str, msg_type: str = "user"):
        """Add message to chat area"""
        self.chat_area.config(state=tk.NORMAL)
        
        timestamp = datetime.now().strftime("%H:%M")
        
        if msg_type == "user":
            prefix = f"\n[{timestamp}] You: "
        elif msg_type == "bot":
            prefix = f"\n[{timestamp}] TAPAN: "
        else:
            prefix = f"\n[{timestamp}] "
        
        self.chat_area.insert(tk.END, prefix, msg_type)
        self.chat_area.insert(tk.END, message + "\n", msg_type)
        
        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)
    
    def send_message(self, event=None):
        """Send message to agent"""
        message = self.input_entry.get().strip()
        if not message:
            return
        
        self.input_entry.delete(0, tk.END)
        self.add_message("You", message, "user")
        
        # Check for exit
        if message.lower() in ['exit', 'quit', 'bye']:
            self.add_message("TAPAN", "Bye! Take care! 👋", "bot")
            self.root.after(1000, self.root.quit)
            return
        
        # Process in thread
        self.status_var.set("Processing...")
        threading.Thread(target=self.process_message, args=(message,), daemon=True).start()
    
    def process_message(self, message: str):
        """Process message in background thread"""
        try:
            response = self.agent.process(message)
            
            # Update UI in main thread
            self.root.after(0, lambda: self.handle_response(response))
            
        except Exception as e:
            self.root.after(0, lambda: self.add_message("Error", str(e), "error"))
            self.root.after(0, lambda: self.status_var.set("Error occurred"))
    
    def handle_response(self, response: str):
        """Handle agent response"""
        self.add_message("TAPAN", response, "bot")
        self.update_status()
        
        # Speak if TTS enabled
        if self.voice_output_enabled and self.voice.has_audio_output:
            threading.Thread(target=self.voice.speak, args=(response,), daemon=True).start()
    
    def toggle_voice_input(self):
        """Toggle voice input"""
        if not self.voice.has_audio_input:
            messagebox.showwarning("Voice", "Microphone not available.\nInstall: pip install SpeechRecognition pyaudio")
            return
        
        self.voice_input_enabled = not self.voice_input_enabled
        
        if self.voice_input_enabled:
            self.mic_btn.config(bg=self.accent_color)
            self.listen_voice()
        else:
            self.mic_btn.config(bg=self.bot_msg_color)
        
        self.update_status()
    
    def listen_voice(self):
        """Listen for voice input"""
        if not self.voice_input_enabled:
            return
        
        self.status_var.set("🎤 Listening...")
        
        def do_listen():
            text = self.voice.listen()
            self.root.after(0, lambda: self.handle_voice_input(text))
        
        threading.Thread(target=do_listen, daemon=True).start()
    
    def handle_voice_input(self, text: str):
        """Handle voice input result"""
        if text and not text.startswith("❌"):
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, text)
            self.add_message("System", f"🎤 Heard: {text}", "system")
        else:
            self.add_message("System", text, "error")
        
        self.update_status()
        self.voice_input_enabled = False
        self.mic_btn.config(bg=self.bot_msg_color)
    
    def toggle_voice_output(self):
        """Toggle voice output (TTS)"""
        if not self.voice.has_audio_output:
            messagebox.showwarning("TTS", "TTS not available.\nInstall: pip install pyttsx3")
            return
        
        self.voice_output_enabled = not self.voice_output_enabled
        
        if self.voice_output_enabled:
            self.speaker_btn.config(text="🔊", bg=self.accent_color)
        else:
            self.speaker_btn.config(text="🔇", bg=self.bot_msg_color)
        
        self.update_status()
    
    def update_status(self):
        """Update status bar"""
        voice_status = "On" if self.voice_input_enabled else "Off"
        tts_status = "On" if self.voice_output_enabled else "Off"
        self.status_var.set(f"Ready | Voice: {voice_status} | TTS: {tts_status}")


def main():
    """Launch TAPAN_AI UI"""
    if not HAS_TK:
        print("❌ Tkinter not available. Run `python start_agent.py` for CLI mode.")
        return
    
    root = tk.Tk()
    app = TapanChatUI(root)
    
    # Handle window close
    root.protocol("WM_DELETE_WINDOW", root.quit)
    
    root.mainloop()


if __name__ == "__main__":
    main()
