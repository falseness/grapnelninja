// Build configuration. This file is the repo (dev) default: every mode is
// playable and the local platform backend is used. A release build replaces
// this one file (e.g. modes: ['grapple_over'] for the itch.io, GamePix and Y8
// builds, which ship Grapple Over only). Those single-mode release zips also
// leave out the scripts only the bad and classic modes need (tools/
// build_release.py OTHER_MODE_SCRIPTS; a generated stub keeps their names).
//   platform: the platform backend the build is made for
//   modes:    the game modes the build can enter; boot starts Grapple Over
//             when it is listed, else modes[0]
//   y8:       Y8 ids (filled by the Y8 build)
const BUILD_CONFIG = {platform: 'local', modes: ['grapple_over', 'bad', 'classic'], y8: {appId: '', gameId: ''}}

// Whether the build can enter mode
function buildHasMode(mode)
{
    return BUILD_CONFIG.modes.includes(mode)
}
// Whether the game may use the Escape key. Playgama (requirement 1.5.2)
// reserves Escape for the browser leaving full screen: there P pauses and the
// Go back dialog answers to arrows, Enter/Space and its buttons only.
function buildUsesEscape()
{
    return BUILD_CONFIG.platform !== 'playgama'
}
// The mode a launch starts in
function buildBootMode()
{
    return buildHasMode('grapple_over') ? 'grapple_over' : BUILD_CONFIG.modes[0]
}
