// TAPAN_AI v2 // Cinematic Interface Logic

// ── State ─────────────────────────────────────────────────────────
const state = {
    sessionId: crypto.randomUUID(),
    socket: null,
    isSpeaking: false,
    isListening: false,
    recognition: null,
    voices: [],
    selectedVoice: null,
};

// ── DOM Elements ──────────────────────────────────────────────────
const dom = {
    chatHistory: document.getElementById('chat-history'),
    userInput: document.getElementById('user-input'),
    sendBtn: document.getElementById('send-btn'),
    voiceBtn: document.getElementById('voice-toggle'),
    statusDot: document.querySelector('.status-dot'),
    statusText: document.querySelector('.status-text'),
};

// ── WebSocket ─────────────────────────────────────────────────────
function connect() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/ws/${state.sessionId}`;
    
    state.socket = new WebSocket(url);

    state.socket.onopen = () => {
        dom.statusDot.style.background = '#00ff88';
        dom.statusText.innerText = 'ONLINE';
        dom.statusText.style.color = '#00ff88';
        console.log('Connected to Neural Core');
    };

    state.socket.onclose = () => {
        dom.statusDot.style.background = '#ff3366';
        dom.statusText.innerText = 'OFFLINE';
        dom.statusText.style.color = '#ff3366';
        setTimeout(connect, 3000); // Auto-reconnect
    };

    state.socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleResponse(data);
    };
}

function handleResponse(data) {
    // Reset UI state
    setLoading(false);

    // 1. Render text
    addMessage(data.text, 'assistant');
    
    // 2. Speak
    speak(data.text);
}

// ── Chat UI ───────────────────────────────────────────────────────
function setLoading(loading) {
    dom.userInput.disabled = loading;
    dom.sendBtn.disabled = loading;
    if (loading) {
        dom.userInput.placeholder = "Processing...";
        dom.sendBtn.classList.add('loading');
        dom.statusText.innerText = 'THINKING...';
        dom.statusText.style.color = '#ff3366';
    } else {
        dom.userInput.placeholder = "Type a command or speak...";
        dom.sendBtn.classList.remove('loading');
        dom.statusText.innerText = 'ONLINE';
        dom.statusText.style.color = '#00ff88';
        dom.userInput.focus();
    }
}

function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    
    if (window.marked && role === 'assistant') {
        bubble.innerHTML = marked.parse(text);
    } else {
        bubble.innerText = text;
    }
    
    div.appendChild(bubble);
    dom.chatHistory.appendChild(div);
    scrollToBottom();
}

function scrollToBottom() {
    dom.chatHistory.scrollTop = dom.chatHistory.scrollHeight;
}

function sendMessage() {
    const text = dom.userInput.value.trim();
    if (!text) return;

    setLoading(true);
    addMessage(text, 'user');
    state.socket.send(text); // WebSocket handles string directly
    dom.userInput.value = '';
}

dom.sendBtn.addEventListener('click', sendMessage);
dom.userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
});

// ── Voice Interface (Web Speech API) ──────────────────────────────
function initVoice() {
    if (!('webkitSpeechRecognition' in window)) {
        dom.voiceBtn.style.display = 'none';
        return;
    }

    state.recognition = new webkitSpeechRecognition();
    state.recognition.continuous = false;
    state.recognition.interimResults = false;
    state.recognition.lang = 'en-US';

    state.recognition.onstart = () => {
        state.isListening = true;
        dom.voiceBtn.classList.add('active');
        dom.userInput.placeholder = "Listening...";
    };

    state.recognition.onend = () => {
        state.isListening = false;
        dom.voiceBtn.classList.remove('active');
        dom.userInput.placeholder = "Type a command or speak...";
    };

    state.recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        if (transcript) {
            dom.userInput.value = transcript;
            sendMessage();
        }
    };

    dom.voiceBtn.addEventListener('click', () => {
        if (state.isListening) state.recognition.stop();
        else state.recognition.start();
    });

    // TTS Setup
    window.speechSynthesis.onvoiceschanged = () => {
        state.voices = window.speechSynthesis.getVoices();
        // Prefer a "natural" or "bot" voice
        state.selectedVoice = state.voices.find(v => v.name.includes('Natural') || v.name.includes('Google US English')) || state.voices[0];
    };
}

function speak(text) {
    if (!text) return;
    
    // Cancel previous speech
    window.speechSynthesis.cancel();

    // Strip markdown for speech
    const cleanText = text.replace(/[*_#`]/g, ''); 
    const utterance = new SpeechSynthesisUtterance(cleanText);
    
    if (state.selectedVoice) utterance.voice = state.selectedVoice;
    utterance.rate = 1.0;
    utterance.pitch = 1.0;

    utterance.onstart = () => {
        state.isSpeaking = true;
        pulseAvatar(true);
    };
    
    utterance.onend = () => {
        state.isSpeaking = false;
        pulseAvatar(false);
    };

    window.speechSynthesis.speak(utterance);
}


// ── 3D Visualizer (Three.js Brain Simulation) ──────────────────────
let scene, camera, renderer, brainGroup, particles, lines, outerRing;

