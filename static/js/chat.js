document.addEventListener('DOMContentLoaded', () => {
    feather.replace();
    
    const socket = io();
    const channel = window.location.pathname.split('/').pop();
    
    const messagesDiv = document.getElementById('messages');
    const messageInput = document.getElementById('message');
    const sendButton = document.getElementById('send');
    const fileInput = document.getElementById('file');
    const leaveButton = document.getElementById('leaveChannel');
    const emojiButton = document.getElementById('emojiButton');
    const emojiModal = new bootstrap.Modal(document.getElementById('emojiModal'));
    const typingIndicator = document.getElementById('typing-indicator');
    const userListDiv = document.getElementById('user-list');

    let typingTimeout;
    const TYPING_TIMER_LENGTH = 3000; // 3 seconds
    let currentlyTyping = false;

    socket.emit('join', { channel });

    function updateUserList(users) {
        userListDiv.innerHTML = '';
        users.forEach(username => {
            const userItem = document.createElement('div');
            userItem.className = 'user-item';
            userItem.textContent = username;
            userListDiv.appendChild(userItem);
        });
    }

    function generateMessageId() {
        return Date.now().toString() + Math.random().toString(36).substr(2, 9);
    }

    function createReactionButtons(messageDiv, messageId) {
        const reactionsDiv = document.createElement('div');
        reactionsDiv.className = 'message-reactions';
        reactionsDiv.dataset.messageId = messageId;
        messageDiv.appendChild(reactionsDiv);

        const addReactionBtn = document.createElement('button');
        addReactionBtn.className = 'btn btn-outline-secondary btn-sm';
        addReactionBtn.innerHTML = '<i data-feather="smile"></i>';
        addReactionBtn.onclick = () => {
            const emojiButtons = document.querySelectorAll('.emoji-btn');
            emojiButtons.forEach(btn => {
                const originalClick = btn.onclick;
                btn.onclick = (e) => {
                    e.preventDefault();
                    const emoji = btn.dataset.emoji;
                    socket.emit('reaction', {
                        message_id: messageId,
                        emoji: emoji,
                        channel: channel
                    });
                    emojiModal.hide();
                    btn.onclick = originalClick;
                };
            });
            emojiModal.show();
        };
        reactionsDiv.appendChild(addReactionBtn);
        feather.replace();
    }

    function updateReactions(messageId, reactions) {
        const reactionsDiv = document.querySelector(`.message-reactions[data-message-id="${messageId}"]`);
        if (!reactionsDiv) return;

        // Remove existing reaction buttons except the add reaction button
        Array.from(reactionsDiv.children).forEach(child => {
            if (!child.classList.contains('btn-outline-secondary')) {
                child.remove();
            }
        });

        // Add reaction buttons
        Object.entries(reactions).forEach(([emoji, count]) => {
            const reactionBtn = document.createElement('button');
            reactionBtn.className = 'btn btn-outline-primary btn-sm reaction-btn';
            reactionBtn.innerHTML = `${emoji} <span class="reaction-count">${count}</span>`;
            reactionBtn.onclick = () => {
                socket.emit('reaction', {
                    message_id: messageId,
                    emoji: emoji,
                    channel: channel
                });
            };
            reactionsDiv.insertBefore(reactionBtn, reactionsDiv.firstChild);
        });
    }

    function updateTypingIndicator(typingUsers) {
        if (typingUsers.length === 0) {
            typingIndicator.textContent = '';
        } else if (typingUsers.length === 1) {
            typingIndicator.textContent = `${typingUsers[0]} is typing...`;
        } else if (typingUsers.length === 2) {
            typingIndicator.textContent = `${typingUsers[0]} and ${typingUsers[1]} are typing...`;
        } else {
            typingIndicator.textContent = 'Several people are typing...';
        }
    }

    const typingUsers = new Set();

    socket.on('typing_status', (data) => {
        if (data.typing) {
            typingUsers.add(data.username);
        } else {
            typingUsers.delete(data.username);
        }
        updateTypingIndicator(Array.from(typingUsers));
    });

    socket.on('user_list_update', (data) => {
        updateUserList(data.users);
    });

    function emitTyping(isTyping) {
        if (currentlyTyping !== isTyping) {
            currentlyTyping = isTyping;
            socket.emit('typing', {
                channel: channel,
                typing: isTyping
            });
        }
    }

    messageInput.addEventListener('input', () => {
        clearTimeout(typingTimeout);
        emitTyping(true);
        
        typingTimeout = setTimeout(() => {
            emitTyping(false);
        }, TYPING_TIMER_LENGTH);
    });

    socket.on('message', (data) => {
        const messageId = data.message_id || generateMessageId();
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message bg-dark';
        messageDiv.dataset.messageId = messageId;
        
        const usernameDiv = document.createElement('div');
        usernameDiv.className = 'username';
        usernameDiv.textContent = data.username;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'content';
        
        if (data.type === 'image') {
            const img = document.createElement('img');
            img.src = data.msg;
            contentDiv.appendChild(img);
        } else {
            contentDiv.textContent = data.msg;
        }
        
        messageDiv.appendChild(usernameDiv);
        messageDiv.appendChild(contentDiv);
        createReactionButtons(messageDiv, messageId);
        messagesDiv.appendChild(messageDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    });

    socket.on('status', (data) => {
        const statusDiv = document.createElement('div');
        statusDiv.className = 'status-message';
        statusDiv.textContent = data.msg;
        messagesDiv.appendChild(statusDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    });

    socket.on('reaction_update', (data) => {
        updateReactions(data.message_id, data.reactions);
    });

    emojiButton.addEventListener('click', () => {
        const emojiButtons = document.querySelectorAll('.emoji-btn');
        emojiButtons.forEach(btn => {
            btn.onclick = (e) => {
                e.preventDefault();
                const emoji = btn.dataset.emoji;
                messageInput.value += emoji;
                emojiModal.hide();
            };
        });
        emojiModal.show();
    });

    sendButton.addEventListener('click', () => {
        const message = messageInput.value.trim();
        if (message) {
            const messageId = generateMessageId();
            socket.emit('message', {
                msg: message,
                channel,
                type: 'text',
                message_id: messageId
            });
            messageInput.value = '';
            clearTimeout(typingTimeout);
            emitTyping(false);
        }
    });

    messageInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendButton.click();
        }
    });

    fileInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (file) {
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    const data = await response.json();
                    const messageId = generateMessageId();
                    socket.emit('message', {
                        msg: data.url,
                        channel,
                        type: 'image',
                        message_id: messageId
                    });
                }
            } catch (error) {
                console.error('Error uploading file:', error);
            }
        }
    });

    leaveButton.addEventListener('click', () => {
        socket.emit('leave', { channel });
        window.location.href = '/';
    });

    window.addEventListener('beforeunload', () => {
        socket.emit('leave', { channel });
    });
});
