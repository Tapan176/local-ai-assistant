# TAPAN_AI Testing & Validation Guide

## Quick Start Verification

Follow these steps to verify all improvements are working correctly.

---

## Test 1: Basic Functionality ✅

### 1.1 Start the Application

```bash
python start_agent.py
```

**Expected Output**:
```
Loading TAPAN_AI (SQLite-First)...
✨ Jarvis Event Loop Active (Type 'help' for commands)
🚀 TAPAN_AI Event Loop Started
   - Input: Thread-safe queue
   - Tasks: Main thread polling
```

### 1.2 Test Basic Commands

```
> help
> show balance
> add account savings
> expense 500 food
> show memories
> who is alice
```

**Expected**: Each command executes without errors. No "Semantic Parse Error" messages.

---

## Test 2: Intent Parser Improvements ✅

### 2.1 Test False Positive Fix

Try these commands that previously caused false positives:

```
> feeling low
>> Expected: Chat response about emotions (NOT finance data)

> show memories
>> Expected: List of saved memories (NOT account balance)

> koi reminder hai
>> Expected: Reminder list (NOT "Total Balance: ₹0")

> are you responding same thing everyday
>> Expected: Conversation response (NOT finance data)
```

**Verification**:
- ✅ Finance data only appears when asking about accounts/balance
- ✅ Non-finance queries don't trigger finance tool
- ✅ More specific intent matching

---

## Test 3: Error Handling ✅

### 3.1 Test Parameter Handling

```bash
# This previously caused: "Semantic Parse Error: max_tokens"
ollama serve
# In another terminal:
python start_agent.py
> some query that triggers LLM

# Expected: No max_tokens error, smooth LLM response
```

**Verification**:
- ✅ No "Semantic Parse Error" messages
- ✅ All LLM backends handle parameters gracefully

---

## Test 4: Voice-Chat Sync ✅

### 4.1 Start with Voice Interface

```bash
python start_agent.py --voice
```

**Expected Output**:
```
Loading TAPAN_AI (SQLite-First)...
🎤 Initializing Voice Interface...
🎤 Voice Interface Active
✨ Jarvis Event Loop Active
🚀 TAPAN_AI Event Loop Started
```

### 4.2 Test Voice Input

1. Speak clearly: "Hello Jarvis, add expense 500 food"
2. System responds with voice (TTS)
3. Enter text mode: type "show memories"

### 4.3 Verify Voice-Chat Sync

```bash
# Check chat history database
sqlite3 data/chat_history.db "SELECT user_input, source, sentiment_label FROM turns LIMIT 5;"
```

**Expected Output**:
```
Hello Jarvis add expense 500 food|voice|neutral
show memories|text|neutral
```

**Verification**:
- ✅ Voice input shows source="voice"
- ✅ Text input shows source="text"
- ✅ Both stored in unified history
- ✅ Sentiment analyzed for both

---

## Test 5: Sentiment Analysis ✅

### 5.1 Test Sentiment Detection

```bash
# Happy sentiment
> I love this! It's amazing!
# Check database
sqlite3 data/chat_history.db "SELECT sentiment_label, sentiment_valence FROM turns WHERE sentiment_label='happy';"
# Expected: Shows sentiment_label='happy', high valence (~0.5-1.0)

# Sad sentiment
> I'm feeling terrible and exhausted
# Check database
sqlite3 data/chat_history.db "SELECT sentiment_label, sentiment_valence FROM turns WHERE sentiment_label='sad';"
# Expected: Shows sentiment_label='sad', low valence (~-0.5--1.0)

# Neutral sentiment
> What is 2 + 2?
# Check database
sqlite3 data/chat_history.db "SELECT sentiment_label FROM turns WHERE user_input LIKE '%2 + 2%';"
# Expected: sentiment_label='neutral'
```

**Verification**:
- ✅ Positive text gets high valence scores
- ✅ Negative text gets low valence scores
- ✅ Neutral text gets label='neutral'
- ✅ Sentiment persisted to database

### 5.2 View Sentiment Statistics

```bash
sqlite3 data/chat_history.db
sqlite> SELECT sentiment_label, COUNT(*) as count FROM turns GROUP BY sentiment_label;
sqlite> SELECT AVG(sentiment_valence) as avg_mood FROM turns;
sqlite> .quit
```

