"""The pin domain: what a pin can be and how it may change, as pure values and functions.

Nothing in this package reads files, the clock, subprocesses or HTTP (coding rule R1,
docs/handbook/code-style-roadmap.md). server.py loads records under the pin lock, calls in here, and
saves what comes back; the HTTP layer turns each outcome into a response.
"""
