// "none" analytics backend: no SDK, no network. analytics.js (the ANALYTICS
// facade) sanitizes every call and then calls these inner methods. To turn
// on GameAnalytics (itch.io, Y8 or local builds only: GamePix and Playgama
// forbid third-party analytics, see docs/platform-sdk.md) replace the body
// of each method with the GameAnalytics call in its REPLACE marker and load
// the GameAnalytics SDK plus this file's replacement in index.html.
// Docs for every marker: https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
var ANALYTICS_BACKEND = {
    backendId: 'none',

    // config: {build}
    // REPLACE: GameAnalytics.configureBuild(config.build); GameAnalytics.initialize(gameKey, secretKey)
    // https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
    initialize(config) {},

    // REPLACE: GameAnalytics.startSession()
    // https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
    startSession() {},

    // REPLACE: GameAnalytics.endSession()
    // https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
    endSession() {},

    // status: 'Start' | 'Complete' | 'Fail' (EGAProgressionStatus)
    // REPLACE: GameAnalytics.addProgressionEvent(EGAProgressionStatus[status], p1, p2, p3, score)
    // https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
    addProgressionEvent(status, p1, p2, p3, score) {},

    // REPLACE: GameAnalytics.addDesignEvent(id, value)
    // https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
    addDesignEvent(id, value) {},

    // severity: 'debug' | 'info' | 'warning' | 'error' | 'critical' (EGAErrorSeverity)
    // REPLACE: GameAnalytics.addErrorEvent(EGAErrorSeverity[severity], message)
    // https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
    addErrorEvent(severity, message) {},

    // REPLACE: GameAnalytics.addAdEvent(EGAAdAction[action], EGAAdType[type], sdkName, placement)
    // https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
    addAdEvent(action, type, sdkName, placement) {},
}