**Verification**:
- ✅ Can see sentiment distribution
- ✅ Sentiment_label appears for all turns
- ✅ Valence values range from -1.0 to 1.0

---

## Test 6: Data Persistence ✅

### 6.1 Verify Data Storage

```bash
# Check all database files exist
ls -lh data/*.db

# Expected files:
# - finances.db
# - memories.db
# - reminders.db
# - experiences.db
# - relations.db
# - knowledge.db
# - profile.db
# - chat_history.db
```

### 6.2 Test Multi-Session Persistence

**Session 1**:
```
> remember I like pizza
> expense 500 lunch
> Exit application
```

**Session 2**:
```
python start_agent.py
> show memories
# Expected: "i like pizza" should appear

> show balance
# Expected: Account should show expense was recorded
```

**Verification**:
- ✅ Memories persist across sessions
- ✅ Finances persist across sessions
- ✅ Chat history accumulates
- ✅ Zero data loss

### 6.3 Verify Conversation History

```bash
sqlite3 data/chat_history.db "SELECT COUNT(*) as total_turns FROM turns;"
sqlite3 data/chat_history.db "SELECT timestamp, user_input, source FROM turns ORDER BY timestamp DESC LIMIT 10;"
```

**Verification**:
- ✅ All conversations logged
- ✅ Source field shows voice/text
- ✅ Timestamps recorded
- ✅ Can query conversation history

---

## Test 7: Backup & Recovery ✅

### 7.1 Verify Backup Functionality

```bash
# Backups should exist
ls -la data/backups/

# View latest backup
ls -la data/backups/2024-02-*/

# Check backup integrity
sqlite3 data/backups/2024-02-17/chat_history.db "SELECT COUNT(*) FROM turns;"
```

**Verification**:
- ✅ Automatic daily backups created
- ✅ Backups contain all databases
- ✅ Can restore from backup

### 7.2 Test Recovery

```bash
# Simulate data loss
rm data/chat_history.db

# Restore from backup
cp data/backups/2024-02-17/chat_history.db data/

# Verify recovery
sqlite3 data/chat_history.db "SELECT COUNT(*) FROM turns;"
# Should show same count as before
```

**Verification**:
- ✅ Backup contains recoverable data
- ✅ Can restore functionality
- ✅ No data loss

---

## Test 8: Multi-Modal Conversation ✅

### 8.1 Mixed Voice and Text Input

```
python start_agent.py --voice

# Series of interactions:
1. [VOICE] "What's my balance?"
2. [TEXT] show balance
3. [VOICE] "expense 500 coffee"
4. [TEXT] show memories
5. [VOICE] "I had a great day at the gym"
```

### 8.2 Verify Unified History

```bash
sqlite3 data/chat_history.db "SELECT user_input, source, intent FROM turns WHERE intent != '' ORDER BY timestamp DESC LIMIT 10;"
```

**Expected Output shows mix**:
```
What's my balance?|voice|finance
show balance|text|finance
expense 500 coffee|voice|finance
show memories|text|memory
I had a great day at the gym|voice|experience
```

**Verification**:
- ✅ Both voice and text in one history
- ✅ Source correctly labeled
- ✅ Intent recognized correctly
- ✅ Unified view of all interactions

---

## Test 9: Error Recovery ✅

### 9.1 Test Graceful Degradation

```bash
# Intentionally cause errors (if Ollama not running):
python start_agent.py

> some question that needs LLM
# Expected: Falls back gracefully, no crash
```

**Verification**:
- ✅ App doesn't crash on missing Ollama
- ✅ Falls back to rule-based responses
- ✅ Shows helpful error messages

### 9.2 Test Invalid Input

```
> [empty input]
# Expected: No error, just skips

> ``` injection attempts ```
# Expected: Safe parsing, no SQL injection

> Very long input (thousands of characters)
# Expected: Handled gracefully, truncated if needed
```

**Verification**:
- ✅ Handles edge cases
- ✅ No crashes on bad input
- ✅ All inputs logged safely

---

## Test 10: Performance Metrics ✅

### 10.1 Measure Response Time

