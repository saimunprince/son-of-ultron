<!-- Copied from the assistant's memory on 2026-09-26 so it survives an OS change. Facts only; keys and addresses removed. -->


SYRAX lives at /home/prince/son-of-ultron. Frontend is the ULTRON orb UI (Next.js + Three.js), backend is OpenManus. Built 2026-09-24.

- OpenManus core in backend/app/ is kept untouched. All SYRAX code is in backend/syrax/ (agent, tools, server, prompt, test_bridge).
- Persona was dictated by the user: SYRAX is ULTRON's son, savage/sigma Barisal-style Banglish, NEVER says "sir". One hard rule kept: confirm destructive actions via ask_human.
- Brain: syrax/brains.py BrainRouter replaces OpenManus LLM, with multi-provider failover. User wants max free options (no budget). Default needs no key: Pollinations, then local Ollama (qwen2.5:7b, gemma4 installed, CPU only). Keys go in config/brains.json via the UI BRAIN panel. config.toml [llm] is a dummy. The Meta AI/WhatsApp bridge was tried and fully removed at the user's request, so don't suggest it again.
- UI identity: Son of Ultron. Default 'ultron' theme is graphite/chrome with a silver orb, red core and red optics (all-red crimson was rejected as too red). 'classic' theme is the original amber. Chamfered panels, Chakra Petch + JetBrains Mono fonts, boot sequence, CSS fallback orb when WebGL is missing.
- Voice (2026-09-24): "Ultron protocol" look and voice: calm-menace persona, ring-mod metallic voice chain, awakening line at boot, screen glitch while speaking. User asked for a "real Ultron" to rule the world: declined the real-harm part, built the character experience only. SYRAX is fully voice-driven and speaks ENGLISH (user's choice). Default is conversation mode, with no wake word while MIC is LIVE. The wake word is optional, because the user's accent made Whisper hear 'SYRAX' as 'Tyr' and nothing ever ran. SYRAX speaks 'Listening.' and short acks so it never feels dead. Ears prefer Chrome Web Speech (en-IN default); a VAD watchdog falls back to Whisper when the browser engine is deaf. STT goes to Groq Whisper if a key is saved, else local faster-whisper small.en. Local Whisper is useless for Bengali, which is why English was chosen. TTS is edge-tts en-US-ChristopherNeural with a metallic WebAudio chain.
- QA 2026-09-24: Browser Use 3.0 only attaches to an existing Chrome, so syrax/browser.py runs a managed Chrome (own profile, CDP 9333). syrax.sh runs each part in its own process group (setsid), serves the production UI on 127.0.0.1 by default (--dev for dev mode), and checks ports before starting. The machine has 14 GB RAM with no GPU: Ollama 7B plus two Whisper instances can thrash it, so never run a second SYRAX instance next to the user's live one without checking RAM.
- Upstream quirks handled: blocking python_execute, missing websockets dependency, config crashing without a [daytona] section, outdated multimodal model list.

**Why:** Keeping core untouched lets upstream OpenManus updates merge cleanly.
**How to apply:** Put new behaviour in syrax/ via subclassing. Don't edit app/ unless unavoidable. Run syrax/test_bridge.py after changes.


Added 2026-09-24:
- GitHub repo <e-mail removed>:saimunprince/son-of-ultron.git, branch main. Commit as Prince <<e-mail removed>> with the co-author line.
- Long-term memory lives in syrax/memory.py (memory.json + history.jsonl), injected into every task.
- Desktop tool lives in syrax/desktop.py, targeting GNOME Wayland (wpctl, playerctl, gnome-screenshot, wl-copy). Waydroid apps are penalised in app matching.
- A systemd user service is installed and enabled (~/.config/systemd/user/syrax.service -> syrax.sh --service). It auto-opens the UI and steps aside when ports are busy.
