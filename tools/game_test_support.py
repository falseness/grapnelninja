"""Shared constants for browser tests of the SDK-free game.

The game loads no platform SDK (platform.js is the local adapter), so a
test that routes the Playgama Bridge URL never sees a request for it: SDK is
the URL those routes name and FAKE is the (empty) script they would serve.
"""
from browser_test_support import SDK_URL

SDK = SDK_URL
FAKE = ''
