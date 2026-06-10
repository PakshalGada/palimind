# 🚀 PALIMIND HOTKEY - QUICK START GUIDE

## ✅ EVERYTHING IS INSTALLED AND READY!

All dependencies are installed, all tests are passing, and the system is ready to use.

---

## 🎯 THE HOTKEY FEATURE IN 30 SECONDS

**What it does**: Press **Ctrl+Shift+E** anywhere → Select Field → Text automatically captured and indexed

**Real example**:
1. Reading an article → Copy paragraph
2. Press Ctrl+Shift+E (global hotkey!)
3. Popup asks: "Which Field?"
4. You click "Research"
5. Text is saved and indexed
6. Later, you ask Palimind: "What was that article about?"
7. It finds your capture and generates an answer

---

## 🚀 HOW TO RUN (3 SIMPLE STEPS)

### **Step 1: Start the Server**
```bash
Terminal 1:
$ pm ui

# What happens:
# - FastAPI server starts (port 8000)
# - Browser opens to http://localhost:8000/ui/
# - Boardroom UI loads
# - Create or select a Field
```

### **Step 2: Start the Hotkey Listener**
```bash
Terminal 2:
$ pm hotkey start

# What happens:
# - pynput keyboard listener starts
# - Console says: "Listening on Ctrl+Shift+E"
# - Ready to capture text
```

### **Step 3: Test It!**
```bash
Terminal 3 or any application:

1. Copy text: Ctrl+C
2. Press hotkey: Ctrl+Shift+E
3. Popup appears → Select a Field
4. Done! Text is captured and indexed

Verify:
- Check: field-name/.palimind/captures/TIMESTAMP_capture.txt
- Go to browser, ask about your capture
- It works! ✨
```

---

## 📊 SYSTEM STATUS

| Component | Status |
|-----------|--------|
| **Hotkey Module** | ✅ Complete (675 lines) |
| **Test Suite** | ✅ All Passing (3/3) |
| **Dependencies** | ✅ All Installed (24 packages) |
| **Documentation** | ✅ Comprehensive |
| **Ready to Use** | ✅ YES |

---

## 📚 DOCUMENTATION

### **For Understanding (Read These)**

1. **HOTKEY_FRONT_TO_END_EXPLANATION.md** ← **START HERE**
   - Complete step-by-step explanation
   - Module-by-module breakdown
   - Data transformations
   - Technical deep dive

2. **HOTKEY_SUMMARY.md**
   - Quick reference
   - Architecture diagrams
   - How each component works
   - Dependencies list

3. **HOTKEY_COMPLETE_GUIDE.py**
   - Run: `python3 HOTKEY_COMPLETE_GUIDE.py`
   - Architecture overview
   - User workflow with diagrams
   - File interactions
   - Execution guide

### **For Verification (Run These)**

1. **test_all_steps.py** - Comprehensive test
   ```bash
   $ python3 test_all_steps.py
   # Tests all 3 steps, shows detailed output
   ```

2. **PROJECT_INDEX.py** - Project status
   ```bash
   $ python3 PROJECT_INDEX.py
   # Shows complete project structure and status
   ```

---

## 🔧 CUSTOM CONFIGURATION

### **Different Hotkey**
```bash
$ pm hotkey start --hotkey "alt+shift+c"
```

### **Remote API Server**
```bash
$ pm hotkey start --api-url "http://192.168.1.100:8000"
```

---

## ⚡ KEY FEATURES

✅ **Global Hotkey** - Works in ANY application (not just Palimind)  
✅ **Cross-Platform** - Windows, macOS, Linux  
✅ **Automatic Indexing** - No manual steps needed  
✅ **Smart Retrieval** - Vector search + full-text search  
✅ **Non-Blocking** - Doesn't freeze your UI  
✅ **Error Handling** - Graceful degradation  
✅ **Keyboard Friendly** - Arrow keys in popup, Enter to select  

---

## 🎯 COMPLETE WORKFLOW

```
You're reading something interesting...
                ↓
        Ctrl+C (copy)
                ↓
        Ctrl+Shift+E (hotkey)
                ↓
    Popup: "Which Field?"
                ↓
    Click Field (or arrow + Enter)
                ↓
File saved: field/.palimind/captures/TIMESTAMP_capture.txt
                ↓
    Automatically indexed!
                ↓
Later... in Boardroom chat:
    "What was that article?"
                ↓
Palimind retrieves your capture
    and answers your question ✨
```

---

## 📁 WHERE YOUR CAPTURES GO

```
my-field/
└── .palimind/
    └── captures/          ← Your captures saved here
        ├── 2026-06-10_14-23-45_capture.txt
        ├── 2026-06-10_14-25-12_capture.txt
        └── 2026-06-10_14-27-33_capture.txt

Each capture is automatically:
- Chunked into pieces
- Converted to embeddings
- Indexed for vector search
- Full-text searchable
```

---

## ❓ FREQUENTLY ASKED

**Q: Does it really work globally (in any app)?**
A: Yes! It uses pynput to hook into the OS keyboard at a low level.

**Q: What if my API server crashes?**
A: The capture still saves to disk. Indexing will happen when the API is back.

**Q: Can I change the hotkey?**
A: Yes: `pm hotkey start --hotkey "alt+shift+c"`

**Q: Does it work on Linux?**
A: Yes, but you need xclip or xsel: `sudo apt-get install xclip`

**Q: How is the text indexed?**
A: Chunked → Embeddings generated → Vectors stored in Turbovec → Full-text indexed in SQLite

**Q: Can I query all my captures?**
A: Yes! Type any question in Boardroom and it searches all your captures.

---

## 🧪 TESTING CHECKLIST

- [ ] Run `python3 test_all_steps.py` - All 3 tests pass
- [ ] Run `pm ui` - Server starts, browser opens
- [ ] Run `pm hotkey start` - Listener starts
- [ ] Copy text, press Ctrl+Shift+E, select field
- [ ] Check `field/.palimind/captures/` - File exists
- [ ] Go to browser, ask about your capture
- [ ] See answer generated from your capture ✨

---

## 🎉 YOU'RE ALL SET!

Everything is installed, tested, and ready to use.

**Next step**: Run `pm ui` in one terminal and `pm hotkey start` in another!

For detailed explanation: Read `HOTKEY_FRONT_TO_END_EXPLANATION.md`

---

*Questions? All documentation is in the repo.*  
*Happy capturing! 🚀*
