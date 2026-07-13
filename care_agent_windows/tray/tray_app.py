"""OxyPC Care Agent — customer-facing tray application (spec section 8.1).

Runs in the logged-in user's session, no administrator rights required for
normal use. Everything it shows or does goes through ipc_client.call() —
this process never touches the network, the device credential, or the
offline queue directly. That boundary is what keeps a compromised tray
process from being able to do more than the fixed IPC menu allows.
"""
import tkinter as tk
from tkinter import messagebox, simpledialog

import pystray
from PIL import Image, ImageDraw

from tray.ipc_client import call, IPCClientError

APP_NAME = "OxyPC Care Agent"

TICKET_CATEGORIES = [
    ("hardware", "Hardware issue"), ("battery", "Battery"), ("storage", "Storage / disk"),
    ("performance", "Slow performance"), ("boot", "Won't start / boot issue"),
    ("screen", "Screen issue"), ("keyboard_touchpad", "Keyboard / touchpad"),
    ("software", "Software issue"), ("warranty_query", "Warranty question"),
    ("accessory", "Accessory issue"), ("other", "Something else"),
]

DIAGNOSTIC_DISCLOSURE = (
    "To help support diagnose your issue, OxyPC Care Agent will check:\n\n"
    "  - Battery health and charge cycles\n"
    "  - Storage (disk) health\n"
    "  - CPU, RAM and basic system information\n"
    "  - Recent hardware-related system warnings\n\n"
    "This does NOT include your files, browsing history, passwords, "
    "screenshots, or anything you type. You can review exactly what was "
    "collected before it's sent, and you can decline this step and submit "
    "your ticket without it."
)


def _make_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(0, 90, 156, 255))
    draw.text((20, 18), "OP", fill=(255, 255, 255, 255))
    return img


class CareAgentTray:
    def __init__(self):
        self.icon = pystray.Icon(APP_NAME, _make_icon_image(), APP_NAME, self._build_menu())

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("View warranty status", self._show_warranty),
            pystray.MenuItem("Get support", self._get_support_flow),
            pystray.MenuItem("My tickets", self._show_tickets),
            pystray.MenuItem("Offers", self._show_offers),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Privacy & data notice", self._show_privacy_notice),
            pystray.MenuItem("Exit", self._exit),
        )

    def run(self):
        self.icon.run()

    def _exit(self, icon, item):
        icon.stop()

    # ── Menu actions ─────────────────────────────────────────────────────

    def _show_warranty(self, icon, item):
        try:
            data = call("get_warranty")
        except IPCClientError as e:
            self._error(str(e))
            return
        status = (data.get("status") or "unknown").replace("_", " ").title()
        days_left = data.get("days_left")
        msg = f"Warranty status: {status}"
        if days_left is not None:
            msg += f"\n{days_left} days remaining"
        self._info("Warranty", msg)

    def _show_offers(self, icon, item):
        try:
            data = call("get_offers")
        except IPCClientError as e:
            self._error(str(e))
            return
        offers = data.get("offers", []) if isinstance(data, dict) else []
        if not offers:
            self._info("Offers", "No current offers for your device.")
            return
        lines = [f"- {o.get('title', 'Offer')}" for o in offers[:10]]
        self._info("Offers", "\n".join(lines))

    def _show_tickets(self, icon, item):
        try:
            data = call("get_tickets")
        except IPCClientError as e:
            self._error(str(e))
            return
        tickets = data.get("tickets", []) if isinstance(data, dict) else []
        if not tickets:
            self._info("My Tickets", "You have no support tickets yet.")
            return
        lines = [f"{t.get('ticket_number')} — {t.get('status', '').replace('_', ' ').title()}"
                for t in tickets[:15]]
        self._info("My Tickets", "\n".join(lines))

    def _show_privacy_notice(self, icon, item):
        self._info("Privacy & Data Notice", DIAGNOSTIC_DISCLOSURE +
                   "\n\nYou can uninstall this application at any time from Windows Settings.")

    def _get_support_flow(self, icon, item):
        root = self._hidden_root()
        try:
            category_labels = [label for _, label in TICKET_CATEGORIES]
            choice = simpledialog.askstring(
                APP_NAME, "What best describes the issue?\n\n" + "\n".join(
                    f"{i+1}. {label}" for i, label in enumerate(category_labels)
                ) + "\n\nEnter a number:",
                parent=root,
            )
            if not choice:
                return
            try:
                idx = int(choice.strip()) - 1
                category = TICKET_CATEGORIES[idx][0]
            except (ValueError, IndexError):
                self._error("Please enter a valid option number.")
                return

            description = simpledialog.askstring(
                APP_NAME, "Briefly describe the issue:", parent=root,
            )
            if not description or not description.strip():
                self._error("A description is required to submit a ticket.")
                return

            run_diagnostics = messagebox.askyesno(
                APP_NAME, DIAGNOSTIC_DISCLOSURE + "\n\nRun this check now?", parent=root,
            )

            diagnostics = None
            if run_diagnostics:
                try:
                    diagnostics = call("run_diagnostic_profile", {"profile": "support_basic_v1"})
                except IPCClientError as e:
                    self._error(f"Diagnostics failed, continuing without them: {e}")
                    diagnostics = None

            try:
                result = call("submit_ticket", {
                    "category": category, "description": description.strip(),
                    "customer_contact_preference": "whatsapp",
                    "diagnostics": diagnostics,
                })
            except IPCClientError as e:
                self._error(f"Could not submit ticket: {e}")
                return

            if result.get("queued"):
                self._info("Ticket Queued", "You're offline — your ticket will be sent "
                                           "automatically once you're back online.")
            else:
                self._info("Ticket Submitted", f"Reference: {result.get('ticket_number', '—')}\n"
                                              "Our support team will follow up shortly.")
        finally:
            root.destroy()

    # ── Small tk helpers (pystray has no native dialogs) ───────────────

    def _hidden_root(self) -> tk.Tk:
        root = tk.Tk()
        root.withdraw()
        return root

    def _info(self, title, message):
        root = self._hidden_root()
        messagebox.showinfo(title, message, parent=root)
        root.destroy()

    def _error(self, message):
        root = self._hidden_root()
        messagebox.showerror(APP_NAME, message, parent=root)
        root.destroy()


if __name__ == "__main__":
    CareAgentTray().run()
