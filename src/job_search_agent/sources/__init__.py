"""Job source agents.

Two ways to add a source:

1. Plain RSS feed - no code needed. Add an entry to config/sources.yaml. See generic_rss.py
   and the comments at the top of that config file for the supported options.

2. Anything else (an API needing a key, bespoke auth, non-RSS response format, etc.) - add a
   module here that exposes:

       def fetch_listings(...) -> list[Listing]

   with whatever arguments make sense for that source (see generic_rss.fetch_feed for an
   example). As long as it returns Listing objects, it plugs into the rest of the pipeline the
   same way regardless of where the data came from.
"""
