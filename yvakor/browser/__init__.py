"""YVAKOR — Controle do navegador (Edge + Chrome)."""
from yvakor.browser.manager import Navegadores
from yvakor.browser.session import BrowserSession
from yvakor.browser.tools import register_browser_tools

__all__ = ["BrowserSession", "Navegadores", "register_browser_tools"]
