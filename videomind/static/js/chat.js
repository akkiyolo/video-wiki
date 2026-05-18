document.addEventListener('DOMContentLoaded', () => {
  const chatPage = document.querySelector('.chat-page-container');
  if (!chatPage) return; // Exit if not on chat page

  const sessionId = chatPage.getAttribute('data-session-id');
  const chatMessages = document.getElementById('chatMessages');
  const chatForm = document.getElementById('chatForm');
  const chatTextarea = document.getElementById('chatTextarea');
  const btnSend = document.getElementById('btnSend');
  const charCounter = document.getElementById('charCounter');
  const typingIndicator = document.getElementById('typingIndicator');
  
  // Copilot Panel Interactions
  const wikiCopilotSidebar = document.getElementById('wikiCopilotSidebar');
  const btnToggleCopilot = document.getElementById('btnToggleCopilot');
  const btnFloatingCopilot = document.getElementById('btnFloatingCopilot');

  // Export Action
  const btnExportMarkdown = document.getElementById('btnExportMarkdown');

  // Modal Elements
  const btnViewTranscript = document.getElementById('btnViewTranscript');
  const btnCloseModal = document.getElementById('btnCloseModal');
  const transcriptModal = document.getElementById('transcriptModal');
  const btnCopyTranscript = document.getElementById('btnCopyTranscript');
  const transcriptDisplay = document.querySelector('.transcript-display');

  // Delete Action
  const btnDeleteSession = document.getElementById('btnDeleteSession');

  // Message History State
  let history = [];

  // Save conversation history to localStorage
  function saveHistory() {
    localStorage.setItem(`videomind_history_${sessionId}`, JSON.stringify(history));
  }

  // Load conversation history from localStorage
  function loadHistory() {
    const stored = localStorage.getItem(`videomind_history_${sessionId}`);
    if (stored) {
      try {
        history = JSON.parse(stored);
        history.forEach(msg => {
          appendMessageDOM(msg.role, msg.content);
        });
      } catch (e) {
        console.error('Failed to load chat history:', e);
        history = [];
      }
    }
  }

  // Load past history on page start
  loadHistory();

  // Highlight active session card in sidebar
  const currentCard = document.getElementById(`session-card-${sessionId}`);
  if (currentCard) {
    currentCard.classList.add('active');
  }

  // Auto-scroll chat messages container
  function scrollToBottom() {
    if (chatMessages) {
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  }
  // Initial scroll
  scrollToBottom();

  // ==========================================
  // COPILOT PANEL EXPAND & COLLAPSE HANDLERS
  // ==========================================
  
  if (btnToggleCopilot && wikiCopilotSidebar && btnFloatingCopilot) {
    btnToggleCopilot.addEventListener('click', () => {
      wikiCopilotSidebar.classList.add('collapsed');
      btnFloatingCopilot.classList.add('visible');
    });

    btnFloatingCopilot.addEventListener('click', () => {
      wikiCopilotSidebar.classList.remove('collapsed');
      btnFloatingCopilot.classList.remove('visible');
      setTimeout(scrollToBottom, 310); // Scroll after transit finishes
    });
  }

  // ==========================================
  // CLIENT-SIDE MARKDOWN COMPILER
  // ==========================================
  
  function renderMarkdown(md) {
    if (!md || md.trim() === '') {
      return `
        <div class="wiki-empty-state">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"></path>
            <path d="M6 2v18"></path>
          </svg>
          <h4>No Wiki article generated yet</h4>
          <p>Please wait for the background AI synthesis job to complete editing.</p>
        </div>
      `;
    }

    // Clean syntax and convert headers
    let html = md
      .replace(/^#\s+(.*?)$/gm, '<h1>$1</h1>')
      .replace(/^##\s+(.*?)$/gm, '<h2 id="$1">$1</h2>')
      .replace(/^###\s+(.*?)$/gm, '<h3>$1</h3>');

    // Convert bold and italics
    html = html
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>');

    // Convert lists
    html = html.replace(/^-\s+(.*?)$/gm, '<li>$1</li>');

    // Convert paragraphs
    html = html.replace(/\n\n/g, '<p></p>');

    // Break remaining newlines
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  // Compile raw article markdown to editorial HTML on startup
  const rawArticleMarkdown = document.getElementById('rawArticleMarkdown');
  const wikiArticleHtml = document.getElementById('wikiArticleHtml');
  const wikiLoading = document.getElementById('wikiLoading');

  if (rawArticleMarkdown && wikiArticleHtml) {
    const rawMD = rawArticleMarkdown.value;
    wikiArticleHtml.innerHTML = renderMarkdown(rawMD);
    if (wikiLoading) {
      wikiLoading.style.display = 'none';
    }
  }

  // Export Markdown download action
  if (btnExportMarkdown && rawArticleMarkdown) {
    btnExportMarkdown.addEventListener('click', () => {
      const markdownContent = rawArticleMarkdown.value;
      if (!markdownContent) {
        alert('No article content available to export.');
        return;
      }
      const blob = new Blob([markdownContent], { type: 'text/markdown;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `VideoWiki_${sessionId}.md`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    });
  }

  // Dynamic Textarea Auto-Resizing inside Copilot
  if (chatTextarea) {
    chatTextarea.addEventListener('input', () => {
      chatTextarea.style.height = 'auto';
      chatTextarea.style.height = `${Math.min(chatTextarea.scrollHeight, 140)}px`;
      charCounter.innerText = `${chatTextarea.value.length} / 2000`;
    });
  }

  // ==========================================
  // SEND MESSAGE LOGIC (ASK ARTICLE CHAT)
  // ==========================================

  function appendMessageDOM(role, content) {
    const wrapper = document.createElement('div');
    wrapper.className = `chat-message-wrapper ${role}`;

    const isUser = role === 'user';
    
    // Avatar SVG
    const avatarSVG = isUser ? `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
        <circle cx="12" cy="7" r="4"></circle>
      </svg>
    ` : `
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"></path>
        <path d="M6 2v18"></path>
      </svg>
    `;

    const avatarHTML = `
      <div class="message-avatar ${role}-avatar" title="${isUser ? 'You' : 'VideoWiki AI Copilot'}">
        ${avatarSVG}
      </div>
    `;

    const bubbleHTML = `
      <div class="chat-bubble ${role}">
        <div class="chat-bubble-content">${escapeHTML(content).replace(/\n/g, '<br>')}</div>
      </div>
    `;

    if (isUser) {
      wrapper.innerHTML = bubbleHTML + avatarHTML;
    } else {
      wrapper.innerHTML = avatarHTML + bubbleHTML;
    }

    if (chatMessages && typingIndicator) {
      chatMessages.insertBefore(wrapper, typingIndicator);
    }
    scrollToBottom();
    return wrapper;
  }

  function escapeHTML(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  async function sendMessage() {
    const text = chatTextarea.value.trim();
    if (!text) return;

    // Reset textarea state
    chatTextarea.value = '';
    chatTextarea.style.height = 'auto';
    charCounter.innerText = '0 / 2000';
    chatTextarea.focus();

    // Render User message
    appendMessageDOM('user', text);
    
    // Save historyToSend (excluding current query to prevent backend duplication)
    const historyToSend = [...history];

    // Store message in state history
    history.push({ role: 'user', content: text });
    saveHistory();

    // Show typing indicator
    typingIndicator.style.display = 'flex';
    scrollToBottom();

    let assistantMessageWrapper = null;
    let assistantText = '';

    try {
      const response = await fetch(`/api/chat/${sessionId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          message: text,
          history: historyToSend
        })
      });

      if (!response.ok) {
        throw new Error('Failed to communicate with LLM server.');
      }

      // Read SSE stream
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        
        // Save the incomplete line back to the buffer
        buffer = lines.pop();

        for (const line of lines) {
          const cleanLine = line.trim();
          if (!cleanLine.startsWith('data: ')) continue;
          
          const rawJSON = cleanLine.substring(6);
          try {
            const parsed = JSON.parse(rawJSON);

            if (parsed.error) {
              throw new Error(parsed.error);
            }

            if (parsed.done) {
              break;
            }

            if (parsed.chunk) {
              // Hide typing indicator on first arriving chunk
              if (typingIndicator.style.display !== 'none') {
                typingIndicator.style.display = 'none';
              }

              // Initialize bubble on first token
              if (!assistantMessageWrapper) {
                assistantMessageWrapper = appendMessageDOM('assistant', '');
              }

              assistantText += parsed.chunk;
              const contentEl = assistantMessageWrapper.querySelector('.chat-bubble-content');
              
              // Basic markdown formatting replacement for bold/newlines
              let formattedText = escapeHTML(assistantText)
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.*?)\*/g, '<em>$1</em>')
                .replace(/\n/g, '<br>');
              
              contentEl.innerHTML = formattedText;
              scrollToBottom();
            }
          } catch (jsonErr) {
            console.error('Failed to parse SSE JSON:', jsonErr);
          }
        }
      }

      // Add to final history memory
      if (assistantText) {
        history.push({ role: 'assistant', content: assistantText });
        saveHistory();
      }

    } catch (error) {
      typingIndicator.style.display = 'none';
      appendMessageDOM('assistant', `⚠️ Error: ${error.message}`);
    } finally {
      typingIndicator.style.display = 'none';
    }
  }

  // ==========================================
  // EVENT HANDLERS
  // ==========================================

  if (chatForm) {
    // Submit trigger
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      sendMessage();
    });

    // Enter triggers send, Shift+Enter new line
    chatTextarea.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  // Transcript Modal handlers
  if (btnViewTranscript) {
    btnViewTranscript.addEventListener('click', () => {
      transcriptModal.style.display = 'flex';
    });

    btnCloseModal.addEventListener('click', () => {
      transcriptModal.style.display = 'none';
    });

    // Click outside to close modal
    transcriptModal.addEventListener('click', (e) => {
      if (e.target === transcriptModal) {
        transcriptModal.style.display = 'none';
      }
    });

    // Copy transcript code
    btnCopyTranscript.addEventListener('click', () => {
      const text = transcriptDisplay.innerText;
      navigator.clipboard.writeText(text)
        .then(() => {
          btnCopyTranscript.innerText = 'Copied!';
          setTimeout(() => {
            btnCopyTranscript.innerText = 'Copy to clipboard';
          }, 1500);
        })
        .catch(err => {
          console.error('Could not copy transcript:', err);
        });
    });
  }

  // Delete Session Ingest Handler
  if (btnDeleteSession) {
    btnDeleteSession.addEventListener('click', () => {
      if (confirm('Are you absolutely sure you want to delete this video article and all its indexed memories? This action cannot be undone.')) {
        btnDeleteSession.disabled = true;
        btnDeleteSession.innerText = 'Deleting...';

        fetch(`/api/session/${sessionId}`, {
          method: 'DELETE'
        })
        .then(async (response) => {
          if (!response.ok) {
            throw new Error('Failed to delete session');
          }
          // Remove history from localstorage
          localStorage.removeItem(`videomind_history_${sessionId}`);
          // Redirect to homepage
          window.location.href = '/';
        })
        .catch((error) => {
          alert(error.message);
          btnDeleteSession.disabled = false;
          btnDeleteSession.innerText = 'Delete';
        });
      }
    });
  }
});
