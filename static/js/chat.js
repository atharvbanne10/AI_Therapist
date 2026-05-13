(() => {
    const $ = (id) => document.getElementById(id);

    class MindfulChat {
        constructor() {
            this.apiBase = '';
            this.conversationId = null;
            this.conversations = [];
            this.recognition = null;
            this.isRecording = false;
            this.isSpeaking = false;
            this.audioEnabled = false;
            this.currentAudio = null;
            this.voiceModeActive = false;
            this.autoListen = true;
            this.lastInputWasVoice = false;
            this.ttsAvailable = true;

            this.cacheDom();
            this.attach();
            this.initSpeechRecognition();
            this.enableAudioOnInteraction();
            this.loadConversations();
        }

        cacheDom() {
            this.sidebar = $('sidebar');
            this.sidebarBackdrop = $('sidebar-backdrop');
            this.historyList = $('history-list');
            this.newChatBtn = $('new-chat-btn');
            this.sidebarToggle = $('sidebar-toggle');
            this.insightsBtn = $('insights-btn');
            this.insightsModal = $('insights-modal');
            this.insightsBody = $('insights-body');
            this.insightsClose = $('insights-close');

            this.userMenuBtn = $('user-menu-btn');
            this.userMenu = $('user-menu');
            this.logoutBtn = $('logout-btn');

            this.main = $('main');
            this.chatMessages = $('chat-messages');
            this.messageInput = $('message-input');
            this.sendBtn = $('send-btn');
            this.voiceBtn = $('voice-btn');
            this.chatTitle = $('chat-title');

            this.voiceOverlay = $('voice-overlay');
            this.voiceStopBtn = $('voice-stop-btn');
            this.statusText = $('statusText');
            this.statusHint = $('statusHint');
            this.voiceCircle = $('voiceCircle');
            this.waveBars = $('waveBars');
            this.micButton = $('micButton');
        }

        attach() {
            this.newChatBtn.addEventListener('click', () => this.startNewChat());
            this.insightsBtn.addEventListener('click', () => this.openInsights());
            this.insightsClose.addEventListener('click', () => this.closeInsights());
            this.insightsModal.addEventListener('click', (e) => {
                if (e.target === this.insightsModal) this.closeInsights();
            });
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.insightsModal.classList.contains('open')) {
                    this.closeInsights();
                }
            });
            this.sendBtn.addEventListener('click', () => this.sendMessage());
            this.voiceBtn.addEventListener('click', () => this.startVoiceMode());
            this.messageInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });
            this.messageInput.addEventListener('input', () => this.autoResize());

            this.sidebarToggle?.addEventListener('click', () => this.toggleSidebar());
            this.sidebarBackdrop?.addEventListener('click', () => this.toggleSidebar(false));

            this.userMenuBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.userMenu.classList.toggle('open');
            });
            document.addEventListener('click', () => this.userMenu.classList.remove('open'));

            this.logoutBtn.addEventListener('click', async () => {
                await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' });
                window.location.href = '/login';
            });

            this.voiceStopBtn.addEventListener('click', () => this.stopVoiceMode());
            this.micButton.addEventListener('click', () => this.toggleListening());

            // Delegated pill clicks
            this.chatMessages.addEventListener('click', (e) => {
                const pill = e.target.closest('.pill');
                if (pill) {
                    this.messageInput.value = pill.dataset.text;
                    this.sendMessage();
                }
            });
        }

        toggleSidebar(open) {
            const shouldOpen = open ?? !this.sidebar.classList.contains('open');
            this.sidebar.classList.toggle('open', shouldOpen);
            this.sidebarBackdrop.classList.toggle('open', shouldOpen);
        }

        autoResize() {
            const el = this.messageInput;
            el.style.height = 'auto';
            el.style.height = Math.min(el.scrollHeight, 140) + 'px';
        }

        // ============ Conversations ============
        async loadConversations() {
            try {
                const res = await fetch('/api/conversations', { credentials: 'same-origin' });
                if (!res.ok) return;
                const data = await res.json();
                this.conversations = data.conversations || [];
                this.renderHistory();
            } catch (e) {
                console.error('Failed to load conversations', e);
            }
        }

        renderHistory() {
            if (!this.conversations.length) {
                this.historyList.innerHTML = '<div class="history-empty">No conversations yet.<br>Start a new chat below.</div>';
                return;
            }
            this.historyList.innerHTML = this.conversations.map(c => `
                <div class="history-item ${c.id === this.conversationId ? 'active' : ''}" data-id="${c.id}" title="${this.escape(c.title)}">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="opacity:0.6">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                    </svg>
                    <span class="title">${this.escape(c.title)}</span>
                    <button class="delete-btn" data-id="${c.id}" title="Delete">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>
                        </svg>
                    </button>
                </div>
            `).join('');

            this.historyList.querySelectorAll('.history-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    if (e.target.closest('.delete-btn')) return;
                    this.loadConversation(parseInt(item.dataset.id));
                });
            });
            this.historyList.querySelectorAll('.delete-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.deleteConversation(parseInt(btn.dataset.id));
                });
            });
        }

        async loadConversation(id) {
            try {
                const res = await fetch(`/api/conversations/${id}`, { credentials: 'same-origin' });
                if (!res.ok) return;
                const data = await res.json();
                this.conversationId = id;
                if (this.chatTitle) this.chatTitle.textContent = data.conversation.title;
                this.renderHistory();
                this.renderMessages(data.messages);
                this.toggleSidebar(false);
            } catch (e) {
                console.error(e);
            }
        }

        async deleteConversation(id) {
            if (!confirm('Delete this conversation?')) return;
            await fetch(`/api/conversations/${id}`, { method: 'DELETE', credentials: 'same-origin' });
            if (this.conversationId === id) {
                this.conversationId = null;
                this.renderWelcome();
                if (this.chatTitle) this.chatTitle.textContent = 'Mindful AI';
            }
            await this.loadConversations();
        }

        startNewChat() {
            this.conversationId = null;
            if (this.chatTitle) this.chatTitle.textContent = 'New Conversation';
            this.renderWelcome();
            this.renderHistory();
            this.toggleSidebar(false);
            this.messageInput.focus();
        }

        setWelcomeMode(on) {
            if (this.main) this.main.classList.toggle('welcome-mode', !!on);
        }

        renderWelcome() {
            this.setWelcomeMode(true);
            this.chatMessages.innerHTML = `
                <div class="welcome">
                    <div class="welcome-logo">🧠</div>
                    <h1 class="welcome-title">Welcome to <span class="highlight">Mindful AI</span></h1>
                    <p class="welcome-subtitle">A safe space to share, reflect, and grow. What's on your mind today?</p>
                    <div class="suggestion-pills">
                        <div class="pill" data-text="I'm feeling anxious today">I'm feeling anxious today</div>
                        <div class="pill" data-text="Help me manage stress">Help me manage stress</div>
                        <div class="pill" data-text="I need someone to talk to">I need someone to talk to</div>
                        <div class="pill" data-text="I'm having trouble sleeping">I'm having trouble sleeping</div>
                    </div>
                </div>
            `;
        }

        renderMessages(messages) {
            this.chatMessages.innerHTML = '';
            if (!messages.length) {
                this.renderWelcome();
                return;
            }
            this.setWelcomeMode(false);
            messages.forEach(m => {
                this.addMessage(m.content, m.role === 'assistant' ? 'bot' : 'user', false);
            });
            this.scrollToBottom();
        }

        // ============ Sending ============
        async sendMessage(customMessage = null, isVoice = false) {
            const message = (customMessage ?? this.messageInput.value).trim();
            if (!message) return;

            this.lastInputWasVoice = isVoice;

            // Clear welcome if present
            if (this.chatMessages.querySelector('.welcome')) {
                this.chatMessages.innerHTML = '';
            }
            this.setWelcomeMode(false);

            this.addMessage(message, 'user');

            if (!customMessage) {
                this.messageInput.value = '';
                this.autoResize();
            }

            if (!isVoice) this.showTyping();
            this.sendBtn.disabled = true;

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        message,
                        conversation_id: this.conversationId
                    })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Request failed');

                this.conversationId = data.conversation_id;
                this.hideTyping();
                this.addMessage(data.response, 'bot');

                if (data.is_new || !this.conversations.find(c => c.id === data.conversation_id)) {
                    await this.loadConversations();
                } else {
                    // Bump to top
                    await this.loadConversations();
                }

                if (isVoice && this.voiceModeActive && this.audioEnabled) {
                    this.updateVoiceUI('speaking');
                    try {
                        await this.playAudio(data.response);
                    } catch (e) {
                        console.warn('TTS failed', e);
                    }
                    if (this.voiceModeActive) {
                        if (this.autoListen) {
                            this.updateVoiceUI('idle', 'Listening for you…', 'I\'ll listen automatically. Tap mic to mute.');
                            setTimeout(() => this.startListening(), 350);
                        } else {
                            this.updateVoiceUI('idle');
                        }
                    }
                }
            } catch (err) {
                console.error(err);
                this.hideTyping();
                this.addMessage("I'm having trouble connecting right now. Please try again.", 'bot');
                if (isVoice && this.voiceModeActive) {
                    this.updateVoiceUI('idle', 'Connection error', 'Tap mic to try again.');
                }
            } finally {
                this.sendBtn.disabled = false;
            }
        }

        addMessage(text, type, scroll = true) {
            const wrapper = document.createElement('div');
            wrapper.className = `message-wrapper ${type}`;
            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            avatar.textContent = type === 'bot' ? '🧠' : '👤';
            const content = document.createElement('div');
            content.className = 'message-content';
            content.textContent = text;
            wrapper.append(avatar, content);
            this.chatMessages.appendChild(wrapper);
            if (scroll) this.scrollToBottom();
        }

        // ============ Insights ============
        async openInsights() {
            this.insightsModal.classList.add('open');
            this.insightsBody.innerHTML = `
                <div class="insights-loader">
                    <div class="loader-spinner"></div>
                    <p>Reflecting on your conversations…</p>
                </div>`;
            this.insightsBtn.disabled = true;
            try {
                const res = await fetch('/api/insights', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin'
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Could not generate insights');
                this.insightsBody.innerHTML = this.renderMarkdown(data.insights || 'No insights yet.');
            } catch (err) {
                this.insightsBody.innerHTML = `
                    <p style="color: var(--danger);">Something went wrong: ${this.escape(err.message)}</p>
                    <p>Please try again in a moment.</p>`;
            } finally {
                this.insightsBtn.disabled = false;
            }
        }

        closeInsights() {
            this.insightsModal.classList.remove('open');
        }

        // Minimal markdown: **bold**, line breaks, paragraphs
        renderMarkdown(text) {
            const escaped = this.escape(text);
            const withBold = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            return withBold
                .split(/\n\s*\n/)
                .map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`)
                .join('');
        }

        showTyping() {
            const wrapper = document.createElement('div');
            wrapper.className = 'message-wrapper bot typing-message';
            wrapper.innerHTML = `
                <div class="message-avatar">🧠</div>
                <div class="message-content">
                    <div class="typing-indicator">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                    </div>
                </div>
            `;
            this.chatMessages.appendChild(wrapper);
            this.scrollToBottom();
        }

        hideTyping() {
            this.chatMessages.querySelector('.typing-message')?.remove();
        }

        scrollToBottom() {
            requestAnimationFrame(() => {
                this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
            });
        }

        escape(s) {
            return String(s).replace(/[&<>"']/g, c => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
            }[c]));
        }

        // ============ Voice (STT + TTS) ============
        initSpeechRecognition() {
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SR) {
                this.recognition = null;
                return;
            }
            this.recognition = new SR();
            this.recognition.continuous = false;
            this.recognition.interimResults = false;
            this.recognition.lang = 'en-US';

            this.recognition.onstart = () => {
                this.isRecording = true;
                this.updateVoiceUI('listening');
            };

            this.recognition.onresult = (e) => {
                const transcript = e.results[0][0].transcript;
                this.isRecording = false;
                if (!transcript || !transcript.trim()) {
                    this.updateVoiceUI('idle', 'I didn\'t catch that', 'Tap mic to try again.');
                    return;
                }
                this.updateVoiceUI('processing', 'Thinking…');
                this.sendMessage(transcript, true);
            };

            this.recognition.onend = () => {
                if (this.isRecording) {
                    this.isRecording = false;
                    // ended without result
                    if (this.voiceModeActive && !this.isSpeaking) {
                        this.updateVoiceUI('idle');
                    }
                }
            };

            this.recognition.onerror = (e) => {
                this.isRecording = false;
                console.error('Speech error:', e.error);
                let msg = 'Microphone error';
                let hint = 'Tap mic to try again.';
                if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
                    msg = 'Microphone access denied';
                    hint = 'Please allow mic permission in your browser settings.';
                } else if (e.error === 'no-speech') {
                    msg = 'No speech detected';
                    hint = 'Tap mic and try speaking again.';
                } else if (e.error === 'audio-capture') {
                    msg = 'No microphone found';
                    hint = 'Please check your microphone connection.';
                } else if (e.error === 'network') {
                    msg = 'Network error';
                    hint = 'Check your connection and retry.';
                }
                this.updateVoiceUI('idle', msg, hint);
            };
        }

        startVoiceMode() {
            if (!this.recognition) {
                alert('Speech recognition is not supported in this browser. Please use Chrome, Edge, or Safari.');
                return;
            }
            if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
                alert('Voice mode requires HTTPS or localhost.');
                return;
            }
            this.voiceModeActive = true;
            this.voiceOverlay.classList.add('active');
            document.body.style.overflow = 'hidden';
            this.audioEnabled = true; // overlay click counts as gesture
            this.updateVoiceUI('idle', 'Listening for you…', 'I\'ll listen automatically. Tap mic to mute.');
            setTimeout(() => this.startListening(), 300);
        }

        stopVoiceMode() {
            this.voiceModeActive = false;
            this.voiceOverlay.classList.remove('active');
            document.body.style.overflow = '';
            this.stopListening();
            if (this.currentAudio) {
                try { this.currentAudio.pause(); } catch (e) {}
                this.currentAudio = null;
            }
            this.isSpeaking = false;
            this.updateVoiceUI('idle');
        }

        toggleListening() {
            if (this.isRecording) {
                this.stopListening();
            } else if (!this.isSpeaking) {
                this.startListening();
            }
        }

        startListening() {
            if (!this.recognition || this.isRecording || this.isSpeaking) return;
            try {
                this.recognition.start();
            } catch (err) {
                // start() can throw if already started — recover
                console.warn('recognition.start error:', err);
                try {
                    this.recognition.stop();
                    setTimeout(() => {
                        try { this.recognition.start(); } catch (e) { console.error(e); }
                    }, 200);
                } catch (e) {}
            }
        }

        stopListening() {
            if (this.recognition && this.isRecording) {
                try { this.recognition.stop(); } catch (e) {}
            }
        }

        updateVoiceUI(state, text, hint) {
            switch (state) {
                case 'listening':
                    this.isRecording = true;
                    this.isSpeaking = false;
                    this.micButton.classList.add('active');
                    this.micButton.disabled = false;
                    this.voiceCircle.classList.add('listening');
                    this.voiceCircle.classList.remove('speaking');
                    this.waveBars.classList.add('active');
                    this.statusText.textContent = text || 'Listening…';
                    this.statusHint.textContent = hint || 'Speak naturally — I\'m here.';
                    break;
                case 'processing':
                    this.isRecording = false;
                    this.isSpeaking = true;
                    this.micButton.classList.remove('active');
                    this.micButton.disabled = true;
                    this.voiceCircle.classList.remove('listening');
                    this.waveBars.classList.remove('active');
                    this.statusText.textContent = text || 'Thinking…';
                    this.statusHint.textContent = hint || '';
                    break;
                case 'speaking':
                    this.isRecording = false;
                    this.isSpeaking = true;
                    this.micButton.classList.remove('active');
                    this.micButton.disabled = true;
                    this.voiceCircle.classList.remove('listening');
                    this.voiceCircle.classList.add('speaking');
                    this.waveBars.classList.remove('active');
                    this.statusText.textContent = text || 'Speaking…';
                    this.statusHint.textContent = hint || '';
                    break;
                case 'idle':
                default:
                    this.isRecording = false;
                    this.isSpeaking = false;
                    this.micButton.classList.remove('active');
                    this.micButton.disabled = false;
                    this.voiceCircle.classList.remove('listening', 'speaking');
                    this.waveBars.classList.remove('active');
                    this.statusText.textContent = text || 'Tap the mic to start';
                    this.statusHint.textContent = hint || 'Speak naturally — I\'m here.';
                    break;
            }
        }

        async playAudio(text) {
            if (!this.ttsAvailable) {
                return this.speakWithBrowserTTS(text);
            }
            return new Promise(async (resolve, reject) => {
                try {
                    const res = await fetch('/api/text-to-speech', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({ text })
                    });
                    if (!res.ok) {
                        // Fall back to browser TTS
                        console.warn('ElevenLabs TTS unavailable, falling back to browser speech.');
                        this.ttsAvailable = false;
                        try { await this.speakWithBrowserTTS(text); resolve(); } catch (e) { reject(e); }
                        return;
                    }
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    this.currentAudio = new Audio(url);
                    this.currentAudio.onended = () => {
                        URL.revokeObjectURL(url);
                        this.currentAudio = null;
                        resolve();
                    };
                    this.currentAudio.onerror = (e) => {
                        URL.revokeObjectURL(url);
                        this.currentAudio = null;
                        reject(new Error('Audio playback error'));
                    };
                    await this.currentAudio.play();
                } catch (err) {
                    reject(err);
                }
            });
        }

        speakWithBrowserTTS(text) {
            return new Promise((resolve) => {
                if (!('speechSynthesis' in window)) return resolve();
                try { window.speechSynthesis.cancel(); } catch (e) {}
                const utter = new SpeechSynthesisUtterance(text);
                utter.rate = 1.0;
                utter.pitch = 1.0;
                utter.onend = () => resolve();
                utter.onerror = () => resolve();
                window.speechSynthesis.speak(utter);
            });
        }

        enableAudioOnInteraction() {
            const unlock = () => {
                if (this.audioEnabled) return;
                try {
                    const ctx = new (window.AudioContext || window.webkitAudioContext)();
                    if (ctx.state === 'suspended') ctx.resume();
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    gain.gain.value = 0;
                    osc.start(0);
                    osc.stop(0.05);
                    this.audioEnabled = true;
                } catch (e) {
                    this.audioEnabled = true;
                }
            };
            document.addEventListener('click', unlock, { once: true });
            document.addEventListener('touchstart', unlock, { once: true });
            document.addEventListener('keydown', unlock, { once: true });
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        window.mindful = new MindfulChat();
    });
})();
