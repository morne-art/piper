# Piper

Your personal command-center dashboard. It talks in a natural British voice that runs entirely on your PC, answers questions about your Instagram, and learns from a folder of your own documents.

## First time only
Double-click **install.bat**. It installs the voice engine and document readers, then downloads the voice model (about 120 MB). Takes a few minutes.

## Every day
Double-click **start-piper.bat**. It opens http://localhost:8790. Close the black window to stop.

## Using it
- **BRIEF ME**: your spoken rundown. Click again to stop.
- **🎙 TALK** (Edge or Chrome): "Hey Piper, how's my Instagram doing?", "when should I post?", "what's my posting goal?"
- Or type in the ask box.
- **⚙ (bottom right)**: preview voices and click ★ SET AS DEFAULT, choose the voice (George, Lewis, Daniel, Fable, Emma, Isabella), change the speed, and set your **knowledge folder**.

## Connections (⚙ > CONNECTIONS)
Log in to your accounts right inside Piper. Each card has step-by-step instructions.
- **Instagram**: via Claude + Metricool. Ask Claude "update Piper with my Instagram", paste the result, click IMPORT.
- **Gmail**: paste your address + a Google App Password (button opens the right page).
- **Google Calendar**: paste your calendar's secret iCal link (button opens the right page).
- **Shopify**: paste a read-only Admin API token.
- **Stripe**: paste a restricted, read-only key.
Safety: keys are stored in Windows Credential Manager (not in files), all access is read-only, Piper only listens on this PC, and it refreshes everything automatically every 30 minutes.

## Upload a database (⚙ > KNOWLEDGE > UPLOAD)
Drop in a ZIP containing an SQL export, a SQLite copy and an instructions file (or any single file).
- The ZIP is unpacked into knowledge/uploads and learned automatically.
- SQLite databases are opened READ-ONLY, so Piper can never change your data. If there's only a .sql export, Piper restores it into a SQLite copy.
- Files with readme / instructions / guide / notes in the name are treated as instructions for the data.
- Ask out loud: "how many orders are pending?", "what tables are in the database?", "who lives in Ramsey?"
- Click a table name to preview it, or type your own SELECT query.

## Piper's brain (real conversation)
Piper uses a language model to understand you, follow a conversation and combine facts from everywhere it knows.
- Automatic: Ollama if it's running on this PC, otherwise the built-in brain inside Piper's folder, otherwise Claude Code.
- Built-in brain: install.bat downloads the engine and a model sized to the PC's memory (small 1.1 GB, medium 2.4 GB, large 4.7 GB). It travels with the folder, so Piper can talk on any PC with no internet. Choose a size yourself with: python setup_brain.py small|medium|large
- Database questions: the model can look things up in your database itself (read-only).
- Memory: Piper remembers the conversation for follow-ups, and starts fresh after 30 quiet minutes or when you press NEW CONVERSATION.
- piper-script.md is the rulebook: personality, rules, fixed answers (instant and word for word) and example replies. Edit it in ⚙ → BRAIN.

## Piper on your phone (home and away)
1. Install Tailscale on the PC (tailscale.com, free) and sign in.
2. Double-click enable-phone.bat and choose a PIN (6+ digits). Turn on "HTTPS Certificates" if it asks.
3. Install Tailscale on your phone, sign in with the same account, open the https:// address it shows, enter your PIN.
4. Add to Home Screen for an app icon. The PC must be on with Piper running. Switch off any time with disable-phone.bat.
Only your own devices can reach Piper; nothing is opened to the internet, and the PIN locks out after 5 wrong tries.

## Awareness and curiosity
- Piper knows your location, local time and live weather (Open-Meteo, free, no key). Change it by saying "I'm in Cape Town".
- "What are you thinking about?" draws on your real day: calendar, emails, priorities, weather, things it read, and what it's curious about you.
- "Go learn something" / "tell me a random fact": Piper reads an article from your libraries or Wikipedia. While idle, it reads one an hour (idle_learning in config.json).
- Now and then Piper asks one question to get to know you, and remembers your answer.

## Long-term memory
Piper remembers across restarts and PCs (brain\piper_memory.json, travels with the folder, backed up daily to backups\ for 14 days).
- "Remember that my shop is called…", "forget my…", "what do you remember about me?"
- It also notices clear facts ("my wife is…", "I live in…"), preferences ("I prefer…", "don't…") and your corrections ("no, I meant…"), and uses them in future answers.
- Ask "what are you thinking?" or "what do you know?" and Piper answers from its real state. Say "run a self-test" to check every part.
- Text from files, libraries and websites is treated as information only: it can never change Piper's identity or rules.

## Wikipedia (offline + online)
Piper answers general questions ("what is…", "who was…", "tell me about…") from Wikipedia.
- ZIM files (Kiwix): put them in the wiki folder and they work instantly, no import. ZIMs elsewhere: paste the folder in IMPORT FROM THIS PC.
- Other offline data sets: upload them in ⚙ > KNOWLEDGE, or paste a file/folder path and press IMPORT FROM THIS PC for huge files. Works with .xml.bz2 dumps, .jsonl/.json, .csv (title + text), .parquet and Kiwix .zim. Stored in wiki/wiki.sqlite, searchable with no internet.
- Online: if the PC is online, Piper looks things up on Wikipedia directly. No key, no account.
- Learning: anything looked up online is saved, so next time it's answered offline. Turn either off with the checkboxes.
- Say "look up X online" to force a fresh online lookup.

## Using Piper on another PC
Copy the whole piper folder (USB stick, OneDrive, anywhere) and double-click start-piper.bat. On a new PC it sets itself up automatically, installing Python if needed. Your Wikipedia data, knowledge and Instagram data travel with the folder. Saved logins (Gmail etc.) stay on the PC they were entered on, for safety.

## Knowledge folder
Piper reads every PDF, Word document (.docx), text/markdown note, CSV, JSON and HTML file in a folder (including subfolders) and answers questions from them, telling you which file the answer came from.
1. Click ⚙, paste a folder path, for example `C:\Users\Morne\Documents\Business`.
2. Click **LEARN**.
3. Ask away. When you add or change files, Piper notices on the next start, or click LEARN again.
Nothing leaves your PC. The learned index is saved in knowledge_index.json.
The included `knowledge` folder has an example note, replace it with your own.

Offline, Piper answers by quoting the most relevant lines from your files. When you install Claude Code later and set `PIPER_MODE=live`, Claude reads those same passages and answers in its own words.

## Files you edit
config.json (name, voice, port), priorities.md, connectors/instagram.json (sample until Metricool syncs), CLAUDE.md.

## Rules baked in
Drafts only, never sends or posts. Missing data is shown as offline, never guessed.
