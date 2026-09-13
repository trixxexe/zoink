"""Visual Theme System for ZoinK TUI.

Provides restrained, terminal-friendly palettes with auto/dark/light modes.
"""

from __future__ import annotations

from prompt_toolkit.styles import Style

THEME_MODES = ("auto", "dark", "light")


def get_style(mode: str = "auto") -> Style:
    """Return prompt_toolkit Style for the specified theme mode."""
    if mode == "light":
        return Style.from_dict({
            # Base text
            "primary": "#111827 bold",
            "secondary": "#374151",
            "muted": "#6b7280",
            "dim": "#9ca3af",
            "border": "#d1d5db",
            "border.focus": "#0284c7",
            # Logo & Branding
            "logo": "#0284c7 bold",
            "tagline": "#4b5563 italic",
            "watermark": "#9ca3af",
            # Controls & Inputs
            "input.frame": "#cbd5e1",
            "input.frame.focus": "#0284c7 bold",
            "input.text": "#0f172a bold",
            "input.cursor": "#ffffff bold bg:#0284c7",
            "input.placeholder": "#94a3b8 italic",
            # Lists & Selection
            "choice.cursor": "#0284c7 bold",
            "choice.selected": "#0284c7 bold bg:#e0f2fe",
            "choice.item": "#1e293b",
            "choice.desc": "#64748b",
            # Action Button
            "button.zoink": "#ffffff bold bg:#0284c7",
            "button.zoink.hover": "#ffffff bold bg:#0369a1",
            "button.secondary": "#334155 bg:#f1f5f9",
            # Status & Progress
            "status.spinner": "#0284c7 bold",
            "progress.bar.filled": "#0284c7",
            "progress.bar.empty": "#e2e8f0",
            "progress.pct": "#0f172a bold",
            "progress.meta": "#64748b",
            # Feedback
            "success": "#16a34a bold",
            "error": "#dc2626 bold",
            "badge": "#0369a1 bg:#f0f9ff",
            # Footer
            "footer.key": "#0f172a bold",
            "footer.action": "#475569",
            "footer.sep": "#cbd5e1",
        })

    elif mode == "dark":
        return Style.from_dict({
            # Base text
            "primary": "#f8fafc bold",
            "secondary": "#cbd5e1",
            "muted": "#94a3b8",
            "dim": "#64748b",
            "border": "#334155",
            "border.focus": "#38bdf8",
            # Logo & Branding
            "logo": "#38bdf8 bold",
            "tagline": "#94a3b8 italic",
            "watermark": "#64748b",
            # Controls & Inputs
            "input.frame": "#334155",
            "input.frame.focus": "#38bdf8 bold",
            "input.text": "#ffffff bold",
            "input.cursor": "#0f172a bold bg:#38bdf8",
            "input.placeholder": "#64748b italic",
            # Lists & Selection
            "choice.cursor": "#38bdf8 bold",
            "choice.selected": "#f8fafc bold bg:#1e293b",
            "choice.item": "#e2e8f0",
            "choice.desc": "#94a3b8",
            # Action Button
            "button.zoink": "#0f172a bold bg:#38bdf8",
            "button.zoink.hover": "#0f172a bold bg:#7dd3fc",
            "button.secondary": "#cbd5e1 bg:#1e293b",
            # Status & Progress
            "status.spinner": "#38bdf8 bold",
            "progress.bar.filled": "#38bdf8",
            "progress.bar.empty": "#1e293b",
            "progress.pct": "#f8fafc bold",
            "progress.meta": "#94a3b8",
            # Feedback
            "success": "#4ade80 bold",
            "error": "#f87171 bold",
            "badge": "#38bdf8 bg:#0f172a",
            # Footer
            "footer.key": "#f8fafc bold",
            "footer.action": "#94a3b8",
            "footer.sep": "#475569",
        })

    else:
        # "auto" — uses terminal default foreground and background gracefully
        return Style.from_dict({
            # Base text
            "primary": "bold",
            "secondary": "",
            "muted": "#888888",
            "dim": "#666666",
            "border": "#555555",
            "border.focus": "#00d7d7 bold",
            # Logo & Branding
            "logo": "#00d7d7 bold",
            "tagline": "#888888 italic",
            "watermark": "#666666",
            # Controls & Inputs
            "input.frame": "#555555",
            "input.frame.focus": "#00d7d7 bold",
            "input.text": "bold",
            "input.cursor": "bold reverse",
            "input.placeholder": "#777777 italic",
            # Lists & Selection
            "choice.cursor": "#00d7d7 bold",
            "choice.selected": "bold reverse",
            "choice.item": "",
            "choice.desc": "#888888",
            # Action Button
            "button.zoink": "bold reverse",
            "button.zoink.hover": "#00d7d7 bold reverse",
            "button.secondary": "reverse",
            # Status & Progress
            "status.spinner": "#00d7d7 bold",
            "progress.bar.filled": "#00d7d7",
            "progress.bar.empty": "#333333",
            "progress.pct": "bold",
            "progress.meta": "#888888",
            # Feedback
            "success": "#00ff87 bold",
            "error": "#ff5f5f bold",
            "badge": "#00d7d7",
            # Footer
            "footer.key": "bold",
            "footer.action": "#888888",
            "footer.sep": "#555555",
        })


def next_theme_mode(current: str) -> str:
    """Cycle to the next theme mode."""
    idx = THEME_MODES.index(current) if current in THEME_MODES else 0
    return THEME_MODES[(idx + 1) % len(THEME_MODES)]
