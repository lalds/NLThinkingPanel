const dialogueText = document.getElementById('dialogue-text');
const speakerName = document.getElementById('speaker-name');
const characterImg = document.getElementById('character');

let socket;
let reconnectInterval = 3000;

function connect() {
    // Используем относительный путь для WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Connected to NLThinkingPanel Server');
        updateText('Система инициализирована. Ожидаю сигнал...');
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('Received:', data);

        if (data.type === 'state') {
            handleStateChange(data);
        }
    };

    socket.onclose = () => {
        console.log('Connection lost. Reconnecting...');
        setTimeout(connect, reconnectInterval);
    };
}

function handleStateChange(data) {
    const { state, text, speaker } = data;

    if (speaker) speakerName.innerText = speaker;

    // Спрайты: idle, talking, thinking
    updateCharacter(state);

    if (text) {
        updateText(text);
    }
}

function updateCharacter(state) {
    // state: 'idle', 'talking', 'thinking'
    characterImg.src = `assets/${state}.png`;

    if (state === 'talking') {
        characterImg.style.transform = 'scale(1.05)';
    } else if (state === 'thinking') {
        characterImg.style.filter = 'drop-shadow(0 0 20px rgba(0, 255, 0, 0.3)) hue-rotate(90deg)';
    } else {
        characterImg.style.transform = 'scale(1)';
        characterImg.style.filter = 'drop-shadow(0 0 15px rgba(255, 0, 0, 0.2))';
    }
}

function updateText(text) {
    dialogueText.innerHTML = '';
    let i = 0;

    // Эффект печатной машинки
    function type() {
        if (i < text.length) {
            dialogueText.innerHTML += text.charAt(i);
            i++;
            setTimeout(type, 30);
        }
    }
    type();
}

// Запуск
connect();