```bash
python << 'EOF'
import time
from src.agent.orchestrator import Orchestrator
from pathlib import Path

orch = Orchestrator(Path("data"))

# Test 1: Simple intent
start = time.time()
for _ in range(100):
    orch.process("expense 500 food")
elapsed = time.time() - start
avg = (elapsed / 100) * 1000  # ms
print(f"Simple intent avg: {avg:.1f}ms")

# Test 2: With sentiment analysis
start = time.time()
orch.process("I'm feeling really happy and excited today!")
elapsed = time.time() - start
print(f"Sentiment analysis: {elapsed*1000:.1f}ms")

# Test 3: Conversation context
start = time.time()
for _ in range(100):
    orch.process("what about that?")
elapsed = time.time() - start
avg = (elapsed / 100) * 1000
print(f"Context resolution avg: {avg:.1f}ms")
EOF
```

**Expected Results**:
```
Simple intent avg: 10-20ms
Sentiment analysis: 5-10ms
Context resolution avg: 15-25ms
```

**Verification**:
- ✅ Response time < 100ms (acceptable for CLI)
- ✅ Sentiment adds minimal overhead
- ✅ Performance scales well

---

## Test 11: Database Integrity ✅

### 11.1 Check Database Health

```bash
sqlite3 data/chat_history.db
sqlite> PRAGMA integrity_check;
# Expected: "ok" or "ok" with minor warnings

sqlite> SELECT COUNT(*) FROM turns;
# Should show non-zero count if data exists

sqlite> SELECT COUNT(*) FROM turns WHERE sentiment_label IS NOT NULL;
# Should show same as above (all have sentiment)

sqlite> .quit
```

**Verification**:
- ✅ No database corruption
- ✅ All sentiment fields populated
- ✅ Data integrity maintained

### 11.2 Check Schema

```bash
sqlite3 data/chat_history.db ".schema turns"
```

**Expected Schema**:
```
CREATE TABLE turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT,
  user_input TEXT,
  assistant_response TEXT,
  intent TEXT,
  entities TEXT,
  source TEXT,
  topic TEXT,
  sentiment_valence REAL,
  sentiment_arousal REAL,
  sentiment_label TEXT
)
```

**Verification**:
- ✅ All fields present
- ✅ Sentiment fields exist
- ✅ Source field present

---

## Checklist Summary

- [ ] Test 1: Basic Functionality ✅
- [ ] Test 2: Intent Parser Improvements ✅
- [ ] Test 3: Error Handling ✅
- [ ] Test 4: Voice-Chat Sync ✅
- [ ] Test 5: Sentiment Analysis ✅
- [ ] Test 6: Data Persistence ✅
- [ ] Test 7: Backup & Recovery ✅
- [ ] Test 8: Multi-Modal Conversation ✅
- [ ] Test 9: Error Recovery ✅
- [ ] Test 10: Performance Metrics ✅
- [ ] Test 11: Database Integrity ✅

---

## Known Limitations

1. **Wake Word Detection**: May not work in very noisy environments
2. **Sentiment Lexicon**: Uses basic lexicon, doesn't understand sarcasm
3. **Volume**: Large databases (>1GB) may experience slight slowdown
4. **Concurrency**: Not designed for concurrent user sessions

---

## Troubleshooting

### Issue: "Database is locked"
**Solution**: App is running, wait for it to finish or restart

### Issue: Voice input not working
**Solution**:
- Check microphone permissions
- Test with `python -c "import speech_recognition as sr; print('OK')"`
- Ensure audio is not muted

### Issue: Sentiment always shows "neutral"
**Solution**:
- Sentiment lexicon may need expansion
- Edit `src/agent/sentiment.py` LEXICON
- More emotion words needed

### Issue: Data not persisting
**Solution**:
- Check `data/` directory exists
- Check file permissions: `chmod 755 data/`
- Restart application to reload history

---

## Success Criteria

✅ **All Tests Pass** when:

1. No errors returned for any test
2. Data appears in database for all interactions
3. Voice input recognized (if available)
4. Sentiment values populated
5. Performance < 100ms per request
6. Database integrity check passes
7. Data survives application restart

---

**Status**: Ready for comprehensive testing
**Estimated Time**: 30-45 minutes for all tests
**Result**: Production-Ready configuration

