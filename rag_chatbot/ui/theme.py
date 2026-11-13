JS_LIGHT_THEME = """
() => {
    let voiceSession = null;
    let voiceReplyPending = false;
    let voiceTranscriptReady = false;
    const voicePanel = () => document.querySelector("#voice-panel");
    const setVoicePanel = (content) => {
        const panel = voicePanel();
        if (panel) panel.innerHTML = content;
    };
    let voiceStarting = false;
    const encodeWav = (samples, sampleRate) => {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);
        const write = (offset, text) => [...text].forEach(
            (character, index) => view.setUint8(offset + index, character.charCodeAt(0))
        );
        write(0, "RIFF");
        view.setUint32(4, 36 + samples.length * 2, true);
        write(8, "WAVE"); write(12, "fmt "); view.setUint32(16, 16, true);
        view.setUint16(20, 1, true); view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true); view.setUint16(34, 16, true);
        write(36, "data"); view.setUint32(40, samples.length * 2, true);
        samples.forEach((sample, index) => {
            const value = Math.max(-1, Math.min(1, sample));
            view.setInt16(44 + index * 2, value < 0 ? value * 32768 : value * 32767, true);
        });
        return new Uint8Array(buffer);
    };
    const toBase64 = (bytes) => {
        let binary = "";
        const chunkSize = 0x8000;
        for (let index = 0; index < bytes.length; index += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
        }
        return `data:audio/wav;base64,${btoa(binary)}`;
    };
    const submitAudioPayload = (payload) => {
        const input = document.querySelector("#voice-input textarea, #voice-input input");
        if (!input) return false;
        const setter = Object.getOwnPropertyDescriptor(
            input instanceof HTMLTextAreaElement
                ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype,
            "value"
        ).set;
        setter.call(input, payload);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
    };
    const clearAudioPayload = () => {
        const input = document.querySelector("#voice-input textarea, #voice-input input");
        if (!input) return;
        const setter = Object.getOwnPropertyDescriptor(
            input instanceof HTMLTextAreaElement
                ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype,
            "value"
        ).set;
        setter.call(input, "");
    };
    const startVoiceRecorder = async () => {
        if (voiceSession || voiceStarting) return;
        voiceStarting = true;
        clearAudioPayload();
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const context = new AudioContext();
            const analyser = context.createAnalyser();
            analyser.fftSize = 128;
            const source = context.createMediaStreamSource(stream);
            const processor = context.createScriptProcessor(4096, 1, 1);
            const chunks = [];
            source.connect(analyser);
            source.connect(processor);
            processor.connect(context.destination);
            processor.onaudioprocess = (event) => {
                if (voiceSession) chunks.push(
                    new Float32Array(event.inputBuffer.getChannelData(0))
                );
            };
            const startedAt = Date.now();
            voiceSession = {
                stream, context, analyser, processor, chunks,
                finish: (cancel = false) => {
                    const session = voiceSession;
                    voiceSession = null;
                    if (session.timeout) clearTimeout(session.timeout);
                    const sampleRate = context.sampleRate;
                    stream.getTracks().forEach((track) => track.stop());
                    processor.disconnect();
                    context.close();
                    if (cancel) {
                        voiceTranscriptReady = false;
                        clearAudioPayload();
                        setVoicePanel("");
                        return;
                    }
                    const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
                    if (!length || Date.now() - startedAt < 250) {
                        setVoicePanel("");
                        return;
                    }
                    const samples = new Float32Array(length);
                    let offset = 0;
                    chunks.forEach((chunk) => {
                        samples.set(chunk, offset);
                        offset += chunk.length;
                    });
                    voiceTranscriptReady = true;
                    setVoicePanel(`
                        <div class="voice-overlay" role="status" aria-live="polite">
                            <div class="voice-overlay-card">
                                <div class="voice-spinner"></div>
                                <strong>Processing</strong>
                                <small>Transcribing your new recording...</small>
                            </div>
                        </div>
                    `);
                    if (!submitAudioPayload(toBase64(encodeWav(samples, sampleRate)))) {
                        setVoicePanel("");
                    }
                },
            };
            voiceSession.timeout = setTimeout(() => stopVoiceSession(false), 30000);
            voiceStarting = false;
            setVoicePanel(`
                <div class="voice-overlay" role="dialog" aria-modal="true">
                    <div class="voice-overlay-card">
                        <canvas id="voice-canvas" width="320" height="120"></canvas>
                        <strong>Listening</strong>
                        <small>Speak naturally. Stop when you are finished.</small>
                        <div class="voice-controls">
                            <button id="voice-cancel" type="button">Cancel</button>
                            <button id="voice-stop" type="button">Done</button>
                        </div>
                    </div>
                </div>
            `);
            document.querySelector("#voice-cancel")?.addEventListener(
                "click", () => stopVoiceSession(true)
            );
            document.querySelector("#voice-stop")?.addEventListener(
                "click", () => stopVoiceSession(false)
            );
            const canvas = document.querySelector("#voice-canvas");
            const draw = () => {
                if (!voiceSession || !canvas) return;
                const data = new Uint8Array(analyser.frequencyBinCount);
                analyser.getByteFrequencyData(data);
                const context2d = canvas.getContext("2d");
                context2d.clearRect(0, 0, canvas.width, canvas.height);
                const width = canvas.width / data.length;
                data.forEach((value, index) => {
                    const height = Math.max(4, (value / 255) * canvas.height);
                    context2d.fillStyle = `rgba(154, 164, 255, ${0.45 + value / 510})`;
                    context2d.fillRect(index * width, (canvas.height - height) / 2, width - 2, height);
                });
                voiceSession.animation = requestAnimationFrame(draw);
            };
            draw();
        } catch (error) {
            voiceStarting = false;
            setVoicePanel(`
                <div class="voice-overlay" role="alert">
                    <div class="voice-overlay-card">
                        <strong>Microphone unavailable</strong>
                        <small>The recorder could not be initialized. Please reload and try again.</small>
                    </div>
                </div>
            `);
        }
    };
    const stopVoiceSession = (cancel = false) => {
        if (!voiceSession) return;
        if (voiceSession.animation) cancelAnimationFrame(voiceSession.animation);
        voiceSession.finish(cancel);
    };
    const setupVoiceRecorder = () => {
        const launcher = document.querySelector(
            "#voice-launcher button, button#voice-launcher"
        );
        if (!launcher || launcher.dataset.voiceReady === "true") return;
        launcher.dataset.voiceReady = "true";
        launcher.addEventListener("click", startVoiceRecorder);
    };
    const setupVoiceReplies = () => {
        document.querySelectorAll("#chatbot-main, #history-chatbot").forEach(
            (chatbot) => {
                if (chatbot.dataset.voiceReplyReady === "true") return;
                chatbot.dataset.voiceReplyReady = "true";
                const existingReplies = chatbot.querySelectorAll(
                    ".message.bot, [data-testid='bot']"
                );
                let lastReply = existingReplies.length
                    ? existingReplies[existingReplies.length - 1].innerText.trim()
                    : "";
                let timer;
                const speak = () => {
                    if (!("speechSynthesis" in window)) return;
                    const replies = chatbot.querySelectorAll(
                        ".message.bot, [data-testid='bot']"
                    );
                    const latest = replies[replies.length - 1];
                    const text = latest ? latest.innerText.trim() : "";
                    if (!voiceReplyPending || !text || text === lastReply) return;
                    lastReply = text;
                    voiceReplyPending = false;
                    window.speechSynthesis.cancel();
                    setVoicePanel(`
                        <div class="voice-overlay" role="status" aria-live="polite">
                            <div class="voice-overlay-card">
                                <div class="voice-orb" aria-hidden="true">
                                    <span></span><span></span><span></span><span></span><span></span>
                                </div>
                                <strong>Speaking</strong>
                                <small>Your assistant is responding.</small>
                                <div class="voice-controls">
                                    <button id="voice-stop-speaking" type="button">Stop</button>
                                </div>
                            </div>
                        </div>
                    `);
                    const utterance = new SpeechSynthesisUtterance(text);
                    const finishSpeaking = () => setVoicePanel("");
                    utterance.onend = finishSpeaking;
                    utterance.onerror = finishSpeaking;
                    document.querySelector("#voice-stop-speaking")?.addEventListener(
                        "click", () => {
                            window.speechSynthesis.cancel();
                            finishSpeaking();
                        }
                    );
                    window.speechSynthesis.speak(utterance);
                };
                new MutationObserver(() => {
                    clearTimeout(timer);
                    timer = setTimeout(speak, 900);
                    chatbot.scrollTop = chatbot.scrollHeight;
                }).observe(chatbot, {
                    childList: true,
                    subtree: true,
                    characterData: true,
                });
            }
        );
    };
    setupVoiceRecorder();
    setupVoiceReplies();
    document.addEventListener("change", (event) => {
        if (event.target.closest("#history-selector")) {
            voiceReplyPending = false;
            voiceTranscriptReady = false;
        }
    });
    document.addEventListener("click", (event) => {
        if (event.target.closest("#new-chat-button, #history-selector")) {
            voiceReplyPending = false;
            voiceTranscriptReady = false;
        }
        if (event.target.closest("#history-message-input button:last-child")) {
            voiceReplyPending = voiceTranscriptReady;
            voiceTranscriptReady = false;
        }
    });
    document.addEventListener("keydown", (event) => {
        if (
            voiceTranscriptReady &&
            event.key === "Enter" &&
            event.target.closest("#history-message-input textarea")
        ) {
            voiceReplyPending = true;
            voiceTranscriptReady = false;
        }
    });
    setInterval(setupVoiceRecorder, 1000);
    setInterval(setupVoiceReplies, 1500);
    document.addEventListener("click", (event) => {
        if (event.target.closest(".stop_btn")) {
            window.speechSynthesis?.cancel();
        }
    });
}
"""

