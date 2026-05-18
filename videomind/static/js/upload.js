document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const youtubeForm = document.getElementById('youtubeForm');
  const youtubeUrlInput = document.getElementById('youtubeUrl');
  const btnYoutubeSubmit = document.getElementById('btnYoutubeSubmit');
  
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  
  const uploadOptionsCard = document.getElementById('uploadOptionsCard');
  const progressCard = document.getElementById('progressCard');
  const progressErrorContainer = document.getElementById('progressErrorContainer');
  const progressErrorMessage = document.getElementById('progressErrorMessage');
  const btnRestart = document.getElementById('btnRestart');
  
  // Progress Steps
  const stepTranscribe = document.getElementById('step-transcribe');
  const descTranscribe = document.getElementById('desc-transcribe');
  
  const stepHydra = document.getElementById('step-hydra');
  const descHydra = document.getElementById('desc-hydra');

  const stepArticle = document.getElementById('step-article');
  const descArticle = document.getElementById('desc-article');
  
  const stepReady = document.getElementById('step-ready');
  const descReady = document.getElementById('desc-ready');

  // ==========================================
  // DRAG & DROP EVENT LISTENERS
  // ==========================================
  
  if (dropZone) {
    // Click dropzone to trigger input browse
    dropZone.addEventListener('click', () => fileInput.click());

    // Visual drag states
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('drag-active');
    });

    dropZone.addEventListener('dragleave', () => {
      dropZone.classList.remove('drag-active');
    });

    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-active');
      
      if (e.dataTransfer.files.length > 0) {
        handleFileSelect(e.dataTransfer.files[0]);
      }
    });

    // Browse select triggers upload
    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        handleFileSelect(e.target.files[0]);
      }
    });
  }

  // ==========================================
  // INGEST SUBMIT HANDLERS
  // ==========================================

  // YouTube Ingest
  if (youtubeForm) {
    youtubeForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const url = youtubeUrlInput.value.trim();
      if (!url) return;

      // Validate URL quickly
      if (!url.includes('youtube.com') && !url.includes('youtu.be')) {
        alert('Please enter a valid YouTube URL.');
        return;
      }

      btnYoutubeSubmit.disabled = true;
      btnYoutubeSubmit.innerText = 'Sending...';

      fetch('/api/ingest/youtube', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ url: url })
      })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || 'Failed to submit YouTube URL');
        }
        // Switch view and track progress
        showProgressUI();
        watchProgress(data.session_id);
      })
      .catch((error) => {
        btnYoutubeSubmit.disabled = false;
        btnYoutubeSubmit.innerText = 'Transcribe';
        alert(error.message);
      });
    });
  }

  // Local File Ingest
  function handleFileSelect(file) {
    // 500MB Validation (524288000 bytes)
    const maxSize = 500 * 1024 * 1024;
    if (file.size > maxSize) {
      alert('File size exceeds the 500MB limit.');
      return;
    }

    // Basic type validation
    if (!file.type.startsWith('video/') && !file.type.startsWith('audio/')) {
      alert('Unsupported file format. Please upload an audio or video file.');
      return;
    }

    // Start multipart upload
    const formData = new FormData();
    formData.append('file', file);

    showProgressUI();
    // Update step transcribe description to show uploading progress
    descTranscribe.innerText = 'Uploading file to server...';
    stepTranscribe.className = 'progress-step active';

    fetch('/api/ingest/file', {
      method: 'POST',
      body: formData
    })
    .then(async (response) => {
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Failed to upload file');
      }
      watchProgress(data.session_id);
    })
    .catch((error) => {
      showError(error.message);
    });
  }

  // ==========================================
  // PROGRESS & SSE STATE MANAGEMENT
  // ==========================================

  function showProgressUI() {
    uploadOptionsCard.style.display = 'none';
    progressCard.style.display = 'flex';
    progressErrorContainer.style.display = 'none';
    
    // Set initial states
    stepTranscribe.className = 'progress-step pending';
    stepHydra.className = 'progress-step pending';
    stepArticle.className = 'progress-step pending';
    stepReady.className = 'progress-step pending';
  }

  function watchProgress(sessionId) {
    // Open Server-Sent Events stream
    const eventSource = new EventSource(`/api/ingest/status/${sessionId}`);

    eventSource.onmessage = (e) => {
      const data = JSON.parse(e.data);
      console.log('Ingest event:', data);

      if (data.step === 'transcribe') {
        if (data.status === 'active') {
          stepTranscribe.className = 'progress-step active';
          descTranscribe.innerText = data.msg || 'Transcribing audio...';
        } else if (data.status === 'done') {
          stepTranscribe.className = 'progress-step done';
          descTranscribe.innerText = data.msg || 'Transcription completed.';
          // Instantly prime next step
          stepHydra.className = 'progress-step active';
        }
      } 
      
      else if (data.step === 'hydra') {
        stepTranscribe.className = 'progress-step done'; // ensure step 1 is marked done
        if (data.status === 'active') {
          stepHydra.className = 'progress-step active';
          descHydra.innerText = data.msg || 'Storing memories...';
        } else if (data.status === 'done') {
          stepHydra.className = 'progress-step done';
          descHydra.innerText = data.msg || 'Memories indexed.';
          stepArticle.className = 'progress-step active';
        }
      } 

      else if (data.step === 'article') {
        stepTranscribe.className = 'progress-step done';
        stepHydra.className = 'progress-step done';
        if (data.status === 'active') {
          stepArticle.className = 'progress-step active';
          descArticle.innerText = data.msg || 'Synthesizing Wikipedia article...';
        } else if (data.status === 'done') {
          stepArticle.className = 'progress-step done';
          descArticle.innerText = data.msg || 'Wikipedia article generated.';
          stepReady.className = 'progress-step active';
        }
      }
      
      else if (data.step === 'done') {
        stepTranscribe.className = 'progress-step done';
        stepHydra.className = 'progress-step done';
        stepArticle.className = 'progress-step done';
        stepReady.className = 'progress-step done';
        descReady.innerText = 'Wikipedia Video entry compiled and ready!';
        
        eventSource.close();
        
        // Redirect to chat screen after 800ms
        setTimeout(() => {
          window.location.href = `/session/${data.session_id}`;
        }, 800);
      } 
      
      else if (data.step === 'error') {
        eventSource.close();
        // Mark the active step as error
        if (stepHydra.classList.contains('active')) {
          stepHydra.className = 'progress-step error';
        } else if (stepArticle.classList.contains('active')) {
          stepArticle.className = 'progress-step error';
        } else if (stepReady.classList.contains('active')) {
          stepReady.className = 'progress-step error';
        } else {
          stepTranscribe.className = 'progress-step error';
        }
        showError(data.msg || 'An unknown error occurred during ingestion.');
      }
    };

    eventSource.onerror = (err) => {
      console.error('SSE Error:', err);
      eventSource.close();
      showError('Lost connection to processing server. Session may still be processing. Check the sidebar for updates.');
    };
  }

  function showError(msg) {
    progressErrorContainer.style.display = 'flex';
    progressErrorMessage.innerText = msg;
  }

  // Go back button reset
  if (btnRestart) {
    btnRestart.addEventListener('click', () => {
      window.location.reload();
    });
  }

  // ==========================================
  // GLOBAL WIKI SEARCH
  // ==========================================
  const globalSearchForm = document.getElementById('globalSearchForm');
  const globalSearchInput = document.getElementById('globalSearchInput');
  const searchResults = document.getElementById('searchResults');
  const resultsList = document.getElementById('resultsList');
  const btnClearResults = document.getElementById('btnClearResults');
  const btnGlobalSearch = document.getElementById('btnGlobalSearch');

  if (globalSearchForm) {
    globalSearchForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const query = globalSearchInput.value.trim();
      if (!query) return;

      btnGlobalSearch.disabled = true;
      btnGlobalSearch.innerText = 'Searching...';

      try {
        const response = await fetch('/api/wiki/search', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ query: query })
        });

        if (!response.ok) {
          throw new Error('Failed to retrieve search results');
        }

        const data = await response.json();
        resultsList.innerHTML = '';

        if (data.results && data.results.length > 0) {
          data.results.forEach(res => {
            const card = document.createElement('div');
            card.className = 'search-result-card';
            
            let thumbnailHTML = '';
            if (res.thumbnail) {
              thumbnailHTML = `<img src="${res.thumbnail}" alt="Thumbnail" class="result-card-thumbnail" />`;
            } else {
              thumbnailHTML = `
                <div class="result-card-file-icon">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"></path>
                    <path d="M6 2v18"></path>
                  </svg>
                </div>
              `;
            }

            card.innerHTML = `
              ${thumbnailHTML}
              <div class="result-card-info">
                <h4 class="result-card-title">
                  <a href="/session/${res.session_id}">${escapeHTML(res.session_title)}</a>
                </h4>
                <span class="result-card-badge">${escapeHTML(res.source_type)}</span>
                <p class="result-card-snippet">${escapeHTML(res.snippet)}</p>
                <a href="/session/${res.session_id}" class="result-card-read-link">Read full Wiki article →</a>
              </div>
            `;
            resultsList.appendChild(card);
          });
        } else {
          resultsList.innerHTML = `
            <div class="search-empty-results">
              <p>No matching information found across any video articles.</p>
              <p class="empty-sub">Try asking about different topics, or index more videos first!</p>
            </div>
          `;
        }

        searchResults.style.display = 'block';
      } catch (err) {
        alert(err.message);
      } finally {
        btnGlobalSearch.disabled = false;
        btnGlobalSearch.innerText = 'Search';
      }
    });

    btnClearResults.addEventListener('click', () => {
      globalSearchInput.value = '';
      resultsList.innerHTML = '';
      searchResults.style.display = 'none';
    });

    // Trending Tags Auto-search Handler
    const trendingTags = document.querySelectorAll('.trending-tag');
    trendingTags.forEach(tag => {
      tag.addEventListener('click', () => {
        const query = tag.getAttribute('data-query');
        if (query && globalSearchInput) {
          globalSearchInput.value = query;
          globalSearchForm.dispatchEvent(new Event('submit'));
        }
      });
    });
  }

  function escapeHTML(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
});
