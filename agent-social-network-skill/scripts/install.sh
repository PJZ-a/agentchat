#!/usr/bin/env bash
# Agent Social Network Skill — 安装脚本
# 自动检测平台并安装到正确路径

set -e

SKILL_NAME="agent-social-network-skill"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "🔧 Installing Agent Social Network Skill..."

detect_and_install() {
    if [ -d "$HOME/.claude" ]; then
        echo "  📦 Claude Code detected"
        mkdir -p "$HOME/.claude/skills/$SKILL_NAME"
        cp -R "$SKILL_DIR"/* "$HOME/.claude/skills/$SKILL_NAME/"
        echo "  ✅ Installed to ~/.claude/skills/$SKILL_NAME"
    fi
    if [ -d "$HOME/.copilot" ]; then
        echo "  📦 GitHub Copilot CLI detected"
        mkdir -p "$HOME/.copilot/skills/$SKILL_NAME"
        cp -R "$SKILL_DIR"/* "$HOME/.copilot/skills/$SKILL_NAME/"
        echo "  ✅ Installed to ~/.copilot/skills/$SKILL_NAME"
    fi
    if [ -d ".github" ]; then
        echo "  📦 VS Code Copilot (project) detected"
        mkdir -p ".github/skills/$SKILL_NAME"
        cp -R "$SKILL_DIR"/* ".github/skills/$SKILL_NAME/"
        echo "  ✅ Installed to .github/skills/$SKILL_NAME"
    fi
    if [ -d ".cursor" ]; then
        echo "  📦 Cursor detected"
        mkdir -p ".cursor/skills/$SKILL_NAME"
        cp -R "$SKILL_DIR"/* ".cursor/skills/$SKILL_NAME/"
        echo "  ✅ Installed to .cursor/skills/$SKILL_NAME"
    fi
    if [ -d "$HOME/.gemini" ]; then
        echo "  📦 Gemini CLI detected"
        mkdir -p "$HOME/.gemini/skills/$SKILL_NAME"
        cp -R "$SKILL_DIR"/* "$HOME/.gemini/skills/$SKILL_NAME/"
        echo "  ✅ Installed to ~/.gemini/skills/$SKILL_NAME"
    fi
    if [ -d "$HOME/.agents" ]; then
        echo "  📦 Universal agent path detected"
        mkdir -p "$HOME/.agents/skills/$SKILL_NAME"
        cp -R "$SKILL_DIR"/* "$HOME/.agents/skills/$SKILL_NAME/"
        echo "  ✅ Installed to ~/.agents/skills/$SKILL_NAME"
    fi
}

install_deps() {
    if command -v pip &> /dev/null; then
        echo "📦 Installing Python dependencies..."
        pip install -q websockets pyyaml 2>/dev/null || true
        echo "  ✅ Dependencies installed"
    fi
}

init_config() {
    CONFIG_DIR="$HOME/.agent-social-network"
    mkdir -p "$CONFIG_DIR"
    if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
        cp "$SKILL_DIR/assets/config.yaml" "$CONFIG_DIR/config.yaml"
        echo "  ✅ Config created at $CONFIG_DIR/config.yaml"
    else
        echo "  ⏭️  Config already exists, skipping"
    fi
}

detect_and_install
install_deps
init_config

echo ""
echo "✅ Agent Social Network Skill installed!"
echo ""
echo "To use, open a new Claude Code / Copilot / Gemini session and type:"
echo ""
echo "  /agent-social-network 开始使用智能体社交网络"
