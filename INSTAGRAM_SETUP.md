# Connecting Instagram (via Metricool)

Why Metricool: Instagram has no direct Claude connector, and Meta's own API needs a developer app and weeks of review. Metricool is free, connects to Instagram in a few clicks, and has an official Claude connector.

Requirement: your Instagram must be a **Business or Creator** account (Instagram app > Settings > Account type and tools > Switch to professional account). Free.

## 1. Metricool (5 min)
1. Sign up free at metricool.com.
2. Connect Instagram when it asks (log in through Facebook/Instagram and approve).
3. Wait a few minutes for it to pull your stats.

## 2. Connect Metricool to Claude (2 min)
1. Go to claude.ai > Customize > Connectors > **Add custom connector**.
2. Name: `Metricool`  URL: `https://ai.metricool.com/mcp`
3. Click Connect and approve on Metricool's screen.
4. Test in a normal Claude chat: "Using Metricool, how many Instagram followers do I have?" Check the number against the Instagram app with your own eyes.

## 3. Let Piper use it (Claude Code)
1. Install Node.js (nodejs.org, LTS), then in Command Prompt: `npm install -g @anthropic-ai/claude-code`
2. `cd` into this folder, run `claude`, log in with your claude.ai account (NOT an API key, or connectors won't load).
3. Type `/mcp` and confirm Metricool is listed.
4. Say: **update my Instagram**. It runs the instagram-stats skill, overwrites connectors/instagram.json with real data, and refreshes the dashboard.
5. Refresh the browser: the SAMPLE DATA chip disappears and Instagram turns green.

## No Claude Code yet? Manual route
Ask Claude in a normal chat (with Metricool connected): "Pull my Instagram stats and fill in this JSON", paste connectors/instagram.json, then save the reply over the file and restart Piper.
