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

    // On small screens the copilot is a slide-over sheet, so start with it closed
    if (window.matchMedia('(max-width: 860px)').matches) {
      wikiCopilotSidebar.classList.add('collapsed');
      btnFloatingCopilot.classList.add('visible');
    }
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
          <p>The AI synthesis job is still running. Refresh this page in a moment.</p>
        </div>
      `;
    }

    return markdownToHTML(md, true);
  }

  // Inline markdown on already-escaped text: code, bold, italics, links
  function renderInline(text) {
    return text
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  }

  // Small block-level markdown renderer (headings, lists, quotes, rules, paragraphs).
  // Input is escaped first: the content is LLM output and must never be injected as raw HTML.
  function markdownToHTML(md, withAnchors) {
    const lines = escapeHTML(md.replace(/\r\n?/g, '\n')).split('\n');
    const out = [];
    let para = [];
    let list = null;

    const flushPara = () => {
      if (para.length) {
        out.push(`<p>${renderInline(para.join(' '))}</p>`);
        para = [];
      }
    };
    const flushList = () => {
      if (list) {
        const items = list.items.map(item => `<li>${renderInline(item)}</li>`).join('');
        out.push(`<${list.type}>${items}</${list.type}>`);
        list = null;
      }
    };
    const flush = () => { flushPara(); flushList(); };

    for (const raw of lines) {
      const line = raw.trimEnd();
      let m;

      if (!line.trim()) {
        flush();
      } else if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
        flush();
        const level = m[1].length;
        const text = m[2].replace(/\s+#+$/, '');
        // h2 ids are slugified to match TOC anchors
        const id = withAnchors && level === 2 ? ` id="${slugify(text)}"` : '';
        out.push(`<h${level}${id}>${renderInline(text)}</h${level}>`);
      } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
        flush();
        out.push('<hr>');
      } else if ((m = line.match(/^&gt;\s?(.*)$/))) {
        flush();
        out.push(`<blockquote>${renderInline(m[1])}</blockquote>`);
      } else if ((m = line.match(/^\s*[-*+]\s+(.*)$/)) || (m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
        flushPara();
        const type = /^\s*\d/.test(line) ? 'ol' : 'ul';
        if (list && list.type !== type) flushList();
        if (!list) list = { type, items: [] };
        list.items.push(m[1]);
      } else if (list && /^\s+/.test(raw)) {
        // Indented continuation of the previous list item
        list.items[list.items.length - 1] += ' ' + line.trim();
      } else {
        flushList();
        para.push(line.trim());
      }
    }
    flush();
    return out.join('\n');
  }

  // "Key Thematic Concepts" -> "Key-Thematic-Concepts" (input is already HTML-escaped)
  function slugify(text) {
    return text.replace(/<[^>]*>/g, '').replace(/\*/g, '').trim().replace(/\s+/g, '-');
  }

  // Rebuild the TOC from the headings actually present (the LLM may number or rename them)
  function rebuildTOC(container) {
    const tocList = document.querySelector('.toc-list');
    const headings = container.querySelectorAll('h2[id]');
    if (!tocList || headings.length === 0) return;

    tocList.innerHTML = '';
    headings.forEach((h, i) => {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = `#${encodeURIComponent(h.id)}`;
      a.textContent = `${i + 1}. ${h.textContent}`;
      li.appendChild(a);
      tocList.appendChild(li);
    });
  }

  // Compile raw article markdown to editorial HTML on startup
  const rawArticleMarkdown = document.getElementById('rawArticleMarkdown');
  const wikiArticleHtml = document.getElementById('wikiArticleHtml');
  const wikiLoading = document.getElementById('wikiLoading');

  if (rawArticleMarkdown && wikiArticleHtml) {
    const rawMD = rawArticleMarkdown.value;
    wikiArticleHtml.innerHTML = renderMarkdown(rawMD);
    rebuildTOC(wikiArticleHtml);

    // Let the article title span the full column above the floated infobox
    const titleEl = wikiArticleHtml.firstElementChild;
    const infobox = document.querySelector('.wiki-infobox-floated');
    if (titleEl && titleEl.tagName === 'H1' && infobox) {
      infobox.parentNode.insertBefore(titleEl, infobox);
    }
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
    return String(str ?? '')
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
        let errMsg = 'Failed to communicate with LLM server.';
        try {
          const errData = await response.json();
          if (errData && errData.error) errMsg = errData.error;
        } catch (_) { /* non-JSON error body */ }
        throw new Error(errMsg);
      }

      // Read SSE stream
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let streamDone = false;

      while (!streamDone) {
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
          let parsed;
          try {
            parsed = JSON.parse(rawJSON);
          } catch (jsonErr) {
            console.error('Failed to parse SSE JSON:', jsonErr);
            continue;
          }

          // Thrown outside the JSON try so the outer handler shows it to the user
          if (parsed.error) {
            throw new Error(parsed.error);
          }

          if (parsed.done) {
            streamDone = true;
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
            
            contentEl.innerHTML = markdownToHTML(assistantText, false);
            scrollToBottom();
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