function init3D() {
    const container = document.getElementById('avatar-canvas');
    const width = container.clientWidth;
    const height = container.clientHeight;

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
    camera.position.z = 15;

    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    brainGroup = new THREE.Group();
    scene.add(brainGroup);

    const positions = [];
    const colors = [];
    
    // Reference Colors: Cyan/Teal glow with subtle purple/blue depths
    const colorCore = new THREE.Color(0x00ff88); // Green accent
    const colorDepth = new THREE.Color(0x004422); // Deep green
    
    const particleCount = 3500; // Increased density

    for (let i = 0; i < particleCount; i++) {
        // Brain consists of two hemispheres
        const isRight = Math.random() > 0.5;
        const centerX = isRight ? 2.2 : -2.2; // Slightly closer
        
        // Random spherical coords
        const u = Math.random();
        const v = Math.random();
        const theta = 2 * Math.PI * u;
        const phi = Math.acos(2 * v - 1);
        
        // Detailed noise for gyri/sulci
        const angleNoise = Math.sin(theta * 8) * Math.cos(phi * 7);
        const r = 5.0 + Math.random() * 0.8 + angleNoise * 0.5;
        
        // Ellipsoid scaling
        let x = r * Math.sin(phi) * Math.cos(theta);
        let y = r * Math.sin(phi) * Math.sin(theta) * 0.85; 
        let z = r * Math.cos(phi) * 1.1;
        
        // Medial flattening
        if (isRight && x < 0) x *= 0.1;
        if (!isRight && x > 0) x *= 0.1;
        
        // Color variation: Outer edge is brighter cyan, inner is deeper blue
        const distanceFromCenter = Math.sqrt(x*x + y*y + z*z) / 6.0;
        const mixedColor = new THREE.Color().lerpColors(colorDepth, colorCore, distanceFromCenter);
        
        positions.push(x + centerX, y, z);
        colors.push(mixedColor.r, mixedColor.g, mixedColor.b);
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

    const pMat = new THREE.PointsMaterial({
        size: 0.1,
        vertexColors: true,
        transparent: true,
        opacity: 0.9,
        blending: THREE.AdditiveBlending
    });

    particles = new THREE.Points(geometry, pMat);
    brainGroup.add(particles);

    // Synaptic Connections (Lines)
    const lineMat = new THREE.LineBasicMaterial({
        color: 0x00ff88,
        transparent: true,
        opacity: 0.15,
        blending: THREE.AdditiveBlending
    });
    
    const linePos = [];
    const connectLimit = 1500;
    let connected = 0;
    
    // Generate connections
    for (let i = 0; i < positions.length / 3; i+=2) { // More samples
        if (connected > connectLimit) break;
        
        const x1 = positions[i*3];
        const y1 = positions[i*3+1];
        const z1 = positions[i*3+2];
        
        // Only connect surface-ish particles for the "glow" look
        // Simple heuristic: check magnitude approximately
        // if (x1*x1 + y1*y1 + z1*z1 < 10) continue; 

        for (let j = i + 1; j < positions.length / 3; j+=10) {
            const x2 = positions[j*3];
            const y2 = positions[j*3+1];
            const z2 = positions[j*3+2];
            
            const distSq = (x1-x2)**2 + (y1-y2)**2 + (z1-z2)**2;
            
            if (distSq < 2.5 && distSq > 0.1) { 
                linePos.push(x1, y1, z1);
                linePos.push(x2, y2, z2);
                connected++;
            }
        }
    }
    
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(linePos, 3));
    lines = new THREE.LineSegments(lineGeo, lineMat);
    brainGroup.add(lines);

    // Orbital Rings (HUD Effect from reference)
    const ringGeo = new THREE.RingGeometry(8, 8.1, 64);
    const ringMat = new THREE.MeshBasicMaterial({ 
        color: 0x00ff88, 
        side: THREE.DoubleSide, 
        transparent: true, 
        opacity: 0.3,
        blending: THREE.AdditiveBlending
    });
    outerRing = new THREE.Mesh(ringGeo, ringMat);
    outerRing.rotation.x = Math.PI / 2;
    brainGroup.add(outerRing);

    const ringGeo2 = new THREE.RingGeometry(9, 9.05, 64);
    const ringMat2 = new THREE.MeshBasicMaterial({ 
        color: 0x00aa55, 
        side: THREE.DoubleSide, 
        transparent: true, 
        opacity: 0.15,
        blending: THREE.AdditiveBlending
    });
    const outerRing2 = new THREE.Mesh(ringGeo2, ringMat2);
    outerRing2.rotation.x = Math.PI / 2.2;
    outerRing2.rotation.y = Math.PI / 8;
    brainGroup.add(outerRing2);

    animate();
}

function animate() {
    requestAnimationFrame(animate);
    
    brainGroup.rotation.y += 0.002;
    if (outerRing) {
        outerRing.rotation.z -= 0.001;
        outerRing.scale.setScalar(1 + Math.sin(Date.now() * 0.001) * 0.02);
    }

    const time = Date.now() * 0.001;

    // Pulse effect when speaking
    if (state.isSpeaking) {
        const scale = 1 + Math.sin(time * 10) * 0.05;
        brainGroup.scale.set(scale, scale, scale);
        
        // Active brain activity colors
        particles.material.size = 0.15;
        lines.material.opacity = 0.3;
    } else {
        // Idle breathing
        const scale = 1 + Math.sin(time * 2) * 0.02;
        brainGroup.scale.set(scale, scale, scale);
        particles.material.size = 0.1;
        lines.material.opacity = 0.15;
    }
    
    renderer.render(scene, camera);
}

function pulseAvatar(active) {
    // Handled in animate loop
}

// ── Init ──────────────────────────────────────────────────────────
window.addEventListener('load', () => {
    connect();
    initVoice();
    init3D();
});
