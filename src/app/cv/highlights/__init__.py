"""Highlight pipeline package (Milestone 5).

Derives highlight-worthy events from a completed video job, ranks them, extracts
padded sub-clips with ffmpeg and stitches them into a single reel MP4. The
master reel covers all events for all players; an optional per-player filter
produces a minimal raw cut from the same clips.
"""
