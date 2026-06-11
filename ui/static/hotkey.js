let selectedPath = null;
let fields = [];

async function fetchFields() {
    try {
        const response = await fetch('/api/fields');
        const data = await response.json();
        fields = data.fields;
        renderFields();
    } catch (error) {
        document.getElementById('fieldsList').innerHTML = `
            <div class="empty-state">
                Failed to load fields.<br>
                <small style="opacity: 0.7;">Make sure Palimind is running properly.</small>
            </div>`;
        console.error('Error loading fields:', error);
    }
}

function selectField(path) {
    selectedPath = path;
    renderFields();
    document.getElementById('saveBtn').disabled = false;
}

function renderFields() {
    const container = document.getElementById('fieldsList');
    
    if (fields.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                No Fields available.<br>
                <small style="opacity: 0.7;">Create one in the Palimind UI first.</small>
            </div>`;
        return;
    }

    container.innerHTML = '';
    
    fields.forEach(field => {
        const isSelected = selectedPath === field.path;
        
        const card = document.createElement('div');
        card.className = `field-card ${isSelected ? 'selected' : ''}`;
        card.onclick = () => selectField(field.path);

        card.innerHTML = `
            <div class="radio-btn"></div>
            <div>
                <div class="field-name">${field.name}</div>
                <div class="field-path" title="${field.path}">${field.path}</div>
            </div>
        `;
        
        container.appendChild(card);
    });
    
    // Auto-select first if none selected
    if (!selectedPath && fields.length > 0) {
        selectField(fields[0].path);
    }
}

async function saveSelection() {
    if (!selectedPath) return;
    
    const btn = document.getElementById('saveBtn');
    const originalText = btn.innerText;
    btn.innerText = 'Saving...';
    btn.disabled = true;

    try {
        await fetch('/api/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: selectedPath })
        });
        // Close the window after sending selection
        window.close();
        // Fallback if browser blocks window.close()
        document.body.innerHTML = `
            <div class="container" style="text-align: center;">
                <h1 style="color: #4ade80;">Saved Successfully!</h1>
                <p class="subtitle">The captured text has been added to the field context. You can now safely close this tab.</p>
            </div>`;
    } catch (error) {
        console.error('Save failed:', error);
        btn.innerText = 'Failed';
        setTimeout(() => {
            btn.innerText = originalText;
            btn.disabled = false;
        }, 2000);
    }
}

async function cancelSelection() {
    try {
        await fetch('/api/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: null })
        });
        window.close();
        document.body.innerHTML = `
            <div class="container" style="text-align: center;">
                <h1 style="color: var(--text-muted);">Cancelled</h1>
                <p class="subtitle">You can safely close this tab.</p>
            </div>`;
    } catch (error) {
        window.close();
    }
}

// Add keyboard support
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        saveSelection();
    } else if (e.key === 'Escape') {
        cancelSelection();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (fields.length === 0) return;
        
        let idx = fields.findIndex(f => f.path === selectedPath);
        if (e.key === 'ArrowDown') {
            idx = (idx + 1) % fields.length;
        } else {
            idx = (idx - 1 + fields.length) % fields.length;
        }
        selectField(fields[idx].path);
        
        // Ensure selected item is visible
        const cards = document.querySelectorAll('.field-card');
        if (cards[idx]) {
            cards[idx].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }
});

async function fetchCapturedText() {
    try {
        const response = await fetch('/api/captured');
        const data = await response.json();
        const textarea = document.getElementById('previewText');
        if (textarea) {
            textarea.value = data.text || '';
        }
    } catch (error) {
        console.error('Error fetching captured text:', error);
        const textarea = document.getElementById('previewText');
        if (textarea) {
            textarea.value = '[Failed to load captured text]';
        }
    }
}

// Initialize
fetchFields();
fetchCapturedText();