CSS = """
:root {
    --app-bg: #f7f8fc;
    --surface: rgba(255, 255, 255, 0.9);
    --surface-muted: #f1f3f8;
    --border: #e4e8f0;
    --text: #172033;
    --muted: #748096;
    --accent: #5b5ce2;
    --accent-soft: #eeefff;
    --danger: #c94f67;
    --shadow: 0 18px 55px rgba(27, 38, 72, 0.08);
}

body.dark, .dark {
    --app-bg: #0e1220;
    --surface: rgba(24, 30, 48, 0.92);
    --surface-muted: #171d2d;
    --border: #293149;
    --text: #edf1ff;
    --muted: #9da8c2;
    --accent: #9b9cff;
    --accent-soft: #29294c;
    --shadow: 0 18px 55px rgba(0, 0, 0, 0.25);
}

body, .gradio-container {
    background: var(--app-bg) !important;
    color: var(--text);
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.gradio-container {
    max-width: 1440px !important;
    padding: 22px clamp(14px, 3vw, 46px) 34px !important;
}

.app-header {
    align-items: center;
    display: flex;
    gap: 14px;
    margin: 4px 0 22px;
}

.app-header h1 {
    color: var(--text);
    font-size: clamp(20px, 2.4vw, 29px);
    letter-spacing: -0.04em;
    margin: 0;
}

.app-header p {
    color: var(--muted);
    font-size: 13px;
    margin: 3px 0 0;
}

.brand-mark {
    align-items: center;
    background: linear-gradient(135deg, #7778f5, #b27aff);
    border-radius: 14px;
    box-shadow: 0 8px 20px rgba(91, 92, 226, .28);
    color: white;
    display: flex;
    font-size: 22px;
    height: 44px;
    justify-content: center;
    width: 44px;
}

.status-pill {
    background: var(--accent-soft);
    border-radius: 999px;
    color: var(--accent);
    font-size: 12px;
    margin-left: auto;
    padding: 8px 12px;
}

.status-pill i {
    background: #35c981;
    border-radius: 50%;
    display: inline-block;
    height: 7px;
    margin-right: 6px;
    width: 7px;
}

.tabs {
    border-bottom: 1px solid var(--border);
    gap: 8px;
}

.tab-nav button {
    background: transparent !important;
    border: 0 !important;
    color: var(--muted) !important;
    font-size: 13px;
    font-weight: 600;
}

.tab-nav button.selected {
    color: var(--accent) !important;
    box-shadow: inset 0 -2px var(--accent);
}

.contain, .block, .form, .gr-box, .gr-panel {
    border-color: var(--border) !important;
}

.gr-box, .gr-panel, .block {
    background: var(--surface) !important;
    border-radius: 18px !important;
    box-shadow: var(--shadow);
}

#chatbot-main, #history-chatbot {
    background: var(--surface) !important;
    border: 1px solid var(--border);
    border-radius: 20px !important;
    min-height: 55vh;
    padding: 20px;
}

#message-input, #history-message-input {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 18px !important;
    box-shadow: var(--shadow);
}

#message-input textarea, #history-message-input textarea {
    color: var(--text) !important;
    font-size: 14px !important;
}

button {
    border-radius: 11px !important;
    transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

button:hover {
    transform: translateY(-1px);
}

.primary-action {
    background: var(--accent) !important;
    color: white !important;
}

.secondary-action {
    background: var(--surface-muted) !important;
}

.danger-action {
    color: var(--danger) !important;
}

.history-sidebar-toggle {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    margin-bottom: 12px;
}

#history-search input {
    background: var(--surface-muted) !important;
    border: 1px solid transparent !important;
    border-radius: 12px !important;
}

#voice-launcher-container {
    max-width: 68px;
    min-width: 58px;
}

#voice-launcher {
    background: linear-gradient(135deg, #6869eb, #9a6ff4) !important;
    border: 0;
    border-radius: 16px !important;
    box-shadow: 0 8px 20px rgba(91, 92, 226, .25);
    color: white !important;
    font-size: 19px;
    min-height: 48px;
}

#voice-panel {
    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
    height: 0 !important;
    margin: 0 !important;
    min-height: 0 !important;
    overflow: visible !important;
    padding: 0 !important;
    width: 0 !important;
}

#voice-panel > div,
#voice-panel .wrap,
#voice-panel .block {
    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
    height: 0 !important;
    min-height: 0 !important;
    padding: 0 !important;
}

.voice-overlay {
    inset: 0;
    pointer-events: none;
    position: fixed;
    z-index: 1000;
}

.voice-overlay:has(.voice-overlay-card) {
    align-items: center;
    backdrop-filter: blur(18px);
    background: rgba(11, 16, 32, .54);
    display: flex;
    justify-content: center;
    pointer-events: auto;
}

.voice-overlay-card {
    align-items: center;
    background: rgba(30, 37, 61, .94);
    border: 1px solid rgba(255, 255, 255, .16);
    border-radius: 30px;
    box-shadow: 0 30px 90px rgba(0, 0, 0, .35);
    color: white;
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-width: min(420px, calc(100vw - 32px));
    padding: 46px 52px;
    text-align: center;
}

.voice-overlay-card small {
    color: #bac4df;
    line-height: 1.5;
}

.voice-orb {
    align-items: center;
    background: radial-gradient(circle, #7d8cff, #5b5ce2 70%);
    border-radius: 50%;
    box-shadow: 0 0 0 14px rgba(123, 140, 255, .12), 0 0 55px rgba(123, 140, 255, .58);
    display: flex;
    gap: 4px;
    height: 96px;
    justify-content: center;
    margin-bottom: 8px;
    width: 96px;
}

.voice-orb span {
    animation: voice-wave 850ms ease-in-out infinite alternate;
    background: white;
    border-radius: 5px;
    height: 18px;
    opacity: .9;
    width: 4px;
}

.voice-orb span:nth-child(2) { animation-delay: -220ms; }
.voice-orb span:nth-child(3) { animation-delay: -420ms; }
.voice-orb span:nth-child(4) { animation-delay: -180ms; }
.voice-orb span:nth-child(5) { animation-delay: -340ms; }

@keyframes voice-wave {
    from { transform: scaleY(.5); }
    to { transform: scaleY(1.75); }
}

.voice-controls {
    display: flex;
    gap: 10px;
    margin-top: 12px;
}

.voice-controls button {
    background: rgba(255, 255, 255, .12);
    border: 1px solid rgba(255, 255, 255, .18);
    color: white;
    padding: 9px 18px;
}

.voice-controls button:last-child {
    background: #7179f4;
}

.voice-spinner {
    border: 4px solid rgba(255, 255, 255, .22);
    border-radius: 50%;
    border-top-color: #9aa4ff;
    height: 54px;
    width: 54px;
    animation: voice-spin 800ms linear infinite;
}

@keyframes voice-spin {
    to { transform: rotate(360deg); }
}

@media (max-width: 760px) {
    .gradio-container { padding: 14px 10px 24px !important; }
    .app-header { margin-bottom: 12px; }
    .status-pill { display: none; }
    #chatbot-main, #history-chatbot { min-height: 58vh; padding: 10px; }
    .voice-overlay-card { padding: 34px 24px; }
}
"""
