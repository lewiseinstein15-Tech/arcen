"""Event card factory registry — filled from TUI-07 onward.

Each frozen/v2 stream event maps to a Rich renderable card rendered on the
narration spine. The registry is data-driven so ARCEN² harness events can
register their own cards without touching the spine (TUI-10, H-20).
"""
