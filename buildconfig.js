// Build configuration. This file is the repo (dev) default: every mode is
// playable and the local platform backend is used. A release build replaces
// this one file (e.g. modes: ['grapple_over'] for the itch.io, GamePix and Y8
// builds, which ship Grapple Over only). The other modes stay in the code.
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
// The mode a launch starts in
function buildBootMode()
{
    return buildHasMode('grapple_over') ? 'grapple_over' : BUILD_CONFIG.modes[0]
}
